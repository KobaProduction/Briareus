"""Compatibility exports for the shared project runtime client implementation."""

from datetime import UTC as UTC
from datetime import datetime as datetime
from typing import Literal as Literal
from typing import Protocol as Protocol
from uuid import UUID as UUID

import jwt as jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey as Ed25519PublicKey
from pydantic import ValidationError as ValidationError

from project_runtime_client.a9_signed_lease import A9PinnedRuntimeKeyPort as A9PinnedRuntimeKeyPort
from project_runtime_client.a9_signed_lease import verify_a9_signed_lease as verify_a9_signed_lease
from project_runtime_client.authorization import ProjectPermit as ProjectPermit
from project_runtime_client.domain.runtime_lease import (
    A9SignedLeaseUntrusted as A9SignedLeaseUntrusted,
)
from project_runtime_client.domain.runtime_lease import (
    RuntimeLeaseExpectation as RuntimeLeaseExpectation,
)
from project_runtime_client.domain.runtime_lease import RuntimeLeaseScope as RuntimeLeaseScope
from project_runtime_client.infrastructure.lease_contracts import (
    RuntimeLeaseReceipt as RuntimeLeaseReceipt,
)
from project_runtime_client.infrastructure.lease_contracts import (
    SignedRuntimeLeaseReceipt as SignedRuntimeLeaseReceipt,
)
from project_runtime_client.infrastructure.runtime_lease import (
    runtime_lease_snapshot as runtime_lease_snapshot,
)
from project_runtime_client.infrastructure.runtime_lease import (
    verify_runtime_lease_token as verify_runtime_lease_token,
)
