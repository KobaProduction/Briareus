"""Typed asynchronous binding for the existing NodeControl protobuf service."""

from typing import Literal

import grpc.aio

from . import node_pb2 as pb


def _unary(
    channel: grpc.aio.Channel,
    method: Literal["Inventory", "Configure", "Apply", "Operation", "ObserveBrowser"],
) -> grpc.aio.UnaryUnaryMultiCallable[pb.SignedCommand, pb.SignedReply]:
    return channel.unary_unary(
        "/briareus.node.NodeControl/" + method,
        request_serializer=pb.SignedCommand.SerializeToString,
        response_deserializer=pb.SignedReply.FromString,
    )


class NodeControlClient:
    def __init__(self, channel: grpc.aio.Channel) -> None:
        self.Inventory = _unary(channel, "Inventory")
        self.Configure = _unary(channel, "Configure")
        self.Apply = _unary(channel, "Apply")
        self.Operation = _unary(channel, "Operation")
        self.ObserveBrowser = _unary(channel, "ObserveBrowser")
        self.Watch: grpc.aio.UnaryStreamMultiCallable[pb.SignedCommand, pb.SignedEvent] = (
            channel.unary_stream(
                "/briareus.node.NodeControl/Watch",
                request_serializer=pb.SignedCommand.SerializeToString,
                response_deserializer=pb.SignedEvent.FromString,
            )
        )
