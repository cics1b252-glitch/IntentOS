"""Intent Design System (IDS) — The visual identity of Intent OS.

A permanent, evolving visual identity system.
Like a person who changes clothes but is always recognized.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class IDSToken:
    """A design token."""
    name: str
    value: str
    category: str  # color, typography, spacing, animation


class IntentDesignSystem:
    """The official design system of Intent OS.

    Permanent identity. Evolves without breaking recognition.
    """

    def __init__(self):
        self.tokens = self._init_tokens()
        self.components = self._init_components()
        self.version = "1.0.0"

    def _init_tokens(self) -> dict[str, IDSToken]:
        return {
            # Colors — calm intelligence
            "color-primary": IDSToken("color-primary", "#6366f1", "color"),        # Indigo
            "color-secondary": IDSToken("color-secondary", "#22c55e", "color"),    # Green
            "color-accent": IDSToken("color-accent", "#eab308", "color"),          # Yellow
            "color-bg": IDSToken("color-bg", "#0f0f13", "color"),
            "color-surface": IDSToken("color-surface", "#1a1a24", "color"),
            "color-text": IDSToken("color-text", "#e8e8f0", "color"),
            "color-text-dim": IDSToken("color-text-dim", "#8888aa", "color"),
            "color-border": IDSToken("color-border", "#2a2a3a", "color"),

            # Typography — Sora for headings, system for body
            "font-heading": IDSToken("font-heading", "Sora, system-ui, sans-serif", "typography"),
            "font-body": IDSToken("font-body", "Segoe UI, system-ui, sans-serif", "typography"),
            "font-mono": IDSToken("font-mono", "JetBrains Mono, monospace", "typography"),

            # Spacing — 4px base
            "space-xs": IDSToken("space-xs", "4px", "spacing"),
            "space-sm": IDSToken("space-sm", "8px", "spacing"),
            "space-md": IDSToken("space-md", "16px", "spacing"),
            "space-lg": IDSToken("space-lg", "24px", "spacing"),
            "space-xl": IDSToken("space-xl", "32px", "spacing"),

            # Border radius
            "radius-sm": IDSToken("radius-sm", "6px", "radius"),
            "radius-md": IDSToken("radius-md", "12px", "radius"),
            "radius-lg": IDSToken("radius-lg", "16px", "radius"),

            # Animation
            "animation-fast": IDSToken("animation-fast", "0.15s ease", "animation"),
            "animation-normal": IDSToken("animation-normal", "0.25s ease", "animation"),
            "animation-slow": IDSToken("animation-slow", "0.4s ease", "animation"),
        }

    def _init_components(self) -> list[dict]:
        return [
            {"name": "Card", "description": "Surface container", "token": "radius-md"},
            {"name": "Button", "description": "Action trigger", "token": "radius-sm"},
            {"name": "Input", "description": "Text input", "token": "radius-sm"},
            {"name": "Panel", "description": "Layout section", "token": "radius-lg"},
            {"name": "Badge", "description": "Status indicator", "token": "radius-sm"},
            {"name": "Stat", "description": "Metric display", "token": "radius-md"},
        ]

    def get_tokens(self) -> dict[str, str]:
        return {k: v.value for k, v in self.tokens.items()}

    def get_css_variables(self) -> str:
        lines = [":root {"]
        for token in self.tokens.values():
            var_name = f"--ids-{token.name}"
            lines.append(f"  {var_name}: {token.value};")
        lines.append("}")
        return "\n".join(lines)

    def get_component_spec(self, name: str) -> dict | None:
        for c in self.components:
            if c["name"] == name:
                return c
        return None
