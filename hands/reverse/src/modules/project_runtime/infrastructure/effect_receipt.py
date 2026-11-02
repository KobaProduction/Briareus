"""Owner-local compatibility and codec boundary for shared runtime clients."""

from __future__ import annotations

import hashlib as hashlib
import json as json
from dataclasses import dataclass as dataclass
from datetime import UTC as UTC
from datetime import datetime as datetime
from typing import TYPE_CHECKING as TYPE_CHECKING
from typing import Literal as Literal

import jwt as jwt
from cryptography.hazmat.primitives import serialization as serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey as Ed25519PublicKey
from pydantic import UUID4 as UUID4
from pydantic import BaseModel as BaseModel
from pydantic import ConfigDict as ConfigDict
from pydantic import StrictInt as StrictInt

from modules.project_runtime.domain.effect_receipt import (
    EffectReceiptBinding as EffectReceiptBinding,
)
from modules.project_runtime.domain.effect_receipt import (
    OwnerEffectUnavailable as OwnerEffectUnavailable,
)
from modules.project_runtime.domain.effect_receipt import ReceiptObservation as ReceiptObservation
from modules.project_runtime.domain.effect_receipt import RevocationFence as RevocationFence
from modules.project_runtime.owner_authorization import (
    VerifiedOwnerRecipient as VerifiedOwnerRecipient,
)
from project_runtime_client.infrastructure.effect_receipt import ReceiptClaims as ReceiptClaims
from project_runtime_client.infrastructure.effect_receipt import (
    VerifiedEffectAttestation as VerifiedEffectAttestation,
)
from project_runtime_client.infrastructure.effect_receipt import _fence as _fence
from project_runtime_client.infrastructure.effect_receipt import command_binding as command_binding
from project_runtime_client.infrastructure.effect_receipt import (
    receipt_observation as receipt_observation,
)
from project_runtime_client.infrastructure.effect_receipt import (
    verify_attestation as verify_attestation,
)

from .effect_contracts import OwnerEffectReceipt as OwnerEffectReceipt
from .effect_contracts import OwnerFenceDTO as OwnerFenceDTO
from .effect_contracts import SignedOwnerEffectReceipt as SignedOwnerEffectReceipt
