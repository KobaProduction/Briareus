"""Compatibility API for the bounded Web runtime implementation."""

import hashlib as hashlib
import math as math
from dataclasses import dataclass as dataclass
from dataclasses import field as field
from typing import Protocol as Protocol
from uuid import UUID as UUID

from web_runtime.domain.public_download import DownloadDigest as DownloadDigest
from web_runtime.domain.public_download import DownloadProgress as DownloadProgress
from web_runtime.domain.public_download import DownloadRejected as DownloadRejected
from web_runtime.domain.public_download import PublicDownload as PublicDownload
from web_runtime.domain.public_download import _digest_valid as _digest_valid
from web_runtime.domain.public_download import _duration_valid as _duration_valid
from web_runtime.domain.public_download import _size_valid as _size_valid
