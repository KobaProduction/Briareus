"""Signal isolation for multiple loopback ASGI servers in one test process.

The test runner owns process signals. Uvicorn's default signal capture lets
sse-starlette's process-wide shutdown watcher mistake a stopped sibling
fixture for shutdown of every SSE server. Each fixture shuts down explicitly
through its own Server.should_exit and awaited serve task.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import uvicorn


class FixtureServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield
