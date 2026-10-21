"""Typed private dispatch of the original tools, without a second MCP server."""
from inspect import isawaitable

from pydantic import ConfigDict, validate_call

from .tools import register_terminal_tools


class TerminalToolDispatch:
    def __init__(self, manager):
        self.tools = {}
        register_terminal_tools(self, manager, include_metadata=False)

    def tool(self, **metadata):
        def register(function):
            if function.__name__ in self.tools:
                raise ValueError("Duplicate terminal tool")
            self.tools[function.__name__] = validate_call(
                config=ConfigDict(strict=True), validate_return=True)(function)
            return function
        return register

    async def call(self, name, arguments):
        result = self.tools[name](**arguments)
        return await result if isawaitable(result) else result
