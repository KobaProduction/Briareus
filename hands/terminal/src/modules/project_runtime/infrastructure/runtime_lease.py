"""Compatibility exports for the shared project runtime client implementation."""

import hashlib as hashlib
import json as json
from dataclasses import dataclass as dataclass
from uuid import UUID as UUID

import jwt as jwt
from cryptography.hazmat.primitives import serialization as serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey as Ed25519PublicKey
from pydantic import UUID4 as UUID4
from pydantic import BaseModel as BaseModel
from pydantic import ConfigDict as ConfigDict
from pydantic import StrictInt as StrictInt
from pydantic import ValidationError as ValidationError
from pydantic import field_validator as field_validator

from project_runtime_client.domain.runtime_lease import (
    A9SignedLeaseUntrusted as A9SignedLeaseUntrusted,
)
from project_runtime_client.domain.runtime_lease import RuntimeLeaseClaims as RuntimeLeaseClaims
from project_runtime_client.domain.runtime_lease import (
    RuntimeLeaseExpectation as RuntimeLeaseExpectation,
)
from project_runtime_client.domain.runtime_lease import RuntimeLeaseLifetime as RuntimeLeaseLifetime
from project_runtime_client.domain.runtime_lease import RuntimeLeaseScope as RuntimeLeaseScope
from project_runtime_client.domain.runtime_lease import RuntimeLeaseSnapshot as RuntimeLeaseSnapshot
from project_runtime_client.infrastructure.lease_contracts import (
    RuntimeLeaseReceipt as RuntimeLeaseReceipt,
)
from project_runtime_client.infrastructure.lease_contracts import (
    SignedRuntimeLeaseReceipt as SignedRuntimeLeaseReceipt,
)
from project_runtime_client.infrastructure.runtime_lease import (
    RuntimeLeaseClaimPayload as RuntimeLeaseClaimPayload,
)
from project_runtime_client.infrastructure.runtime_lease import (
    VerifiedRuntimeLease as VerifiedRuntimeLease,
)
from project_runtime_client.infrastructure.runtime_lease import (
    runtime_lease_snapshot as runtime_lease_snapshot,
)
from project_runtime_client.infrastructure.runtime_lease import (
    verify_runtime_lease_token as verify_runtime_lease_token,
)
