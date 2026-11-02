"""Compatibility API for the bounded Web runtime implementation."""

import json as json

from pydantic import BaseModel as BaseModel
from pydantic import StrictBool as StrictBool

from modules.web.domain.operator import MouseInput as MouseInput
from modules.web.domain.operator import OperatorCommand as OperatorCommand
from web_runtime.infrastructure.operator_codec import OperatorWire as OperatorWire
from web_runtime.infrastructure.operator_codec import decode_command as decode_command
