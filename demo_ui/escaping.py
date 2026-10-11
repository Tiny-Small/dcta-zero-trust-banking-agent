"""HTML escaping for untrusted UI values.

All user-provided or externally-sourced strings that appear in Gradio HTML
rendering must be escaped. This prevents:
  - XSS (script injection via transcript/memo/name fields)
  - Visual spoofing (bold/green text that looks like trusted status)
  - Markdown link/image injection

Backend artifact hashes are 64-char hex strings and are safe unescaped.
Only human-readable strings need escaping.
"""

from __future__ import annotations

from html import escape as _html_escape


def esc(value: str) -> str:
    """Escape a string for safe HTML display.

    Uses html.escape with quote=True so both single and double quotes
    are escaped. This prevents attribute injection as well as tag injection.
    """
    if value is None:
        return ""
    return _html_escape(str(value), quote=True)
