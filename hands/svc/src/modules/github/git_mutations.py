from source_control.providers.github.git_mutations import (
    GitHubGitMutationClient as _SharedGitHubGitMutationClient,
)

from .application.mutations import AtomicChanges as AtomicChanges
from .application.mutations import AtomicResult as AtomicResult
from .application.mutations import CopyFiles as CopyFiles
from .application.mutations import CopyResult as CopyResult
from .domain.mutations import AtomicInput as AtomicInput
from .domain.mutations import CopyItem as CopyItem
from .domain.mutations import MutationError as MutationError
from .git_transaction import GitHubGitDataTransactionClient
from .github_agent import GitHubAgentError as GitHubAgentError
from .infrastructure.mutations import GitMutations as GitMutations
from .models import AtomicChange as AtomicChange
from .models import CopySpec as CopySpec


class GitHubGitMutationClient(_SharedGitHubGitMutationClient, GitHubGitDataTransactionClient):
    pass
