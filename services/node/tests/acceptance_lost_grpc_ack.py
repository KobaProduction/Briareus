"""Ephemeral local acceptance proxy: drop one accepted Apply acknowledgement.

Run only on the private local control network. It owns no signing keys, Docker
socket or credentials. Requests and replies are forwarded unchanged; the real
Node still authenticates every command. Do not add this fixture to production.
"""
import argparse
import asyncio
import json
import signal
from uuid import UUID

import grpc
from node_protocol import node_pb2_grpc as rpc


class DropAcceptedApply(rpc.NodeControlServicer):
    def __init__(self, upstream, node, operation):
        self.upstream,self.node,self.operation=upstream,str(node),str(operation)
        self.dropped=False

    async def Apply(self,request,context):
        # Never change/re-sign a command, synthesize a receipt, or retry it.
        reply=await self.upstream.Apply(request,timeout=5)
        if (not self.dropped and request.command.node_uuid==self.node
            and request.command.operation_uuid==self.operation
            and reply.proof.operation_uuid==self.operation and reply.proof.status_code in {200,202}):
            self.dropped=True
            print(json.dumps({"accepted_ack_dropped":True,"operation_uuid":self.operation,
                              "sequence":request.command.sequence}),flush=True)
            await context.abort(grpc.StatusCode.UNAVAILABLE,"Local acceptance fixture discarded accepted Apply reply")
        return reply


async def main(node,operation):
    stop=asyncio.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig,stop.set)
    async with grpc.aio.insecure_channel("briareus-node:8081",options=[("grpc.enable_retries",0)]) as channel:
        server=grpc.aio.server(options=[("grpc.max_receive_message_length",65536),
                                        ("grpc.max_send_message_length",1048576)])
        rpc.add_NodeControlServicer_to_server(DropAcceptedApply(rpc.NodeControlStub(channel),node,operation),server)
        if not server.add_insecure_port("0.0.0.0:18081"):
            raise RuntimeError("Acceptance proxy bind failed")
        await server.start()
        print(json.dumps({"acceptance_proxy_ready":True}),flush=True)
        try:
            async with asyncio.timeout(300):await stop.wait()
        finally:await server.stop(1)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node',type=UUID,required=True)
    parser.add_argument('--operation',type=UUID,required=True)
    args=parser.parse_args()
    asyncio.run(main(args.node,args.operation))
