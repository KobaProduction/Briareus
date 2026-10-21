"""Original provider calls in an unprivileged identity-bound process."""
import asyncio
from hand_runtime.provider_child import run_provider_child
from .dispatch import SourceToolDispatch
from .invocation_accounts import InvocationAccounts


if __name__ == "__main__":
    asyncio.run(run_provider_child(SourceToolDispatch, InvocationAccounts, "SVC_OPERATION_FAILED"))
