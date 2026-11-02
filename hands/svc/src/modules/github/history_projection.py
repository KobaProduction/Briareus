from source_control.providers.github.history_projection import git_identity as git_identity
from source_control.providers.github.history_projection import verification as verification

from .history_views import ActorSource as ActorSource
from .history_views import CommitIdentity as CommitIdentity
from .history_views import CommitVerification as CommitVerification
from .history_views import CommitVerificationMaterial as CommitVerificationMaterial
from .history_views import IdentitySource as IdentitySource
from .history_views import VerificationSource as VerificationSource
