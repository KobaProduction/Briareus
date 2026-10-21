"""Compatibility entrypoint; shared public-only egress has one implementation."""
import asyncio

from gateway_runtime.egress_proxy import main

if __name__ == "__main__":
    asyncio.run(main())
