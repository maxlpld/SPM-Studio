"""Compact pictograms preserve the existing non-destructive processing behavior."""
from __future__ import annotations
import ast
import os
from pathlib import Path


def test_every_processing_operation_has_a_single_glyph():
    from spm_studio.core.processing import PROCESS_GROUPS
    source=Path(__file__).resolve().parents[1]/'src/spm_studio/ui/inspector_panel.py'
    tree=ast.parse(source.read_text(encoding='utf-8'))
    symbols=next(ast.literal_eval(node.value) for node in tree.body
                 if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name)
                 and t.id=='PROCESSING_PICTOGRAMS' for t in node.targets))
    operations={operation for commands in PROCESS_GROUPS.values() for _,operation in commands}
    assert set(symbols)==operations
    assert all(1<=len(symbol)<=2 for symbol in symbols.values())
    assert len(set(symbols.values()))==len(symbols)


def test_pictograms_have_hover_names_and_keep_processing_pipeline():
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    import pytest
    pytest.importorskip('PySide6')
    from PySide6.QtWidgets import QApplication,QToolButton
    from spm_studio.core.interactive_tools import TOOLS
    from spm_studio.core.processing import PROCESS_GROUPS
    from spm_studio.ui.interactive_tool_palette import InteractiveToolPalette
    from spm_studio.ui.inspector_panel import InspectorPanel,PROCESSING_PICTOGRAMS
    app=QApplication.instance() or QApplication([])
    palette=InteractiveToolPalette()
    assert len(palette.buttons)==len(TOOLS)
    for tool in TOOLS:
        button=palette.buttons[tool.identifier]
        assert button.text()==tool.symbol
        assert '\n' not in button.text()
        assert button.accessibleName()==tool.label
        assert tool.label in button.toolTip()
    palette.buttons['profile'].click()
    assert palette.current=='profile'

    inspector=InspectorPanel()
    names={op:name for commands in PROCESS_GROUPS.values() for name,op in commands}
    assert set(inspector.processing_buttons)==set(PROCESSING_PICTOGRAMS)
    for op,button in inspector.processing_buttons.items():
        assert isinstance(button,QToolButton)
        assert button.text()==PROCESSING_PICTOGRAMS[op]
        assert button.accessibleName()==names[op]
        assert names[op] in button.toolTip()
    inspector.processing_buttons['gaussian'].click()
    inspector.processing_buttons['row_median'].click()
    assert [step.operation for step in inspector.steps()]==['gaussian','row_median']
    inspector.processing_buttons['fix_zero'].click()
    inspector.processing_buttons['fix_zero'].click()
    assert [step.operation for step in inspector.steps()].count('fix_zero')==1
    palette.close();inspector.close()
