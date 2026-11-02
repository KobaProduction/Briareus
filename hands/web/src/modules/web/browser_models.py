"""Compatibility API for the bounded Web runtime implementation."""

from pydantic import Field as Field

from common.browser_contracts import BrowserBrand as BrowserBrand
from common.browser_contracts import BrowserObservation as BrowserObservation
from common.browser_contracts import BrowserStatus as BrowserStatus
from common.browser_contracts import Capabilities as Capabilities
from common.browser_contracts import DebugTarget as DebugTarget
from common.browser_contracts import Dimensions as Dimensions
from common.browser_contracts import EmptyObservation as EmptyObservation
from common.browser_contracts import GraphicsObservation as GraphicsObservation
from common.browser_contracts import PageSummary as PageSummary
from common.browser_contracts import SnapshotElement as SnapshotElement
from common.models import StrictModel as StrictModel
from runtime_peer.browser_receipts import BrowserDiagnostics as BrowserDiagnostics
from runtime_peer.browser_receipts import BrowserPreview as BrowserPreview
from runtime_peer.browser_receipts import ClosedPage as ClosedPage
from runtime_peer.browser_receipts import LocalBrowserPages as LocalBrowserPages
from web_runtime.browser_models import AgentAccessStatus as AgentAccessStatus
from web_runtime.browser_models import ChromiumDeveloperObservation as ChromiumDeveloperObservation
from web_runtime.browser_models import CleanBrowserResult as CleanBrowserResult
from web_runtime.browser_models import DeveloperAccessReceipt as DeveloperAccessReceipt
from web_runtime.browser_models import DeveloperExtensionReceipt as DeveloperExtensionReceipt
from web_runtime.browser_models import DeveloperExtensionResult as DeveloperExtensionResult
from web_runtime.browser_models import DeveloperSyncResult as DeveloperSyncResult
from web_runtime.browser_models import OperatorLease as OperatorLease
from web_runtime.browser_models import OperatorState as OperatorState

BrowserPages = LocalBrowserPages
