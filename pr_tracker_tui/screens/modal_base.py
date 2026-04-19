"""Base modal screen with default centered dark-overlay styling.

All modal screens should inherit from ``StyledModalScreen`` instead of
``ModalScreen`` directly.  This ensures consistent appearance (centered
dialog, dark translucent backdrop) without requiring per-screen CSS
entries in ``app.tcss``.
"""

from __future__ import annotations

from textual.screen import ModalScreen, ScreenResultType


class StyledModalScreen(ModalScreen[ScreenResultType]):
    """ModalScreen with built-in centering and dark overlay.

    Subclasses should wrap their content in a ``Vertical`` container.
    The CSS styles any direct ``Vertical`` child as a centered dialog
    box with border and surface background.

    Uses ``CSS`` (not ``DEFAULT_CSS``) so it overrides ModalScreen's
    built-in ``background: $background 60%`` which produces a grey
    backdrop.
    """

    SCOPED_CSS = False
    CSS = """
    StyledModalScreen {
        align: center middle;
        background: rgba(0, 0, 0, 0.6);
    }

    StyledModalScreen > Vertical {
        width: 60;
        height: auto;
        max-height: 20;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    """
