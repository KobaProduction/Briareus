"""The Java heap leaves the fixed native/bridge reserve inside the placement limit."""


def ghidra_heap_mb(memory_bytes: int) -> int:
    return min(1024, max(256, (memory_bytes // 1024**2) - 768))
