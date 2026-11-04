from __future__ import annotations

import asyncio
import hashlib
import tempfile
import unittest
from pathlib import Path

from auth_service.provider import MultiResourceZitadelProvider, RefreshExchangeReplay
from briareus_mcp_resources import allowed_resource_urls, resource_url
from briareus_mcp_support import McpAuthorityHarness
from briareus_support import ISSUER, ORIGIN, SUBJECT
from key_value.aio.adapters.pydantic import PydanticAdapter
from mcp.server.auth.provider import RefreshToken, TokenError
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


class ControlledUpstreamProvider(MultiResourceZitadelProvider):
    """Use the production refresh coordinator and durable encrypted replay adapter.

    Only the external identity exchange and observational audit port are replaced.
    """

    def __init__(self, directory: Path) -> None:
        self.harness = McpAuthorityHarness(directory)
        self.token_authority = self.harness.authority
        self._refresh_token_store = self.harness.refresh_metadata
        self._jti_mapping_store = self.harness.mappings
        self._upstream_token_store = self.harness.upstream
        self._allowed_resources = allowed_resource_urls(ORIGIN)
        self._root_resource = resource_url(ORIGIN, "root")
        self._refresh_exchange_locks = {}
        self._refresh_exchange_replays = {}
        self._refresh_exchange_replay_store = PydanticAdapter[RefreshExchangeReplay](
            key_value=self.harness.storage,
            pydantic_model=RefreshExchangeReplay,
            default_collection="koba-oauth-refresh-replays",
            raise_on_validation_error=True,
        )
        self.exchanges = 0
        self.events: list[str] = []

    async def _session_id_from_jti(self, jti: str) -> str:
        del jti
        return "test-upstream-session"

    async def _upstream_refresh_identity(self, refresh_jti: str) -> tuple[str, str]:
        del refresh_jti
        return "test-upstream-session", "test-upstream-fingerprint"

    async def _exchange_refresh_once(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
        resource: str,
    ) -> OAuthToken:
        self.exchanges += 1
        await asyncio.sleep(0)
        pair = await self.harness.issue(client_id=client.client_id or "", resource=resource)
        # FastMCP 4.1.2 removes the consumed refresh metadata and JTI on rotation.
        old_claims = self.harness.issuer(resource).verify_token(
            refresh_token.token, expected_token_use="refresh"
        )
        await self.harness.mappings.delete(key=old_claims["jti"])
        await self.harness.refresh_metadata.delete(
            key=hashlib.sha256(refresh_token.token.encode()).hexdigest()
        )
        return OAuthToken(
            access_token=pair.access,
            token_type="Bearer",
            refresh_token=pair.refresh,
            expires_in=300,
            scope=" ".join(scopes),
        )

    async def _record_token_result(
        self,
        *,
        client: OAuthClientInformationFull,
        resource: str,
        result: OAuthToken,
        event_name: str,
        session_id: str = "",
    ) -> str:
        del client, resource, result
        self.events.append(event_name)
        return session_id


class McpRefreshReplayContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.provider = ControlledUpstreamProvider(Path(self.directory.name))
        self.client = OAuthClientInformationFull(
            client_id="test-client",
            redirect_uris=["https://callback.example.test"],
            token_endpoint_auth_method="none",
        )
        original = await self.provider.harness.issue()
        self.refresh = RefreshToken(
            token=original.refresh,
            client_id="test-client",
            scopes=["openid"],
            resource=ORIGIN + "/server/mcp",
        )

    async def test_concurrent_replays_rotate_once_and_return_the_identical_pair(self) -> None:
        first, second = await asyncio.gather(
            self.provider.exchange_refresh_token(self.client, self.refresh, ["openid"]),
            self.provider.exchange_refresh_token(self.client, self.refresh, ["openid"]),
        )
        self.assertEqual(first, second)
        self.assertEqual(self.provider.exchanges, 1)
        self.assertEqual(self.provider.events, ["refresh_success", "refresh_replay"])

    async def test_replay_survives_a_fresh_auth_process_with_the_same_store_and_key(self) -> None:
        first = await self.provider.exchange_refresh_token(self.client, self.refresh, ["openid"])
        original = self.provider.harness.issuer(self.refresh.resource).verify_token(
            self.refresh.token, expected_token_use="refresh"
        )
        self.assertIsNone(await self.provider.harness.mappings.get(key=original["jti"]))
        restarted = ControlledUpstreamProvider(Path(self.directory.name))
        loaded = await restarted.load_refresh_token(self.client, self.refresh.token)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        second = await restarted.exchange_refresh_token(self.client, loaded, ["openid"])
        self.assertEqual(first, second)
        self.assertEqual(restarted.exchanges, 0)

    async def assert_replay_denied(self, token: RefreshToken) -> None:
        restarted = ControlledUpstreamProvider(Path(self.directory.name))
        self.assertIsNone(await restarted.load_refresh_token(self.client, token.token))
        with self.assertRaises(TokenError):
            await restarted.exchange_refresh_token(self.client, token, ["openid"])
        self.assertEqual(restarted.exchanges, 0)

    async def test_missing_old_mapping_without_an_existing_replay_never_creates_a_grant(
        self,
    ) -> None:
        claims = self.provider.harness.issuer(self.refresh.resource).verify_token(
            self.refresh.token, expected_token_use="refresh"
        )
        await self.provider.harness.mappings.delete(key=claims["jti"])
        await self.assert_replay_denied(self.refresh)
        self.assertIsNone(await self.provider.harness.mappings.get(key=claims["jti"]))

    async def test_cached_pair_requires_a_current_durable_access_family(self) -> None:
        result = await self.provider.exchange_refresh_token(self.client, self.refresh, ["openid"])
        claims = self.provider.harness.issuer(self.refresh.resource).verify_token(
            result.access_token, expected_token_use="access"
        )
        await self.provider.harness.mappings.delete(key=claims["jti"])
        await self.assert_replay_denied(self.refresh)

    async def test_persisted_replay_cannot_substitute_another_client_resource_or_identity(
        self,
    ) -> None:
        result = await self.provider.exchange_refresh_token(self.client, self.refresh, ["openid"])
        harness = self.provider.harness
        other_client = await harness.issue(client_id="other-client", upstream_id="other-client")
        other_resource = await harness.issue(
            resource=ORIGIN + "/web/mcp", upstream_id="other-resource"
        )
        issuer = harness.issuer(self.refresh.resource)
        claims = issuer.verify_token(result.access_token, expected_token_use="access")
        wrong_identity = issuer.issue_access_token(
            client_id="test-client",
            scopes=["openid"],
            jti=claims["jti"],
            expires_in=300,
            upstream_claims={"iss": ISSUER, "sub": "another-human", "identity_provider": "zitadel"},
        )
        key = self.provider._refresh_replay_key("test-client", self.refresh.token)
        for access in (other_client.access, other_resource.access, wrong_identity):
            with self.subTest(access=access[-8:]):
                await self.provider._store_refresh_exchange_replay(
                    key, result.model_copy(update={"access_token": access})
                )
                await self.assert_replay_denied(self.refresh)

    async def test_old_refresh_binding_and_expiry_remain_required_after_mapping_cleanup(
        self,
    ) -> None:
        result = await self.provider.exchange_refresh_token(self.client, self.refresh, ["openid"])
        harness = self.provider.harness
        issuer = harness.issuer(self.refresh.resource)
        claims = issuer.verify_token(self.refresh.token, expected_token_use="refresh")
        for client_id, resource, subject, lifetime, scopes in (
            ("other-client", self.refresh.resource, SUBJECT, 300, ["openid"]),
            ("test-client", ORIGIN + "/web/mcp", SUBJECT, 300, ["openid"]),
            ("test-client", self.refresh.resource, "another-human", 300, ["openid"]),
            ("test-client", self.refresh.resource, SUBJECT, -1, ["openid"]),
            ("test-client", self.refresh.resource, SUBJECT, 300, []),
        ):
            with self.subTest(client=client_id, resource=resource, subject=subject, ttl=lifetime):
                altered = harness.issuer(resource).issue_refresh_token(
                    client_id=client_id,
                    scopes=scopes,
                    jti=claims["jti"],
                    expires_in=lifetime,
                    upstream_claims={"iss": ISSUER, "sub": subject, "identity_provider": "zitadel"},
                )
                key = self.provider._refresh_replay_key("test-client", altered)
                await self.provider._store_refresh_exchange_replay(key, result)
                await self.assert_replay_denied(self.refresh.model_copy(update={"token": altered}))

    async def test_replay_state_is_bound_to_the_client_and_not_just_refresh_text(self) -> None:
        first = await self.provider.exchange_refresh_token(self.client, self.refresh, ["openid"])
        other = self.client.model_copy(update={"client_id": "other-client"})
        self.assertTrue(first.access_token)
        with self.assertRaises(TokenError):
            await self.provider.exchange_refresh_token(other, self.refresh, ["openid"])
        self.assertEqual(self.provider.exchanges, 1)

    async def test_unknown_resource_is_rejected_before_any_upstream_exchange(self) -> None:
        invalid = self.refresh.model_copy(update={"resource": "https://other.example.test/mcp"})
        with self.assertRaises(ValueError):
            await self.provider.exchange_refresh_token(self.client, invalid, ["openid"])
        self.assertEqual(self.provider.exchanges, 0)
