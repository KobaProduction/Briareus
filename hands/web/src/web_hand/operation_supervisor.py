"""Private bounded operation handles; execution authority stays with ProcessLease."""
import asyncio
import time

from node_protocol.control import canonical


class WebOperations:
    @staticmethod
    def operation_reply(record, permit):
        value = {key: record[key] for key in ("operation_id", "tool", "state")}
        if "result" in record:
            value["result"] = record["result"]
        return {"id": str(permit.request_uuid), "result": {
            "content": [{"type": "text", "text": "Web operation: " + record["state"]}],
            "structuredContent": value, "isError": False}}

    async def operation_control(self, name, arguments, permit, identity):
        # Called with the supervisor lock held, BEFORE profile changes or grants.
        expected = {"operation_id", "tool"} if name == "web_operation_poll" else {"operation_id"}
        if set(arguments) != expected or not isinstance(arguments["operation_id"], str):
            raise ValueError("Exact owned Web operation required")
        record = self.operations.get(self.boot+":"+arguments["operation_id"][8:] if arguments["operation_id"].startswith("request:") else arguments["operation_id"])
        if (record is None or record["identity"] != identity or permit.expires_at <= time.time()
            or name == "web_operation_poll" and arguments["tool"] != record["tool"]):
            raise ValueError("Web operation unavailable for this identity and tool")
        if record["state"] == "running":
            if name == "web_operation_cancel":
                await self.stop()
                record["state"] = "cancelled"
                self.prepare_profile(self.profile_key)
            else:
                if not self.child_ready or self.process_lease.identity != identity:
                    raise ValueError("Original prepared Web runtime required")
                await self.process_lease.grant(identity, permit.expires_at)
        return self.operation_reply(record, permit)

    async def operation_start(self, arguments, permit, identity):
        if (set(arguments) != {"tool", "arguments"} or not isinstance(arguments["tool"], str)
            or not isinstance(arguments["arguments"], dict)
            or arguments["tool"] not in {item["name"] for item in self.metadata}
            or arguments["tool"].startswith("web_operation_")
            or len(canonical(arguments)) > 32000 or not self.status_warm
            or permit.expires_at <= time.time()):
            raise ValueError("Bounded original Web tool and prepared browser required")
        operation_id = self.boot + ":" + str(permit.request_uuid)
        if operation_id in self.operations:
            raise ValueError("Web operation start already received; poll its handle")
        while len(self.operations) >= 32:
            self.operations.pop(next(iter(self.operations)))
        await self.process_lease.grant(identity, permit.expires_at)
        record = {"operation_id": operation_id, "identity": identity,
                  "tool": arguments["tool"], "state": "running"}
        self.operations[operation_id] = record
        record["task"] = asyncio.create_task(self.run_operation(record, arguments["arguments"], permit))
        return self.operation_reply(record, permit)

    async def run_operation(self, record, arguments, permit):
        try:
            from hand_runtime.runtime_policy import runtime_policy
            async with asyncio.timeout(runtime_policy().execution_timeout_seconds):
                reply = await self.exchange(record["tool"], arguments, permit, background=True)
            async with self.lock:
                if record["state"] == "running":
                    record["result"] = reply["result"]
                    record["state"] = "failed" if reply["result"].get("isError") else "completed"
        except asyncio.CancelledError:
            raise
        except Exception:
            async with self.lock:
                await self.stop()
                record["state"] = "failed"
                self.prepare_profile(self.profile_key)
