"""The small BETA mark shown next to everything that only beta testers have (pages, options, tools of extensions)."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel

TOOLTIP = 'Beta: only available to beta testers (private extension)'
SUFFIX = '  · BETA'


def beta_badge(parent=None, text: str = 'BETA') -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName('BetaBadgeV0014')
    label.setToolTip(TOOLTIP)
    label.setAccessibleName('Beta feature')
    label.setStyleSheet('#BetaBadgeV0014 { background: #7c3aed; color: white; border-radius: 6px; padding: 1px 6px;'
                        ' font-size: 10px; font-weight: 700; letter-spacing: 0.5px; }')
    return label


def beta_label(text: str) -> str:
    """Plain-text form for lists and menus: 'My tool  · BETA'."""
    return text if text.endswith(SUFFIX) else text + SUFFIX
