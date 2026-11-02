"""Compatibility exports for the shared provider implementation."""

import http as http
import ssl as ssl
import urllib as urllib

from pydantic import BaseModel as BaseModel
from pydantic import ValidationError as ValidationError

from common.account_contracts import AccountConnectionSummary as AccountConnectionSummary
from common.account_contracts import ResolvedAccount as ResolvedAccount
from common.http_transport import HttpTransportError as HttpTransportError
from common.http_transport import HttpTransportResponse as HttpTransportResponse
from common.http_transport import PooledHttpTransport as PooledHttpTransport
from common.provider_identity import SigNozReply as SigNozReply
from common.provider_identity import SigNozServiceAccount as SigNozServiceAccount
from infrastructure_runtime.providers.signoz.client import SigNozClient as SigNozClient
from infrastructure_runtime.providers.signoz.client import SigNozClientError as SigNozClientError

from .domain.search import TelemetrySearch as TelemetrySearch
from .infrastructure.discovery import FieldKeysQuery as FieldKeysQuery
from .infrastructure.discovery import FieldKeysReply as FieldKeysReply
from .infrastructure.discovery import FieldValuesQuery as FieldValuesQuery
from .infrastructure.discovery import FieldValuesReply as FieldValuesReply
from .infrastructure.query_contracts import QueryRangeRequest as QueryRangeRequest
from .infrastructure.query_contracts import ServicesQuery as ServicesQuery
from .infrastructure.search_query import search_query as search_query
