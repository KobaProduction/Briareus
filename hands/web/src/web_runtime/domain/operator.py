"""Operator selection is the authority for page input within one owner session."""

from dataclasses import dataclass


class OperatorViolation(ValueError):
    pass


@dataclass(frozen=True)
class OperatorOwner:
    token: str
    selected_page_id: str


@dataclass(frozen=True)
class MouseInput:
    event_type: str
    x: float
    y: float
    button: str
    click_count: int
    delta_x: float
    delta_y: float


@dataclass(frozen=True)
class OperatorCommand:
    action: str
    page_id: str = ""
    value: str = ""
    allowed: bool | None = None
    mouse: MouseInput | None = None

    def access(self) -> bool:
        if self.allowed is None:
            raise OperatorViolation("allowed must be a boolean")
        return self.allowed


@dataclass
class OperatorSelection:
    page_id: str = ""

    def require_selected(self) -> str:
        if not self.page_id:
            raise OperatorViolation("no browser page selected")
        return self.page_id

    def input_target(self, requested: str) -> str:
        target = requested or self.page_id
        if not target or target != self.page_id:
            raise OperatorViolation("browser input target is not active for this operator")
        return target
