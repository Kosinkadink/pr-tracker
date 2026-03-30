"""Tag management screen — add/remove tags on a PR."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Input, Static


class TagScreen(ModalScreen[list[str] | None]):
    """Modal for adding/removing tags on a PR."""

    BINDINGS = [
        Binding("q", "close", "Back"),
        Binding("escape", "close", "Back"),
    ]

    def __init__(self, pr: dict) -> None:
        super().__init__()
        self._pr = pr
        self._repo = pr.get("repo", "")
        self._number = pr["number"]

    def compose(self) -> ComposeResult:
        tags = self._pr.get("tags", [])
        tag_str = ", ".join(tags) if tags else "[dim]none[/dim]"
        with Vertical(id="tag-dialog"):
            yield Static(
                f"[bold]Tags for #{self._number}[/bold]\n\n"
                f"Current: {tag_str}\n\n"
                f"Type a tag name and press Enter to add.\n"
                f"Prefix with [bold]-[/bold] to remove (e.g. [bold]-review[/bold]).",
                id="tag-text",
            )
            yield Input(placeholder="Tag name (or -tag to remove)", id="tag-input")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#tag-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "tag-input":
            return
        value = event.value.strip()
        if not value:
            return

        from pr_tracker.data import add_tag, get_tags, remove_tag

        if value.startswith("-"):
            tag = value[1:].strip()
            if tag:
                remove_tag(self._repo, self._number, tag)
                self.notify(f"Removed tag: {tag}")
        else:
            add_tag(self._repo, self._number, value)
            self.notify(f"Added tag: {value}")

        event.input.value = ""
        # Update display
        tags = get_tags(self._repo, self._number)
        self._pr["tags"] = tags
        tag_str = ", ".join(tags) if tags else "[dim]none[/dim]"
        self.query_one("#tag-text", Static).update(
            f"[bold]Tags for #{self._number}[/bold]\n\n"
            f"Current: {tag_str}\n\n"
            f"Type a tag name and press Enter to add.\n"
            f"Prefix with [bold]-[/bold] to remove (e.g. [bold]-review[/bold])."
        )

    def action_close(self) -> None:
        from pr_tracker.data import get_tags
        self.dismiss(get_tags(self._repo, self._number))
