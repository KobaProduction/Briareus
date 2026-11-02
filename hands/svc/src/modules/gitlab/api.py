"""Compatibility exports for the shared GitLab technical implementation."""

import http as http
import ssl as ssl
import urllib as urllib
from pathlib import Path as Path

from pydantic import BaseModel as BaseModel
from pydantic import ValidationError as ValidationError

from service_runtime.http_transport import HttpTransportError as HttpTransportError
from service_runtime.http_transport import HttpTransportResponse as HttpTransportResponse
from service_runtime.http_transport import PooledHttpTransport as PooledHttpTransport
from source_control.providers.gitlab.api import GitLabApiClient as GitLabApiClient

from .errors import GitLabError as GitLabError
from .models import GitLabProfile as GitLabProfile
from .transport_views import GitLabAcknowledgement as GitLabAcknowledgement
from .transport_views import GitLabModelResponse as GitLabModelResponse
from .transport_views import GitLabPagination as GitLabPagination
from .transport_views import GitLabRequestHeaders as GitLabRequestHeaders
