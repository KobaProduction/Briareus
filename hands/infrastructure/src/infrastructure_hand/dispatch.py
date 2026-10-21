"""Typed private dispatch of original provider callables; no second MCP server."""
from inspect import isawaitable
from pydantic import ConfigDict, validate_call
from .source_tools import register_source_tools


class SourceToolDispatch:
    def __init__(self, accounts, policies=None):
        self.tools = {}
        self.annotations = {}
        self.contexts = register_source_tools(self, accounts, policies)

    def tool(self, **metadata):
        def register(function):
            if function.__name__ in self.tools:
                raise ValueError("Duplicate provider tool")
            self.tools[function.__name__] = validate_call(
                config=ConfigDict(strict=True), validate_return=True)(function)
            self.annotations[function.__name__] = metadata.get("annotations")
            return function
        return register

    def configure(self, policies):
        if not isinstance(policies, dict):
            raise ValueError("Current provider policies required")

    async def call(self, name, arguments):
        if name not in self.tools:
            raise ValueError("Unregistered provider tool")
        result = self.tools[name](**arguments)
        return await result if isawaitable(result) else result

    def clear(self):
        for context in self.contexts:
            clear = getattr(context, "clear", None)
            if clear is not None:
                clear()
        self.contexts = ()
        self.tools.clear()
        self.annotations.clear()
