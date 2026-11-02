"""Owner-local compatibility and codec boundary for shared runtime clients."""

from __future__ import annotations

import hashlib as hashlib
import json as json
from datetime import UTC as UTC
from datetime import datetime as datetime
from typing import Literal as Literal
from uuid import UUID as UUID

import jwt as jwt
from cryptography.hazmat.primitives import serialization as serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey as Ed25519PublicKey
from pydantic import BaseModel as BaseModel
from pydantic import ConfigDict as ConfigDict
from pydantic import Field as Field
from pydantic import ValidationError as ValidationError

from project_runtime_client.owner_status import OwnerEffectStatusV2 as OwnerEffectStatusV2
from project_runtime_client.owner_status import (
    SignedOwnerEffectStatusV2 as SignedOwnerEffectStatusV2,
)
from project_runtime_client.owner_status import (
    verify_signed_owner_status_v2 as verify_signed_owner_status_v2,
)

from .a11_owner_wire import A11OwnerCommandDTO as A11OwnerCommandDTO
from .owner_authorization import VerifiedOwnerRecipient as VerifiedOwnerRecipient
from .owner_effects import OwnerEffectCommand as OwnerEffectCommand
from .owner_effects import OwnerEffectUnavailable as OwnerEffectUnavailable
