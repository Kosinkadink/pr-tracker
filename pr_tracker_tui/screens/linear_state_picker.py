"""LinearStatePickerScreen — small modal to move a Linear issue to a new state.

Triggered by ``M`` on PR list / branch list / Linear detail screen when the
selected row has a ``linear_identifier``.  Calls
:func:`pr_tracker.linear_ops.move_issue` on a worker thread and dismisses
with a pill dict on success::

    {
        "linear_identifier": "DESK2-42",
        "linear_state_name": "In Review",
        "linear_state_type": "started",
        "linear_state_color": "",
    }

Dismissed with ``None`` on cancel/error.
"""

from __future__ import annotations

from rich.markup import escape

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Static

from .modal_base import StyledModalScreen


# (key, alias passed to move_issue, label shown in the picker)
_STATE_OPTIONS: list[tuple[str, str, str]] = [
    ("1", "todo",        "Todo"),
    ("2", "in-progress", "In Progress"),
    ("3", "in-review",   "In Review"),
    ("4", "done",        "Done"),
    ("5", "cancelled",   "Cancelled"),
    ("6", "backlog",     "Backlog"),
]


class LinearStatePickerScreen(StyledModalScreen[dict | None]):
    """Modal for picking a new state for a Linear issue."""

    SCOPED_CSS = False
    CSS = StyledModalScreen.CSS + """
    LinearStatePickerScreen > Vertical {
        width: 50;
        max-height: 16;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "cancel", "Cancel", show=False),
        *[Binding(key, f"pick({idx})", label) for idx, (key, _alias, label) in enumerate(_STATE_OPTIONS)],
    ]

    def __init__(self, identifier: str, *, current_state: str = "") -> None:
        super().__init__()
        self._identifier = identifier
        self._current_state = current_state
        self._submitting = False

    def compose(self) -> ComposeResult:
        lines = [
            f"[bold]Move {escape(self._identifier)}[/bold]",
        ]
        if self._current_state:
            lines.append(f"  [dim]current: {escape(self._current_state)}[/dim]")
        lines.append("")
        for key, _alias, label in _STATE_OPTIONS:
            lines.append(f"  [bold]{key}[/bold]  {label}")
        lines.append("")
        lines.append("  [dim]Esc to cancel[/dim]")
        with Vertical(id="linear-state-picker-dialog"):
            yield Static("\n".join(lines), id="linear-state-picker-text")
        yield Footer()

    # ------------------------------------------------------------------
    # Pick actions (one per state option, dispatched by the binding key)
    # ------------------------------------------------------------------

    def action_pick(self, index: int) -> None:
        self._pick(index)

    def _pick(self, index: int) -> None:
        if self._submitting:
            return
        if index < 0 or index >= len(_STATE_OPTIONS):
            return
        _key, alias, label = _STATE_OPTIONS[index]
        self._submitting = True
        self.notify(f"Moving {self._identifier} → {label}…")
        identifier = self._identifier

        def _work() -> None:
            self._do_move(identifier, alias)

        self.run_worker(_work, thread=True, exclusive=True, group="linear-move")

    def _do_move(self, identifier: str, alias: str) -> None:
        from pr_tracker.linear_ops import move_issue

        try:
            issue = move_issue(identifier, alias)
        except Exception as e:
            self.app.call_from_thread(self._on_error, str(e))
            return

        st = issue.get("state") or {}
        pill = {
            "linear_identifier": identifier,
            "linear_state_name": st.get("name", "") if isinstance(st, dict) else "",
            "linear_state_type": st.get("type", "") if isinstance(st, dict) else "",
            "linear_state_color": st.get("color", "") if isinstance(st, dict) else "",
        }
        self.app.call_from_thread(self._on_success, pill)

    def _on_success(self, pill: dict) -> None:
        self._submitting = False
        self.notify(
            f"Moved {pill.get('linear_identifier', '?')} → "
            f"{pill.get('linear_state_name', '?')}",
            timeout=4,
        )
        self.dismiss(pill)

    def _on_error(self, msg: str) -> None:
        self._submitting = False
        self.notify(f"Move failed: {msg}", severity="error", timeout=8)

    def action_cancel(self) -> None:
        if self._submitting:
            self.notify("Already moving — please wait")
            return
        self.dismiss(None)
