"""Export › Measurement parameters: which acquisition values are written on an image, and where.

The list comes from the scan header (core/scan_parameters.py): general values (bias, setpoint,
feedback, time per line …) and, for a Nanonis Multipass scan, every value of every pass
(P1, P2 …: bias, setpoint, Δz, playback, time per line, speed ratio …).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QComboBox, QCheckBox, QTreeWidget,
                               QTreeWidgetItem, QDialogButtonBox, QLabel, QHBoxLayout, QPushButton)

from ..core import scan_parameters as sp
from .color_field import ColorField

CORNERS = (('Top left', 'top_left'), ('Top right', 'top_right'),
           ('Bottom left', 'bottom_left'), ('Bottom right', 'bottom_right'))


def default_state():
    return {'enabled': False, 'corner': 'top_left', 'keys': None, 'color': '#ffffff', 'background': True}


def clean_state(value) -> dict:
    """Validated copy of a stored parameter-box state (export profiles, sessions)."""
    state = default_state()
    if not isinstance(value, dict):
        return state
    state['enabled'] = bool(value.get('enabled', False))
    if value.get('corner') in dict((v, k) for k, v in CORNERS):
        state['corner'] = value['corner']
    keys = value.get('keys')
    if isinstance(keys, (list, tuple)):
        state['keys'] = [str(k) for k in keys if isinstance(k, str) and 0 < len(k) < 80][:40]
    color = value.get('color')
    if isinstance(color, str) and 0 < len(color) <= 40:
        state['color'] = color
    state['background'] = bool(value.get('background', True))
    return state


def summary(state, scan, channel) -> str:
    if not state.get('enabled'):
        return 'Off'
    keys = state.get('keys')
    keys = sp.default_selection(scan, channel) if keys is None else keys
    lines = sp.lines_for(scan, keys, channel)
    corner = dict((v, k) for k, v in CORNERS).get(state.get('corner'), 'Top left')
    return f'{corner}: ' + ('; '.join(lines) if lines else 'nothing found in the header')


def box_spec(state, scan, channel) -> dict:
    """What export_publication draws (``spec['parameter_box']``)."""
    keys = state.get('keys')
    keys = sp.default_selection(scan, channel) if keys is None else keys
    return {'enabled': bool(state.get('enabled')), 'corner': state.get('corner', 'top_left'),
            'color': state.get('color', '#ffffff'), 'background': bool(state.get('background', True)),
            'keys': list(keys), 'lines': sp.lines_for(scan, keys, channel)}


class ParameterBoxDialog(QDialog):
    def __init__(self, scan, channel, state, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Measurement parameters on the image')
        self.scan, self.channel = scan, channel
        state = clean_state(state)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.enabled = QCheckBox('Write the parameters on this image')
        self.enabled.setChecked(state['enabled'] or state['keys'] is None)
        self.corner = QComboBox()
        for label, value in CORNERS:
            self.corner.addItem(label, value)
        self.corner.setCurrentIndex(max(0, self.corner.findData(state['corner'])))
        self.color = ColorField(state['color'], 'Text colour')
        self.background = QCheckBox('Semi-transparent box behind the text')
        self.background.setChecked(state['background'])
        form.addRow('', self.enabled)
        form.addRow('Corner', self.corner)
        form.addRow('Text colour', self.color)
        form.addRow('', self.background)
        lay.addLayout(form)
        n = sp.pass_of_channel(channel)
        hint = QLabel(f'Channel: {channel}' + (f'  ·  recorded in pass P{n}' if n else '') +
                      '\nTick what to show; the order of the list is the order on the image.')
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Parameter', 'Value'])
        self.tree.setMinimumSize(420, 320)
        lay.addWidget(self.tree, 1)
        params = sp.parameters(scan)
        chosen = set(sp.default_selection(scan, channel) if state['keys'] is None else state['keys'])
        groups = {}
        for p in params:
            if p.group not in groups:
                title = 'Scan' if p.group == 'Scan' else f'Pass {p.group}' + \
                    (' (this channel)' if n is not None and p.group == f'P{n}' else '')
                item = QTreeWidgetItem([title, ''])
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.tree.addTopLevelItem(item)
                item.setExpanded(p.group == 'Scan' or n is None or p.group == f'P{n}')
                groups[p.group] = item
            child = QTreeWidgetItem([p.label, p.value])
            child.setData(0, Qt.ItemDataRole.UserRole, p.key)
            child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            child.setCheckState(0, Qt.CheckState.Checked if p.key in chosen else Qt.CheckState.Unchecked)
            groups[p.group].addChild(child)
        self.tree.resizeColumnToContents(0)
        if not params:
            lay.addWidget(QLabel('This scan header has no bias / setpoint / Multipass information.'))
        row = QHBoxLayout()
        for label, keys in (('Default', None), ('Bias of every pass', 'bias'),
                            ('Bias + setpoint + Δz of every pass', 'pass3'), ('None', [])):
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, k=keys: self._preset(k))
            row.addWidget(button)
        lay.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _items(self):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                yield top.child(j)

    def _preset(self, which):
        if which is None:
            wanted = set(sp.default_selection(self.scan, self.channel))
        elif which == 'bias':
            wanted = {k for k in (it.data(0, Qt.ItemDataRole.UserRole) for it in self._items())
                      if k.endswith('.bias')} or {'bias'}
        elif which == 'pass3':
            wanted = {k for k in (it.data(0, Qt.ItemDataRole.UserRole) for it in self._items())
                      if k.split('.')[-1] in ('bias', 'setpoint', 'z_offset') and '.' in k}
        else:
            wanted = set(which)
        for it in self._items():
            it.setCheckState(0, Qt.CheckState.Checked if it.data(0, Qt.ItemDataRole.UserRole) in wanted
                             else Qt.CheckState.Unchecked)
        if wanted:
            self.enabled.setChecked(True)

    def state(self) -> dict:
        keys = [it.data(0, Qt.ItemDataRole.UserRole) for it in self._items()
                if it.checkState(0) == Qt.CheckState.Checked]
        return {'enabled': self.enabled.isChecked(), 'corner': self.corner.currentData(),
                'keys': keys, 'color': self.color.text().strip() or '#ffffff',
                'background': self.background.isChecked()}
