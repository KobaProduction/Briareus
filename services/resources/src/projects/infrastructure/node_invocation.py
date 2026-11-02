"""Project-filtered, bounded private account read; never a cross-owner SQL join."""

from uuid import UUID

from cryptography.fernet import Fernet
from sqlalchemy import or_, select

from common.platform_db import PlatformDatabase
from projects._resource_persistence import IntegrationRow
from projects.application.node_invocation import (
    GitHubPolicy,
    GitLabPolicy,
    GitRuntimePolicy,
    InvocationContext,
    InvocationPolicies,
    ProjectAccount,
)
from projects.domain.node_invocation import (
    AccountProvenance,
    ProviderModule,
    ProviderSelection,
    require_current_accounts,
)
from projects.domain.provider_endpoints import ProviderEndpoint
from projects.infrastructure.connection_metadata import (
    StoredGitHubPolicy,
    StoredGitLabPolicy,
)
from projects.infrastructure.integration_settings_jsonb import connection_metadata
from projects.infrastructure.provider_connections import CredentialEnvelope
from runtime_peer.connection_contracts import GitLabPolicyForm, GitPolicyForm
from service_runtime.platform_db_mechanics import _DatabaseCipherBinding


def public_account(row: IntegrationRow) -> ProjectAccount:
    options = connection_metadata(row.provider_settings)
    endpoint = ProviderEndpoint(options.base_url).value
    if not endpoint or row.provider not in {"github", "gitlab", "coolify", "signoz"}:
        raise ValueError("Current validated provider endpoint required")
    return ProjectAccount(
        id=row.id,
        alias=row.alias,
        provider=row.provider,
        auth_type=row.auth_type,
        base_url=endpoint,
        external_id=options.external_id or None,
        verify_tls=True,
        ca_cert_pem=options.ca_cert_pem or None,
        enabled=True,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


def connection_policies(row: IntegrationRow) -> InvocationPolicies:
    if row.provider == "github":
        github = StoredGitHubPolicy.model_validate_json(
            row.provider_settings.model_dump_json(exclude_unset=True)
        ).git_policy
        return InvocationPolicies(
            github=GitHubPolicy(
                protected_branches=github.protected_branches,
                required_checks=github.required_checks,
                required_reviewers=github.required_reviewers,
            ),
            github_runtime=runtime_policy(github),
        )
    gitlab = StoredGitLabPolicy.model_validate_json(
        row.provider_settings.model_dump_json(exclude_unset=True)
    ).git_policy
    return InvocationPolicies(
        gitlab=GitLabPolicy(protected_branches=gitlab.protected_branches),
        gitlab_runtime=runtime_policy(gitlab),
    )


def runtime_policy(policy: GitPolicyForm | GitLabPolicyForm) -> GitRuntimePolicy:
    return GitRuntimePolicy(
        local_first_guidance=policy.local_first_guidance,
        local_git_transport_enabled=policy.local_git_transport_enabled,
        remote_source_mutations_enabled=policy.remote_source_mutations_enabled,
    )


class SqlInvocationAccounts(_DatabaseCipherBinding[PlatformDatabase, Fernet]):
    async def load(
        self,
        project_uuid: UUID,
        module: ProviderModule,
        selection: ProviderSelection,
    ) -> InvocationContext:
        providers = {"github", "gitlab"} if module == "svc" else {"signoz", "coolify"}
        if selection.provider is not None:
            providers &= {selection.provider}
        statement = select(IntegrationRow).where(
            IntegrationRow.owner_project_id == project_uuid,
            IntegrationRow.owner_team_id.is_(None),
            IntegrationRow.deleted_at.is_(None),
            IntegrationRow.provider.in_(providers),
        )
        if selection.account is not None:
            try:
                selected_id = UUID(selection.account)
            except ValueError:
                selected_id = None
            alias = IntegrationRow.alias_key == selection.account.casefold()
            statement = statement.where(
                or_(alias, IntegrationRow.id == selected_id) if selected_id else alias
            )
        async with self._database.transaction() as tx:
            rows = list(await tx.scalars(statement.order_by(IntegrationRow.id).limit(65)))
            require_current_accounts(
                tuple(
                    AccountProvenance(
                        row.owner_project_id,
                        row.owner_team_id,
                        row.deleted_at is not None,
                        row.provider,
                    )
                    for row in rows
                ),
                project_uuid,
                frozenset(providers),
                selected=selection.account is not None,
            )
            accounts = tuple(public_account(row) for row in rows)
            if selection.account is not None:
                accounts = (
                    accounts[0].model_copy(
                        update={"credential": self._credential(rows[0], project_uuid)}
                    ),
                )
                if module == "svc":
                    return InvocationContext(
                        accounts=accounts, policies=connection_policies(rows[0])
                    )
            return InvocationContext(accounts=accounts)

    def _credential(self, row: IntegrationRow, project_uuid: UUID) -> str:
        envelope = CredentialEnvelope.model_validate_json(
            self._cipher.decrypt(row.encrypted_credential.encode())
        )
        if (
            envelope.connection != row.id
            or envelope.project != project_uuid
            or not 0 < len(envelope.token) <= 32768
        ):
            raise ValueError("Current connection credential binding invalid")
        return envelope.token
