"""HTTP body encoding policy for concrete GitHub request models."""

from collections.abc import Callable
from functools import partial
from operator import is_
from typing import ClassVar

from pydantic import BaseModel


class GitHubRequestBody(BaseModel):
    omit_null_fields: ClassVar[bool] = True

    def encode_http_body(self) -> bytes:
        return self.model_dump_json(exclude_none=self.omit_null_fields, by_alias=True).encode(
            "utf-8"
        )


omit_unreported: Callable[[object], bool] = partial(is_, None)
