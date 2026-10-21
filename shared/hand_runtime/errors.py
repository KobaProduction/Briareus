"""Safe public execution states; no provider diagnostics or caller data."""


class NodePreparing(ValueError):
    """A clean isolated runtime is preparing; only read-only probes may retry."""
