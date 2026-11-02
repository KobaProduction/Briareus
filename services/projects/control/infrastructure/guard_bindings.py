"""Platform-only constructor guards; each source layout supplies its own actor contract."""

from common.owner_contracts import TrustedOwnerServicePeerPort
from common.owner_effect_authorization import OwnerEffectDecisionSigner
from common.owner_proof_signing import SourceOwnerSigner
from common.platform_db import PlatformDatabase


class _ControlEffectBinding[ActorSource]:
    def __init__(
        self,
        database: PlatformDatabase,
        signer: OwnerEffectDecisionSigner,
        peers: TrustedOwnerServicePeerPort,
        actors: ActorSource,
    ) -> None:
        trusted_peer = peers is not None
        if (
            database.engine.url.database != "briareus_platform"
            or signer.owner != "platform"
            or not trusted_peer
            or actors is None
        ):
            raise RuntimeError("Control effect decision requires current Control and C2")
        self.database = database
        self.signer = signer
        self.peers = peers
        self.actors = actors


class _ControlProofBinding[ActorSource]:
    def __init__(
        self,
        database: PlatformDatabase,
        signer: SourceOwnerSigner,
        peers: TrustedOwnerServicePeerPort,
        actor_source: ActorSource,
    ) -> None:
        trusted_peer = peers is not None
        if (
            database.engine.url.database != "briareus_platform"
            or not trusted_peer
            or actor_source is None
        ):
            raise RuntimeError("Control proof must use own DB and trusted Identity/peer sources")
        self.db = database
        self.signer = signer
        self.peers = peers
        self.actors = actor_source


class _TeamProofBinding[ActorSource]:
    def __init__(
        self,
        database: PlatformDatabase,
        signer: SourceOwnerSigner,
        peers: TrustedOwnerServicePeerPort,
        actors: ActorSource,
    ) -> None:
        trusted_peer = peers is not None
        if (
            database.engine.url.database != "briareus_platform"
            or not trusted_peer
            or actors is None
        ):
            raise RuntimeError("Team proof issuer requires Control owner and signed Identity actor")
        self.db = database
        self.signer = signer
        self.peers = peers
        self.actors = actors
