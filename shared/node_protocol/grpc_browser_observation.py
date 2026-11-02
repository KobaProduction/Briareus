"""Typed protobuf adaptation of the passive browser observation records."""

from uuid import UUID

from . import node_pb2 as pb
from .browser_observation import (
    BrowserObservationSelector,
    BrowserObservationWire,
    BrowserObservedFrameWire,
)


def encode_selector(value: BrowserObservationSelector) -> pb.BrowserObservationSelector:
    return pb.BrowserObservationSelector(
        project_uuid=str(value.project_uuid),
        placement_uuid=str(value.placement_uuid),
        fingerprint=value.fingerprint,
        actor_uuid=str(value.actor_uuid),
        agent_session_uuid=str(value.agent_session_uuid),
        grant_revision=value.grant_revision,
    )


def decode_selector(value: pb.BrowserObservationSelector) -> BrowserObservationSelector:
    return BrowserObservationSelector(
        project_uuid=UUID(value.project_uuid),
        placement_uuid=UUID(value.placement_uuid),
        fingerprint=value.fingerprint,
        actor_uuid=UUID(value.actor_uuid),
        agent_session_uuid=UUID(value.agent_session_uuid),
        grant_revision=value.grant_revision,
    )


def encode_observation(value: BrowserObservationWire) -> pb.BrowserObservation:
    result = pb.BrowserObservation(target=encode_selector(value.target))
    frame = value.frame
    if frame is not None:
        result.frame.CopyFrom(
            pb.BrowserObservedFrame(
                source_request_uuid=str(frame.source_request_uuid),
                captured_at=frame.captured_at,
                page_id=frame.page_id,
                url=frame.url,
                title=frame.title,
                png_base64=frame.png_base64,
            )
        )
    return result


def decode_observation(value: pb.BrowserObservation) -> BrowserObservationWire:
    frame = value.frame
    return BrowserObservationWire(
        target=decode_selector(value.target),
        frame=BrowserObservedFrameWire(
            source_request_uuid=UUID(frame.source_request_uuid),
            captured_at=frame.captured_at,
            page_id=frame.page_id,
            url=frame.url,
            title=frame.title,
            png_base64=frame.png_base64,
        )
        if value.HasField("frame")
        else None,
    )
