"""Bounded recursive traversal and source/destination containment policy."""

from dataclasses import dataclass


@dataclass
class TreeTraversalBudget:
    visited: int = 0

    def visit(self, depth: int) -> None:
        self.visited += 1
        if self.visited > 10_000:
            raise ValueError("Recursive Files operation exceeds entry budget")
        if depth > 64:
            raise ValueError("Recursive Files depth exceeded")


def require_separate_destination(source: str, destination: str) -> None:
    if destination == source or destination.startswith(source + "/"):
        raise ValueError("Destination cannot be inside source")
