"""Prompt preview screen — confirm, edit, or skip sending a preset to Amp.

For issues, presents a flow selection (investigate-only vs all-in-one) before
showing the prompt text.
"""

from __future__ import annotations

from rich.markup import escape

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from .modal_base import StyledModalScreen
from textual.widgets import Footer, Input, Static, TextArea


class PromptPreviewScreen(StyledModalScreen[str | None]):
    """Modal showing the rendered prompt preset with send/edit/skip options.

    Dismissed with the (possibly edited) prompt string on send,
    or None on skip.
    """

    BINDINGS = [
        Binding("enter", "send", "Send", priority=True),
        Binding("e", "edit", "Edit"),
        Binding("s", "skip", "Skip"),
        Binding("escape", "skip", "Skip"),
        Binding("q", "skip", "Skip", show=False),
    ]

    def __init__(
        self,
        prompt: str,
        *,
        title: str = "",
    ) -> None:
        super().__init__()
        self._prompt = prompt
        self._title = title or "Prompt Preview"
        self._editing = False

    def compose(self) -> ComposeResult:
        with Vertical(id="prompt-preview-dialog"):
            yield Static(
                f"[bold]{escape(self._title)}[/bold]\n\n"
                "[dim]Prompt to send to Amp:[/dim]",
                id="prompt-header",
            )
            with VerticalScroll(id="prompt-scroll"):
                yield Static(
                    escape(self._prompt),
                    id="prompt-text",
                )
            yield Static(
                "[bold]Enter[/bold] Send  ·  "
                "[bold]e[/bold] Edit  ·  "
                "[bold]s[/bold]/[bold]Esc[/bold] Skip",
                id="prompt-actions",
            )
        yield Footer()

    def action_send(self) -> None:
        if self._editing:
            # Grab edited text from TextArea
            try:
                ta = self.query_one("#prompt-editor", TextArea)
                self._prompt = ta.text
            except Exception:
                pass
        self.dismiss(self._prompt)

    def action_edit(self) -> None:
        if self._editing:
            return
        self._editing = True
        # Replace the Static with a TextArea for editing
        scroll = self.query_one("#prompt-scroll", VerticalScroll)
        text_static = self.query_one("#prompt-text", Static)
        text_static.remove()
        editor = TextArea(self._prompt, id="prompt-editor")
        scroll.mount(editor)
        editor.focus()

    def action_skip(self) -> None:
        self.dismiss(None)


class IssueFlowScreen(StyledModalScreen[str | None]):
    """Modal for selecting the issue workflow before showing the prompt.

    Presents flow options (investigate+plan vs all-in-one), resolves the
    chosen preset, then chains to PromptPreviewScreen.
    """

    BINDINGS = [
        Binding("1", "flow_1", "Investigate + plan"),
        Binding("2", "flow_2", "All-in-one"),
        Binding("escape", "skip", "Skip"),
        Binding("s", "skip", "Skip"),
        Binding("q", "skip", "Skip", show=False),
    ]

    def __init__(
        self,
        repo: str,
        data: dict,
        *,
        title: str = "",
        on_prompt_chosen: object = None,
    ) -> None:
        super().__init__()
        self._repo = repo
        self._data = data
        self._title = title or "Issue Workflow"
        # Callback: fn(prompt_str | None) — called with the final prompt or None
        self._on_prompt_chosen = on_prompt_chosen

    def compose(self) -> ComposeResult:
        with Vertical(id="prompt-preview-dialog"):
            yield Static(
                f"[bold]{escape(self._title)}[/bold]\n\n"
                "[dim]Choose issue workflow:[/dim]\n\n"
                "[bold]1[/bold]  Investigate + plan  [dim](then follow up manually)[/dim]\n"
                "[bold]2[/bold]  All-in-one  [dim](investigate → plan → branch → PR → review)[/dim]\n\n"
                "[bold]s[/bold]/[bold]Esc[/bold]  Skip",
                id="prompt-header",
            )
        yield Footer()

    def _resolve_and_show(self, preset_type: str) -> None:
        from pr_tracker.presets import resolve_preset

        prompt = resolve_preset(preset_type, self._repo, self._data)
        if not prompt:
            self.dismiss(None)
            return

        # Dismiss this screen, then show the prompt preview
        self.dismiss(None)

        def _on_preview_dismiss(result: str | None) -> None:
            if self._on_prompt_chosen:
                self._on_prompt_chosen(result)

        self.app.push_screen(
            PromptPreviewScreen(prompt, title=self._title),
            callback=_on_preview_dismiss,
        )

    def action_flow_1(self) -> None:
        self._resolve_and_show("issue")

    def action_flow_2(self) -> None:
        self._resolve_and_show("issue_full")

    def action_skip(self) -> None:
        self.dismiss(None)
        if self._on_prompt_chosen:
            self._on_prompt_chosen(None)


class FollowUpScreen(StyledModalScreen[str | None]):
    """Modal for selecting a follow-up prompt to send to the station's amp window."""

    BINDINGS = [
        Binding("1", "pick_1", "Work + PR"),
        Binding("2", "pick_2", "Continue"),
        Binding("3", "pick_3", "Review"),
        Binding("escape", "skip", "Skip"),
        Binding("s", "skip", "Skip"),
        Binding("q", "skip", "Skip", show=False),
    ]

    def __init__(self, *, title: str = "") -> None:
        super().__init__()
        self._title = title or "Follow-up Prompt"

    def compose(self) -> ComposeResult:
        from pr_tracker.presets import FOLLOWUP_PROMPTS
        lines = [
            f"[bold]{escape(self._title)}[/bold]\n\n"
            "[dim]Send follow-up to Amp:[/dim]\n"
        ]
        for fp in FOLLOWUP_PROMPTS:
            if len(fp['prompt']) > 60:
                lines.append(f"\n[bold]{fp['key']}[/bold]  {fp['label']}  [dim]{fp['prompt'][:60]}...[/dim]")
            else:
                lines.append(f"\n[bold]{fp['key']}[/bold]  {fp['label']}  [dim]{fp['prompt']}[/dim]")
        lines.append("\n\n[bold]s[/bold]/[bold]Esc[/bold]  Cancel")
        with Vertical(id="prompt-preview-dialog"):
            yield Static("".join(lines), id="prompt-header")
        yield Footer()

    def _pick(self, index: int) -> None:
        from pr_tracker.presets import FOLLOWUP_PROMPTS
        if index < len(FOLLOWUP_PROMPTS):
            self.dismiss(FOLLOWUP_PROMPTS[index]["prompt"])
        else:
            self.dismiss(None)

    def action_pick_1(self) -> None:
        self._pick(0)

    def action_pick_2(self) -> None:
        self._pick(1)

    def action_pick_3(self) -> None:
        self._pick(2)

    def action_skip(self) -> None:
        self.dismiss(None)


class StationNameScreen(StyledModalScreen[str | None]):
    """Modal for entering a name/purpose for a new station."""

    BINDINGS = [
        Binding("escape", "skip", "Skip"),
        Binding("q", "skip", "Skip", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()

    def compose(self) -> ComposeResult:
        with Vertical(id="prompt-preview-dialog"):
            yield Static(
                "[bold]New Station[/bold]\n\n"
                "[dim]Enter a name or purpose (optional):[/dim]",
                id="prompt-header",
            )
            yield Input(placeholder="e.g. fix auth bug, refactor tests...", id="station-name-input")
            yield Static(
                "[bold]Enter[/bold] Create  ·  "
                "[bold]Esc[/bold] Skip (no name)",
                id="prompt-actions",
            )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#station-name-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        name = event.value.strip()
        self.dismiss(name if name else None)

    def action_skip(self) -> None:
        self.dismiss(None)
