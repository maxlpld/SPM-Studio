"""Presentation editor window (v0.0.8), in the spirit of PowerPoint.

Slides on the left, the slide in the middle (text boxes, LaTeX boxes rendered automatically,
pictures, animated GIFs, videos, shapes), properties on the right, speaker notes below. Figures
exported from SPM Studio arrive through :mod:`.hub`; the assistant acts on the presentation
through ``<spm-doc>`` requests (:meth:`PresentationWindow.ai_action`).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QSize, QSettings, QEvent, QRectF, QSizeF, QPointF, Signal, QMarginsF
from PySide6.QtGui import (QBrush, QKeySequence, QShortcut, QIcon, QPixmap, QPainter, QColor, QFont, QTextCharFormat,
                           QTextCursor, QTextBlockFormat, QTextListFormat, QImageReader)
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget,
                               QListWidgetItem, QGraphicsView, QPlainTextEdit, QTabWidget, QScrollArea, QFormLayout,
                               QLabel, QDoubleSpinBox, QSpinBox, QComboBox, QCheckBox, QLineEdit, QPushButton, QMenu,
                               QFileDialog, QFontComboBox, QSlider, QFrame, QAbstractItemView, QGraphicsTextItem,
                               QApplication)

from spm_studio.documents import settings as doc_settings, deck as deck_model, templates
from spm_studio.shared.dialogs import MessageDialog, TextInputDialog
from .common import HeaderBar, Ribbon, button, open_path, color_button, figure_for_slides, svg_to_image
from .formula import FormulaRenderer
from .slide_items import (Context, SlideScene, TextItem, LatexItem, ImageItem, GifItem, VideoItem, ShapeItem,
                          SlideItem, render_slide, paint_slide)

THUMB_WIDTH = 176
MEDIA_FILTER = {'image': 'Pictures (*.png *.jpg *.jpeg *.svg *.bmp *.webp *.pdf)',
                'gif': 'Animated GIF (*.gif)',
                'video': 'Videos (*.mp4 *.mov *.webm *.mkv *.avi *.m4v)'}


# ============================================================================ widgets
class ThumbList(QListWidget):
    reordered = Signal(list)          # slide ids in the new order
    deleteRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('slideThumbs')
        self.setIconSize(QSize(THUMB_WIDTH, int(THUMB_WIDTH * 9 / 16)))
        self.setViewMode(QListWidget.ViewMode.ListMode)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSpacing(2)
        self.setFixedWidth(THUMB_WIDTH + 58)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

    def dropEvent(self, event):
        super().dropEvent(event)
        self.reordered.emit([self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())])

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.deleteRequested.emit()
            return
        super().keyPressEvent(event)


class SlideView(QGraphicsView):
    """The slide being edited: fitted in the view, Ctrl+wheel zooms, keyboard edits items."""
    filesDropped = Signal(list, QPointF)

    def __init__(self, window, scene):
        super().__init__(scene)
        self.window_ = window
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform |
                            QPainter.RenderHint.TextAntialiasing)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setAcceptDrops(True)
        self.zoom = None              # None = fit
        try:
            from spm_studio.shared.appearance import colors
            self.setBackgroundBrush(QColor(colors()['sidebar']))
        except Exception:
            self.setBackgroundBrush(QColor('#2A2D33'))

    def fit(self):
        rect = self.scene().sceneRect()
        if self.zoom is None:
            margin = 28
            self.fitInView(rect.adjusted(-margin, -margin, margin, margin), Qt.AspectRatioMode.KeepAspectRatio)
        else:
            self.resetTransform()
            self.scale(self.zoom, self.zoom)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            current = self.transform().m11()
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.zoom = max(0.1, min(6.0, current * factor))
            self.fit()
            return
        super().wheelEvent(event)

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        page = self.scene().sceneRect()
        painter.fillRect(page.translated(3, 4), QColor(0, 0, 0, 60))

    def _editing_text(self) -> bool:
        focus = self.scene().focusItem()
        return isinstance(focus, QGraphicsTextItem) and bool(
            focus.textInteractionFlags() & Qt.TextInteractionFlag.TextEditorInteraction)

    def keyPressEvent(self, event):
        if self._editing_text():
            super().keyPressEvent(event)
            return
        w = self.window_
        key, mods = event.key(), event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            w.delete_selected()
        elif ctrl and key == Qt.Key.Key_Z:
            w.redo_action() if mods & Qt.KeyboardModifier.ShiftModifier else w.undo_action()
        elif ctrl and key == Qt.Key.Key_Y:
            w.redo_action()
        elif ctrl and key == Qt.Key.Key_C:
            w.copy_selected()
        elif ctrl and key == Qt.Key.Key_X:
            w.copy_selected()
            w.delete_selected()
        elif ctrl and key == Qt.Key.Key_V:
            w.paste()
        elif ctrl and key == Qt.Key.Key_D:
            w.duplicate_selected()
        elif ctrl and key == Qt.Key.Key_A:
            for item in w.scene.graphics.values():
                item.setSelected(True)
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down) and w.selected_items():
            step = 10.0 if mods & Qt.KeyboardModifier.ShiftModifier else 1.0
            dx = {Qt.Key.Key_Left: -step, Qt.Key.Key_Right: step}.get(key, 0.0)
            dy = {Qt.Key.Key_Up: -step, Qt.Key.Key_Down: step}.get(key, 0.0)
            w.nudge(dx, dy)
        elif key in (Qt.Key.Key_PageDown,):
            w.show_slide(w.index + 1)
        elif key in (Qt.Key.Key_PageUp,):
            w.show_slide(w.index - 1)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_F2) and w.selected_items():
            item = w.selected_items()[0]
            if isinstance(item, TextItem):
                item.start_edit(select_all=False)
            elif isinstance(item, LatexItem):
                w.focus_latex_source()
        elif key == Qt.Key.Key_Escape:
            w.scene.clearSelection()
        else:
            super().keyPressEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            files = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
            self.filesDropped.emit(files, self.mapToScene(event.position().toPoint()))
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def contextMenuEvent(self, event):
        item = self.itemAt(event.pos())
        while item is not None and not isinstance(item, SlideItem):
            item = item.parentItem()
        w = self.window_
        menu = QMenu(self)
        if item is not None:
            if not item.isSelected():
                w.scene.clearSelection()
                item.setSelected(True)
            menu.addAction('Cut', lambda: (w.copy_selected(), w.delete_selected()))
            menu.addAction('Copy', w.copy_selected)
            menu.addAction('Duplicate\tCtrl+D', w.duplicate_selected)
            menu.addAction('Delete', w.delete_selected)
            menu.addSeparator()
            menu.addAction('Bring to front', lambda: w.restack('front'))
            menu.addAction('Send to back', lambda: w.restack('back'))
            if isinstance(item, (ImageItem, GifItem)) and not isinstance(item, VideoItem):
                menu.addAction('Original size ratio', w.reset_ratio)
        menu.addAction('Paste\tCtrl+V', w.paste)
        menu.addSeparator()
        menu.addAction('New slide', lambda: w.new_slide('title_content'))
        menu.exec(event.globalPos())


# ============================================================================ window
class PresentationWindow(QMainWindow):
    def __init__(self, deck_path, hub=None):
        super().__init__()
        self.hub = hub
        self.conf = doc_settings.load()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(1500, 900)
        self.setAcceptDrops(True)
        self.renderer = FormulaRenderer.instance()
        self.renderer.rendered.connect(self._formula_ready)
        self.deck = {}
        self.index = 0
        self.undo_stack, self.redo_stack = [], []
        self._state = ''
        self._dirty = False
        self._clipboard = []
        self._slideshow = None
        self._building = False
        self._latex_source = None
        self.deck_path = Path(deck_path)
        self.project_dir = self.deck_path.parent
        self.deck.update(deck_model.load(self.deck_path))
        self.ctx = Context(self.deck, self.project_dir, editable=True, live=True, renderer=self.renderer)
        self.scene = SlideScene(self.ctx, self)
        self.scene.selectionChanged.connect(self._selection_changed)
        self._timers()
        self._build()
        self._state = self._serialise()
        self._set_title()
        doc_settings.add_recent('slides', self.deck_path)
        self.refresh_thumbs()
        self.show_slide(0)
        geometry = QSettings('SPM Studio', 'Documents').value('slides_geometry')
        if geometry:
            self.restoreGeometry(geometry)

    def title(self) -> str:
        return self.deck.get('title') or self.project_dir.name

    def _set_title(self):
        mark = ' •' if self._dirty else ''
        self.header.title.setText(self.title() + mark)
        self.setWindowTitle(f'{self.title()}{mark} — Presentation · SPM Studio')

    def _timers(self):
        def timer(ms, slot):
            t = QTimer(self)
            t.setSingleShot(True)
            t.setInterval(ms)
            t.timeout.connect(slot)
            return t
        self.commit_timer = timer(350, self.commit)
        self.thumb_timer = timer(250, lambda: self.refresh_thumb(self.index))
        self.autosave_timer = timer(1500, self._autosave)
        self.latex_timer = timer(500, self._latex_source_changed)
        self.all_thumbs_timer = timer(600, self._refresh_formula_thumbs)

    # ================================================================== interface
    def _build(self):
        central = QWidget()
        central.setObjectName('workbenchRoot')
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header = HeaderBar('Presentation')
        self.menu_button = button('File', 'menu', 'New, open, import, save as, templates, export')
        self.menu_button.setPopupMode(self.menu_button.ToolButtonPopupMode.InstantPopup)
        self.file_menu = QMenu(self)
        self.menu_button.setMenu(self.file_menu)
        self.header.row.insertWidget(0, self.menu_button)
        self.header.stretch()
        self.from_spm = button('From SPM Studio', 'send-to', 'Add a scan or an analysis figure from SPM Studio')
        self.from_spm.setPopupMode(self.from_spm.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self)
        menu.addAction('Export the open scan onto a new slide…', lambda: self._export_from_scan('new'))
        menu.addAction('Export the open scan onto this slide…', lambda: self._export_from_scan('current'))
        self.from_spm.setMenu(menu)
        self.header.add(self.from_spm)
        self.assistant_button = button('Assistant', 'ai', 'Open the AI assistant next to this window')
        self.assistant_button.clicked.connect(lambda: self.hub.show_assistant(self) if self.hub else None)
        self.header.add(self.assistant_button)
        from spm_studio.shared.appearance import separator
        self.header.add(separator())
        self.save_button = button('', 'save', 'Save (Ctrl+S)', icon_only=True)
        self.save_button.clicked.connect(self.save)
        self.header.add(self.save_button)
        self.present_button = button('Present', 'play', 'Slide show from the beginning (F5)', flat=False, primary=True)
        self.present_button.setObjectName('SlidesPresentV008')
        present_menu = QMenu(self)
        present_menu.addAction('From the beginning\tF5', lambda: self.present(0))
        present_menu.addAction('From this slide\tShift+F5', lambda: self.present(self.index))
        self.present_button.setMenu(present_menu)
        self.present_button.setPopupMode(self.present_button.ToolButtonPopupMode.MenuButtonPopup)
        self.present_button.clicked.connect(lambda: self.present(0))
        self.header.add(self.present_button)
        root.addWidget(self.header)
        self.ribbon = Ribbon()
        self._fill_ribbon()
        root.addWidget(self.ribbon)

        body = QSplitter(Qt.Orientation.Horizontal)
        body.setChildrenCollapsible(False)
        self.thumbs = ThumbList()
        self.thumbs.currentRowChanged.connect(lambda row: self.show_slide(row) if row >= 0 and row != self.index
                                              and not self._building else None)
        self.thumbs.reordered.connect(self._reordered)
        self.thumbs.deleteRequested.connect(self.delete_slide)
        self.thumbs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.thumbs.customContextMenuRequested.connect(self._thumb_menu)
        body.addWidget(self.thumbs)
        centre = QSplitter(Qt.Orientation.Vertical)
        self.view = SlideView(self, self.scene)
        self.view.filesDropped.connect(self._files_dropped)
        centre.addWidget(self.view)
        self.notes = QPlainTextEdit()
        self.notes.setObjectName('speakerNotes')
        self.notes.setPlaceholderText('Click to add speaker notes')
        self.notes.textChanged.connect(self._notes_changed)
        centre.addWidget(self.notes)
        centre.setSizes([760, 110])
        body.addWidget(centre)
        self.props = QTabWidget()
        self.props.setMinimumWidth(300)
        self.props.setMaximumWidth(380)
        self.item_page = QScrollArea()
        self.item_page.setWidgetResizable(True)
        self.slide_page = QScrollArea()
        self.slide_page.setWidgetResizable(True)
        self.design_page = QScrollArea()
        self.design_page.setWidgetResizable(True)
        self.props.addTab(self.item_page, 'Format')
        self.props.addTab(self.slide_page, 'Slide')
        self.props.addTab(self.design_page, 'Design')
        body.addWidget(self.props)
        body.setStretchFactor(1, 1)
        root.addWidget(body, 1)
        self.setCentralWidget(central)
        self.status = QLabel('')
        self.statusBar().addWidget(self.status)
        self._fill_file_menu()
        self._build_design_page()
        for keys, slot in (('Ctrl+S', self.save), ('F5', lambda: self.present(0)),
                           ('Shift+F5', lambda: self.present(self.index)), ('Ctrl+M', lambda: self.new_slide('title_content'))):
            QShortcut(QKeySequence(keys), self, activated=slot)

    def _fill_ribbon(self):
        r = self.ribbon
        undo = button('', 'undo', 'Undo (Ctrl+Z)', icon_only=True)
        undo.clicked.connect(self.undo_action)
        redo = button('', 'redo', 'Redo (Ctrl+Y)', icon_only=True)
        redo.clicked.connect(self.redo_action)
        r.add(undo)
        r.add(redo)
        r.separator()
        new = button('New slide', 'plus', 'New slide (Ctrl+M) — arrow: choose the layout')
        layouts = QMenu(self)
        for key, label in deck_model.LAYOUTS.items():
            layouts.addAction(label, lambda k=key: self.new_slide(k))
        new.setMenu(layouts)
        new.setPopupMode(new.ToolButtonPopupMode.MenuButtonPopup)
        new.clicked.connect(lambda: self.new_slide('title_content'))
        dup = button('', 'copy', 'Duplicate slide', icon_only=True)
        dup.clicked.connect(self.duplicate_slide)
        delete = button('', 'trash', 'Delete slide', icon_only=True)
        delete.clicked.connect(self.delete_slide)
        for w in (new, dup, delete):
            r.add(w)
        r.separator()
        for text, icon_name, tip, slot in (
                ('Text', 'text', 'Text box', lambda: self.add_text()),
                ('LaTeX', 'formula', 'LaTeX text box: write LaTeX, it is compiled and shown automatically',
                 lambda: self.add_latex()),
                ('Image', 'image', 'Picture (PNG, JPG, SVG, PDF)', lambda: self.add_media_dialog('image')),
                ('GIF', 'gif', 'Animated GIF', lambda: self.add_media_dialog('gif')),
                ('Video', 'video', 'Video (MP4, MOV, WebM…)', lambda: self.add_media_dialog('video'))):
            b = button(text, icon_name, tip)
            b.clicked.connect(slot)
            if text == 'LaTeX':
                b.setObjectName('SlidesAddLatexBoxV008')
            r.add(b)
        shape = button('Shape', 'shape', 'Rectangle, rounded rectangle, ellipse, triangle, line, arrow')
        shape.setPopupMode(shape.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self)
        for key, label in (('rect', 'Rectangle'), ('rounded', 'Rounded rectangle'), ('ellipse', 'Ellipse'),
                           ('triangle', 'Triangle'), ('line', 'Line'), ('arrow', 'Arrow')):
            menu.addAction(label, lambda k=key: self.add_shape(k))
        shape.setMenu(menu)
        r.add(shape)
        r.separator()
        self.font_box = QFontComboBox()
        self.font_box.setObjectName('SlidesFontBoxV008')
        self.font_box.setFixedWidth(150)
        self.font_box.setToolTip('Font of the selected text')
        self.font_box.currentFontChanged.connect(lambda f: self._char_format(family=f.family()))
        self.size_box = QSpinBox()
        self.size_box.setObjectName('SlidesSizeBoxV008')
        self.size_box.setRange(6, 160)
        self.size_box.setValue(int(self.deck.get('theme', {}).get('body_size', 20)))
        self.size_box.setSuffix(' pt')
        self.size_box.setToolTip('Font size of the selected text')
        self.size_box.editingFinished.connect(lambda: self._char_format(size=self.size_box.value()))
        r.add(self.font_box)
        r.add(self.size_box)
        for icon_name, tip in (('bold', 'Bold'), ('italic', 'Italic'), ('underline', 'Underline')):
            b = button('', icon_name, tip, icon_only=True)
            b.clicked.connect(lambda _=False, k=icon_name: self._toggle(k))
            r.add(b)
        self.text_color = color_button('#1A1D22', 'Text colour', lambda c: self._char_format(color=c))
        r.add(self.text_color)
        for icon_name, align in (('align-left', Qt.AlignmentFlag.AlignLeft), ('align-center', Qt.AlignmentFlag.AlignHCenter),
                                 ('align-right', Qt.AlignmentFlag.AlignRight)):
            b = button('', icon_name, 'Align ' + icon_name.split('-')[1], icon_only=True)
            b.clicked.connect(lambda _=False, a=align: self._align_text(a))
            r.add(b)
        bullets = button('', 'list', 'Bullets', icon_only=True)
        bullets.clicked.connect(self._toggle_bullets)
        r.add(bullets)
        r.separator()
        front = button('', 'front', 'Bring to front', icon_only=True)
        front.clicked.connect(lambda: self.restack('front'))
        back = button('', 'back-layer', 'Send to back', icon_only=True)
        back.clicked.connect(lambda: self.restack('back'))
        align = button('Align', None, 'Align the selection on the slide')
        align.setPopupMode(align.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self)
        for key, label in (('left', 'Left'), ('hcenter', 'Centre horizontally'), ('right', 'Right'),
                           ('top', 'Top'), ('vcenter', 'Centre vertically'), ('bottom', 'Bottom')):
            menu.addAction(label, lambda k=key: self.align(k))
        align.setMenu(menu)
        for w in (front, back, align):
            r.add(w)
        r.stretch()
        fit = button('', 'fit', 'Fit the slide in the window', icon_only=True)
        fit.clicked.connect(lambda: (setattr(self.view, 'zoom', None), self.view.fit()))
        r.add(fit)

    def _fill_file_menu(self):
        m = self.file_menu
        m.clear()
        m.addAction('New presentation…', lambda: self.hub.launch('slides', self) if self.hub else None)
        m.addAction('Open…', self._open)
        m.addAction('Import a PowerPoint file (.pptx)…', self._import_pptx)
        m.addSeparator()
        m.addAction('Save\tCtrl+S', self.save)
        m.addAction('Save as… (copy elsewhere)', self._save_as)
        m.addAction('Save as template…', self._save_as_template)
        m.addAction('Apply a template…', self._apply_template)
        m.addSeparator()
        m.addAction('Export as PDF…', self.export_pdf)
        m.addAction('Export as PowerPoint (.pptx)…', self.export_pptx)
        m.addAction('Export slides as PNG images…', self.export_png)
        m.addAction('Export as .zip (to share)…', self._export_zip)
        m.addSeparator()
        m.addAction('Rename…', self._rename)
        m.addAction('Open project folder', lambda: open_path(self.project_dir))
        m.addAction('Close', self.close)

    # ================================================================== model ⇄ view
    def _serialise(self) -> str:
        return json.dumps(self.deck, sort_keys=True, ensure_ascii=False)

    def slides(self):
        return self.deck['slides']

    def current_slide(self):
        return self.slides()[self.index]

    def show_slide(self, index):
        if not self.slides():
            return
        index = max(0, min(len(self.slides()) - 1, index))
        self._finish_text_edits()
        self.index = index
        graphics = self.scene.build(self.current_slide(), index + 1, len(self.slides()))
        for item in graphics.values():
            item.changed.connect(self._item_changed)
            item.editRequested.connect(self.focus_latex_source)
        self.view.fit()
        self._building = True
        self.thumbs.setCurrentRow(index)
        self._building = False
        self.notes.blockSignals(True)
        self.notes.setPlainText(self.current_slide().get('notes', ''))
        self.notes.blockSignals(False)
        self._build_slide_page()
        self._selection_changed()
        self.status.setText(f'Slide {index + 1} of {len(self.slides())}')

    def _rebuild_current(self):
        selected = [i.data['id'] for i in self.selected_items()]
        self.show_slide(self.index)
        for key in selected:
            if key in self.scene.graphics:
                self.scene.graphics[key].setSelected(True)

    def _item_changed(self):
        # every selected item moved together: keep their model positions in step
        for item in list(self.scene.graphics.values()):
            try:
                pos = item.pos()
            except RuntimeError:
                continue
            if abs(pos.x() - float(item.data['x'])) > 0.01 or abs(pos.y() - float(item.data['y'])) > 0.01:
                item.data['x'] = round(pos.x(), 2)
                item.data['y'] = round(pos.y(), 2)
        self._selection_changed(refresh_only=True)
        self.commit()

    def commit(self):
        """Record an undo step if the presentation changed; refresh thumbnail; autosave."""
        self.commit_timer.stop()
        state = self._serialise()
        if state == self._state:
            return
        self.undo_stack.append(self._state)
        del self.undo_stack[:-150]
        self.redo_stack.clear()
        self._state = state
        self._dirty = True
        self._set_title()
        self.thumb_timer.start()
        if self.conf.get('slides_autosave', True):
            self.autosave_timer.start()

    def _restore(self, state):
        self.deck.clear()
        self.deck.update(json.loads(state))
        self._state = state
        self._dirty = True
        self._set_title()
        self.index = min(self.index, len(self.slides()) - 1)
        self.refresh_thumbs()
        self.show_slide(self.index)
        self._build_design_page()
        if self.conf.get('slides_autosave', True):
            self.autosave_timer.start()

    def undo_action(self):
        self._finish_text_edits()
        self.commit()
        if self.undo_stack:
            self.redo_stack.append(self._state)
            self._restore(self.undo_stack.pop())

    def redo_action(self):
        if self.redo_stack:
            self.undo_stack.append(self._state)
            self._restore(self.redo_stack.pop())

    def _finish_text_edits(self):
        for item in list(self.scene.graphics.values()):
            if isinstance(item, TextItem) and item.editing():
                item.finish_edit()

    # ================================================================== thumbnails
    def refresh_thumbs(self):
        self._building = True
        self.thumbs.clear()
        for i, slide in enumerate(self.slides()):
            item = QListWidgetItem(str(i + 1))
            item.setData(Qt.ItemDataRole.UserRole, slide['id'])
            item.setIcon(self._thumb_icon(i))
            if slide.get('hidden'):
                item.setForeground(QBrush(QColor(140, 140, 140)))
                item.setText(f'{i + 1}  (hidden)')
            self.thumbs.addItem(item)
        self.thumbs.setCurrentRow(self.index)
        self._building = False

    def _thumb_icon(self, index) -> QIcon:
        image = render_slide(self.deck, index, self.project_dir, THUMB_WIDTH * 2, self.renderer)
        return QIcon(QPixmap.fromImage(image))

    def refresh_thumb(self, index):
        if 0 <= index < self.thumbs.count():
            self.thumbs.item(index).setIcon(self._thumb_icon(index))

    def _formula_ready(self, _key):
        self.all_thumbs_timer.start()

    def _refresh_formula_thumbs(self):
        for index, slide in enumerate(self.slides()):
            if any(i.get('type') == 'latex' for i in slide.get('items', [])):
                self.refresh_thumb(index)

    def _reordered(self, ids):
        by_id = {s['id']: s for s in self.slides()}
        current = self.current_slide()['id']
        self.deck['slides'] = [by_id[i] for i in ids if i in by_id]
        self.index = next((n for n, s in enumerate(self.slides()) if s['id'] == current), 0)
        self.commit()
        self.refresh_thumbs()
        self.show_slide(self.index)

    def _thumb_menu(self, pos):
        row = self.thumbs.indexAt(pos).row()
        if row >= 0 and row != self.index:
            self.show_slide(row)
        menu = QMenu(self)
        layouts = menu.addMenu('New slide')
        for key, label in deck_model.LAYOUTS.items():
            layouts.addAction(label, lambda k=key: self.new_slide(k))
        menu.addAction('Duplicate slide', self.duplicate_slide)
        menu.addAction('Delete slide', self.delete_slide)
        hidden = menu.addAction('Hide slide in the slide show')
        hidden.setCheckable(True)
        hidden.setChecked(bool(self.current_slide().get('hidden')))
        hidden.toggled.connect(self._toggle_hidden)
        menu.addSeparator()
        menu.addAction('Present from this slide', lambda: self.present(self.index))
        menu.exec(self.thumbs.viewport().mapToGlobal(pos))

    def _toggle_hidden(self, on):
        self.current_slide()['hidden'] = bool(on)
        self.commit()
        self.refresh_thumbs()
        self._build_slide_page()

    # ================================================================== slides
    def slide_size(self):
        return float(self.deck['width']), float(self.deck['height'])

    def new_slide(self, layout='title_content', title='', body=None, after=None) -> dict:
        slide = deck_model.new_slide(layout, self.deck['theme'], self.slide_size(), title=title)
        if body is not None:
            for item in slide['items']:
                if item.get('role') == 'body':
                    item['html'] = deck_model.text_html(body, size=float(self.deck['theme'].get('body_size', 20)),
                                                        color=self.deck['theme'].get('text_color', '#1A1D22'),
                                                        font=self.deck['theme'].get('body_font', 'Inter'))
                    break
        position = (self.index + 1) if after is None else max(0, min(len(self.slides()), after))
        self.slides().insert(position, slide)
        self.commit()
        self.refresh_thumbs()
        self.show_slide(position)
        return slide

    def duplicate_slide(self):
        slide = copy.deepcopy(self.current_slide())
        slide['id'] = deck_model.new_id()
        for item in slide['items']:
            item['id'] = deck_model.new_id()
        self.slides().insert(self.index + 1, slide)
        self.commit()
        self.refresh_thumbs()
        self.show_slide(self.index + 1)

    def delete_slide(self, index=None):
        index = self.index if index is None or isinstance(index, bool) else index
        if len(self.slides()) <= 1:
            self.slides()[0]['items'] = []
        else:
            self.slides().pop(index)
        self.index = min(index, len(self.slides()) - 1)
        self.commit()
        self.refresh_thumbs()
        self.show_slide(self.index)

    # ================================================================== items
    def selected_items(self):
        return [i for i in self.scene.selectedItems() if isinstance(i, SlideItem)]

    def _add(self, data, select=True):
        self.current_slide()['items'].append(data)
        self.commit()
        self._rebuild_current()
        item = self.scene.graphics.get(data['id'])
        if select and item is not None:
            self.scene.clearSelection()
            item.setSelected(True)
        return item

    def _theme(self):
        return self.deck['theme']

    def add_text(self, text='Text', x=None, y=None, w=None, h=None, size=None, color=None, bold=False):
        sw, sh = self.slide_size()
        t = self._theme()
        w = w or sw * 0.6
        h = h or 60.0
        data = deck_model.make_item('text', x if x is not None else (sw - w) / 2, y if y is not None else (sh - h) / 2,
                                    w, h, html=deck_model.text_html(text, size=size or float(t.get('body_size', 20)),
                                                                    color=color or t.get('text_color', '#1A1D22'),
                                                                    font=t.get('body_font', 'Inter'), bold=bold))
        item = self._add(data)
        if item is not None and text == 'Text' and x is None:
            QTimer.singleShot(0, lambda: item.start_edit(select_all=True))
        return data

    def add_latex(self, source=r'$\nabla \cdot \mathbf{E} = \rho / \varepsilon_0$', x=None, y=None, w=None, h=None,
                  size=None, color=None):
        sw, sh = self.slide_size()
        w = w or sw * 0.5
        h = h or 70.0
        data = deck_model.make_item('latex', x if x is not None else (sw - w) / 2, y if y is not None else (sh - h) / 2,
                                    w, h, source=source, size=float(size or 28),
                                    color=color or self._theme().get('text_color', '#1A1D22'))
        self._add(data)
        if x is None:
            QTimer.singleShot(0, self.focus_latex_source)
        return data

    def add_shape(self, kind='rect', x=None, y=None, w=None, h=None, fill=None):
        sw, sh = self.slide_size()
        w = w or (240.0 if kind not in ('line', 'arrow') else 260.0)
        h = h or (140.0 if kind not in ('line', 'arrow') else 24.0)
        accent = self._theme().get('accent_color', '#0F7C6F')
        data = deck_model.make_item('shape', x if x is not None else (sw - w) / 2, y if y is not None else (sh - h) / 2,
                                    w, h, shape=kind, fill_color='' if kind in ('line', 'arrow') else (fill or accent),
                                    line_color=accent if kind in ('line', 'arrow') else '',
                                    line_width=3.0 if kind in ('line', 'arrow') else 0.0)
        self._add(data)
        return data

    def add_media_dialog(self, kind):
        files, _ = QFileDialog.getOpenFileNames(self, 'Insert ' + kind, str(Path.home()), MEDIA_FILTER[kind] +
                                                ';;All files (*)')
        for n, file in enumerate(files):
            self.add_media(Path(file), offset=n * 20)

    def _media_size(self, path: Path) -> QSizeF:
        suffix = path.suffix.lower()
        if suffix == '.svg':
            try:
                from PySide6.QtSvg import QSvgRenderer
                r = QSvgRenderer(str(path))
                box = r.viewBoxF()
                if box.width() > 0:
                    return QSizeF(box.width(), box.height())
            except ImportError:
                pass
        if suffix in deck_model.VIDEO_SUFFIXES:
            return QSizeF(1280, 720)
        reader = QImageReader(str(path))
        size = reader.size()
        return QSizeF(size) if size.isValid() and size.width() > 0 else QSizeF(800, 600)

    def add_media(self, path: Path, at: QPointF | None = None, offset=0.0, box=None, select=True) -> dict:
        path = Path(path)
        if path.suffix.lower() == '.pdf':
            out = self.project_dir / deck_model.MEDIA / (path.stem + '.png')
            out.parent.mkdir(parents=True, exist_ok=True)
            from .common import pdf_to_image
            pdf_to_image(path, 2400).save(str(out))
            path = out
        rel = deck_model.add_media(self.project_dir, path)
        kind = deck_model.media_kind(path)
        sw, sh = self.slide_size()
        natural = self._media_size(self.project_dir / rel)
        if box is None:
            limit_w, limit_h = sw * 0.7, sh * 0.7
            scale = min(limit_w / natural.width(), limit_h / natural.height(), 1e9)
            w, h = natural.width() * scale, natural.height() * scale
            cx, cy = (at.x(), at.y()) if at is not None else (sw / 2 + offset, sh / 2 + offset)
            box = (cx - w / 2, cy - h / 2, w, h)
        data = deck_model.make_item(kind, *box, src=rel)
        self._add(data, select=select)
        return data

    def add_figure(self, files, new_slide=True, title='') -> str:
        """From SPM Studio's export: a picture on a new slide (with a title) or on the current slide."""
        figure = figure_for_slides(files, self.project_dir / '.spm_render')
        label = title or Path(figure).stem.replace('_', ' ')
        if new_slide:
            self.new_slide('title_only', title=label)
            sw, sh = self.slide_size()
            top = 124.0
            natural = self._media_size(Path(figure))
            scale = min((sw - 96) / natural.width(), (sh - top - 40) / natural.height())
            w, h = natural.width() * scale, natural.height() * scale
            self.add_media(Path(figure), box=((sw - w) / 2, top + (sh - top - 40 - h) / 2, w, h))
        else:
            self.add_media(Path(figure))
        self.raise_()
        self.activateWindow()
        return f'slide {self.index + 1} of “{self.title()}”'

    def _files_dropped(self, files, at):
        for n, f in enumerate(files):
            if f.suffix.lower() in deck_model.IMAGE_SUFFIXES + deck_model.VIDEO_SUFFIXES + ('.gif',):
                self.add_media(f, at=QPointF(at.x() + n * 20, at.y() + n * 20))

    def delete_selected(self):
        ids = {i.data['id'] for i in self.selected_items()}
        if not ids:
            return
        self.current_slide()['items'] = [i for i in self.current_slide()['items'] if i['id'] not in ids]
        self.commit()
        self._rebuild_current()

    def copy_selected(self):
        self._clipboard = [copy.deepcopy(i.data) for i in self.selected_items()]
        if self._clipboard:
            QApplication.clipboard().setText(json.dumps({'spm_slide_items': self._clipboard}))

    def paste(self):
        items = self._clipboard
        try:
            data = json.loads(QApplication.clipboard().text())
            if isinstance(data, dict) and isinstance(data.get('spm_slide_items'), list):
                items = data['spm_slide_items']
        except (ValueError, TypeError):
            text = QApplication.clipboard().text().strip()
            image = QApplication.clipboard().image()
            if not image.isNull():
                folder = self.project_dir / deck_model.MEDIA
                folder.mkdir(exist_ok=True)
                target = folder / f'pasted_{deck_model.new_id()}.png'
                image.save(str(target))
                self.add_media(target)
                return
            if text:
                self.add_text(text, x=96, y=160)
                return
        if not items:
            return
        self.scene.clearSelection()
        new_ids = []
        for data in items:
            clone = copy.deepcopy(data)
            clone['id'] = deck_model.new_id()
            clone['x'] = float(clone.get('x', 0)) + 16
            clone['y'] = float(clone.get('y', 0)) + 16
            self.current_slide()['items'].append(deck_model.normalise_item(clone))
            new_ids.append(clone['id'])
        self.commit()
        self._rebuild_current()
        for key in new_ids:
            if key in self.scene.graphics:
                self.scene.graphics[key].setSelected(True)

    def duplicate_selected(self):
        self.copy_selected()
        self.paste()

    def nudge(self, dx, dy):
        for item in self.selected_items():
            item.data['x'] = float(item.data['x']) + dx
            item.data['y'] = float(item.data['y']) + dy
            item.sync_from_data()
        self.commit_timer.start()
        self._selection_changed(refresh_only=True)

    def restack(self, where):
        ids = [i.data['id'] for i in self.selected_items()]
        items = self.current_slide()['items']
        chosen = [i for i in items if i['id'] in ids]
        rest = [i for i in items if i['id'] not in ids]
        self.current_slide()['items'] = rest + chosen if where == 'front' else chosen + rest
        self.scene.restack()
        self.commit()

    def align(self, where):
        sw, sh = self.slide_size()
        for item in self.selected_items():
            d = item.data
            if where == 'left':
                d['x'] = 48.0
            elif where == 'right':
                d['x'] = sw - 48.0 - d['w']
            elif where == 'hcenter':
                d['x'] = (sw - d['w']) / 2
            elif where == 'top':
                d['y'] = 48.0
            elif where == 'bottom':
                d['y'] = sh - 48.0 - d['h']
            else:
                d['y'] = (sh - d['h']) / 2
            item.sync_from_data()
        self.commit()
        self._selection_changed(refresh_only=True)

    def reset_ratio(self):
        for item in self.selected_items():
            if isinstance(item, ImageItem):
                natural = item.natural_size()
                if natural.width() > 0:
                    item.prepareGeometryChange()
                    item.data['h'] = item.data['w'] * natural.height() / natural.width()
                    item.sync_from_data()
        self.commit()

    def _notes_changed(self):
        self.current_slide()['notes'] = self.notes.toPlainText()
        self.commit_timer.start()

    # ================================================================== text format
    def _text_targets(self):
        return [i for i in self.selected_items() if isinstance(i, TextItem)]

    def _char_format(self, family=None, size=None, color=None, toggle=None):
        """Apply a character format to the selected words (while typing) or to the whole text box."""
        targets = self._text_targets()
        if not targets:
            return
        for item in targets:
            editor = item.editor
            cursor = editor.textCursor() if item.editing() and editor.textCursor().hasSelection() else None
            if cursor is None:
                cursor = QTextCursor(editor.document())
                cursor.select(QTextCursor.SelectionType.Document)
            current = cursor.charFormat()
            fmt = QTextCharFormat()
            if family:
                fmt.setFontFamilies([family])
            if size:
                fmt.setFontPointSize(float(size))
            if color:
                fmt.setForeground(QBrush(QColor(color)))
            if toggle == 'bold':
                fmt.setFontWeight(int(QFont.Weight.Normal.value) if current.fontWeight() >= 600
                                  else int(QFont.Weight.Bold.value))
            elif toggle == 'italic':
                fmt.setFontItalic(not current.fontItalic())
            elif toggle == 'underline':
                fmt.setFontUnderline(not current.fontUnderline())
            cursor.mergeCharFormat(fmt)
            if not item.editing():
                item.commit_html()
            item.geometry_changed()
            item.update()

    def _toggle(self, what):
        self._char_format(toggle=what)

    def _align_text(self, alignment):
        for item in self._text_targets():
            editor = item.editor
            cursor = editor.textCursor() if item.editing() else QTextCursor(editor.document())
            if not item.editing():
                cursor.select(QTextCursor.SelectionType.Document)
            fmt = QTextBlockFormat()
            fmt.setAlignment(alignment)
            cursor.mergeBlockFormat(fmt)
            if not item.editing():
                item.commit_html()
            item.update()

    def _toggle_bullets(self):
        for item in self._text_targets():
            editor = item.editor
            cursor = editor.textCursor() if item.editing() else QTextCursor(editor.document())
            if not item.editing():
                cursor.select(QTextCursor.SelectionType.Document)
            current = cursor.currentList()
            if current is not None:
                block = cursor.document().findBlock(cursor.selectionStart())
                end = cursor.selectionEnd()
                while block.isValid() and block.position() <= end:
                    if block.textList() is not None:
                        block.textList().remove(block)
                    fmt = block.blockFormat()
                    fmt.setIndent(0)
                    QTextCursor(block).setBlockFormat(fmt)
                    block = block.next()
            else:
                style = QTextListFormat()
                style.setStyle(QTextListFormat.Style.ListDisc)
                style.setIndent(1)
                cursor.createList(style)
            if not item.editing():
                item.commit_html()
            item.update()

    # ================================================================== properties
    def _clear_page(self, page):
        old = page.takeWidget()          # deleted later: the widget may be the sender of this change
        if old is not None:
            old.hide()
            old.deleteLater()
        widget = QWidget()
        form = QFormLayout(widget)
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        page.setWidget(widget)
        return form

    @staticmethod
    def _section(form, text):
        label = QLabel(text.upper())
        label.setObjectName('panelTitle')
        form.addRow(label)

    def _spin(self, value, lo, hi, step=1.0, decimals=1, suffix=''):
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(decimals)
        s.setSingleStep(step)
        s.setValue(float(value))
        s.setSuffix(suffix)
        s.setKeyboardTracking(False)
        return s

    def _set_prop(self, item, key, value, rebuild=False):
        item.data[key] = value
        if rebuild:
            item.prepareGeometryChange()
        item.sync_from_data()
        self.commit_timer.start()

    def _selection_changed(self, refresh_only=False):
        try:
            items = self.selected_items()
        except RuntimeError:
            return
        if refresh_only and getattr(self, '_geometry_spins', None) and len(items) == 1:
            d = items[0].data
            for key, spin in self._geometry_spins.items():
                spin.blockSignals(True)
                spin.setValue(float(d.get(key, 0)))
                spin.blockSignals(False)
            return
        self._geometry_spins = {}
        self._latex_source = None
        form = self._clear_page(self.item_page)
        if not items:
            form.addRow(QLabel('Select an item on the slide to change it.\n\nDouble-click a text box to type in '
                               'it; double-click a LaTeX box to edit its source.'))
            return
        if len(items) > 1:
            form.addRow(QLabel(f'{len(items)} items selected'))
            self._common_rows(form, items)
            return
        item = items[0]
        d = item.data
        names = {'text': 'Text box', 'latex': 'LaTeX box', 'image': 'Picture', 'gif': 'Animated GIF',
                 'video': 'Video', 'shape': 'Shape'}
        self._section(form, names.get(d['type'], d['type']))
        if d['type'] == 'latex':
            self._latex_rows(form, item)
        elif d['type'] == 'text':
            self._text_rows(form, item)
        elif d['type'] in ('image', 'gif', 'video'):
            self._media_rows(form, item)
        elif d['type'] == 'shape':
            self._shape_rows(form, item)
        self._section(form, 'Position and size')
        for key, label in (('x', 'X'), ('y', 'Y'), ('w', 'Width'), ('h', 'Height')):
            spin = self._spin(d.get(key, 0), -2000 if key in 'xy' else 4, 4000, 1.0, 1, ' pt')
            spin.valueChanged.connect(lambda v, k=key: self._set_prop(item, k, float(v), rebuild=True))
            self._geometry_spins[key] = spin
            form.addRow(label, spin)
        self._common_rows(form, [item])

    def _common_rows(self, form, items):
        first = items[0].data
        rotation = self._spin(first.get('rotation', 0), -360, 360, 5, 0, '°')
        rotation.valueChanged.connect(lambda v: [self._set_prop(i, 'rotation', float(v)) for i in items])
        form.addRow('Rotation', rotation)
        opacity = QSlider(Qt.Orientation.Horizontal)
        opacity.setRange(5, 100)
        opacity.setValue(int(float(first.get('opacity', 1)) * 100))
        opacity.valueChanged.connect(lambda v: [self._set_prop(i, 'opacity', v / 100.0) for i in items])
        form.addRow('Opacity', opacity)
        row = QHBoxLayout()
        for text, slot in (('Front', lambda: self.restack('front')), ('Back', lambda: self.restack('back')),
                           ('Delete', self.delete_selected)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            if text == 'Delete':
                b.setProperty('destructive', True)
            row.addWidget(b)
        holder = QWidget()
        holder.setLayout(row)
        form.addRow(holder)

    def _latex_rows(self, form, item):
        d = item.data
        source = QPlainTextEdit(d.get('source', ''))
        source.setObjectName('SlidesLatexSourceV008')
        source.setMinimumHeight(140)
        from PySide6.QtGui import QFontDatabase
        source.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        from .code_editor import LatexHighlighter
        source._highlighter = LatexHighlighter(source.document())
        source.setPlaceholderText('Text with $inline$ math, or \\[ display math \\]')
        self._latex_source = (source, item)
        form.addRow(QLabel('LaTeX source'))
        form.addRow(source)
        auto = QCheckBox('Render automatically while typing')
        auto.setChecked(bool(self.conf.get('formula_autorender', True)))
        auto.toggled.connect(lambda on: doc_settings.update(formula_autorender=bool(on)))
        render = QPushButton('Render now')
        render.clicked.connect(lambda: self._apply_latex_source(force=True))
        source.textChanged.connect(lambda: self.latex_timer.start() if auto.isChecked() else None)
        form.addRow(auto)
        form.addRow(render)
        error = self.renderer.error(item.key) if item.key else None
        self._latex_status = QLabel(('⚠ ' + error) if error else '')
        self._latex_status.setWordWrap(True)
        self._latex_status.setObjectName('hint')
        form.addRow(self._latex_status)
        size = self._spin(d.get('size', 24), 6, 200, 1, 0, ' pt')
        size.valueChanged.connect(lambda v: self._set_prop(item, 'size', float(v)))
        form.addRow('Size', size)
        form.addRow('Colour', color_button(d.get('color', '#000000'), 'Formula colour',
                                           lambda c: self._set_prop(item, 'color', c or '#000000')))
        align = QComboBox()
        for key, label in (('left', 'Left'), ('center', 'Centre'), ('right', 'Right')):
            align.addItem(label, key)
        align.setCurrentIndex(max(0, align.findData(d.get('align', 'center'))))
        align.currentIndexChanged.connect(lambda _i: self._set_prop(item, 'align', align.currentData()))
        form.addRow('Alignment', align)
        form.addRow('Background', color_button(d.get('fill_color', ''), 'Box background',
                                               lambda c: self._set_prop(item, 'fill_color', c), allow_none=True))
        form.addRow(QLabel('Packages for every LaTeX box: Design tab.'))

    def focus_latex_source(self):
        items = self.selected_items()
        if items and isinstance(items[0], LatexItem):
            self.props.setCurrentWidget(self.item_page)
            if self._latex_source is None:
                self._selection_changed()
            if self._latex_source is not None:
                self._latex_source[0].setFocus()
                cursor = self._latex_source[0].textCursor()
                cursor.select(QTextCursor.SelectionType.Document)
                self._latex_source[0].setTextCursor(cursor)

    def _latex_source_changed(self):
        self._apply_latex_source()

    def _apply_latex_source(self, force=False):
        if self._latex_source is None:
            return
        source, item = self._latex_source
        try:
            text = source.toPlainText()
        except RuntimeError:
            return
        if force:
            self.renderer.forget_errors()
        item.data['source'] = text
        item.content_changed()
        item.update()
        self.commit_timer.start()
        QTimer.singleShot(1500, self._update_latex_status)

    def _update_latex_status(self):
        if self._latex_source is None:
            return
        _source, item = self._latex_source
        try:
            error = self.renderer.error(item.key) if item.key else None
            self._latex_status.setText(('⚠ ' + error) if error else '')
        except RuntimeError:
            pass

    def _text_rows(self, form, item):
        d = item.data
        edit = QPushButton('Edit the text')
        edit.clicked.connect(lambda: item.start_edit(select_all=False))
        form.addRow(edit)
        form.addRow(QLabel('Font, size, colour, bold, alignment and bullets: toolbar above\n'
                           '(selected words while typing, else the whole box).'))
        valign = QComboBox()
        for key, label in (('top', 'Top'), ('middle', 'Middle'), ('bottom', 'Bottom')):
            valign.addItem(label, key)
        valign.setCurrentIndex(max(0, valign.findData(d.get('valign', 'top'))))
        valign.currentIndexChanged.connect(lambda _i: self._set_prop(item, 'valign', valign.currentData()))
        form.addRow('Vertical', valign)
        form.addRow('Fill', color_button(d.get('fill_color', ''), 'Box fill', lambda c: self._set_prop(item, 'fill_color', c),
                                         allow_none=True))
        form.addRow('Border', color_button(d.get('line_color', ''), 'Border colour',
                                           lambda c: self._set_prop(item, 'line_color', c), allow_none=True))
        width = self._spin(d.get('line_width', 0), 0, 30, 0.5, 1, ' pt')
        width.valueChanged.connect(lambda v: self._set_prop(item, 'line_width', float(v)))
        form.addRow('Border width', width)
        role = QComboBox()
        for key in ('title', 'subtitle', 'body', 'caption'):
            role.addItem(key.capitalize(), key)
        role.setCurrentIndex(max(0, role.findData(d.get('role', 'body'))))
        role.setToolTip('Used by the title bar of the theme and by the assistant')
        role.currentIndexChanged.connect(lambda _i: (self._set_prop(item, 'role', role.currentData()),
                                                     self._rebuild_current()))
        form.addRow('Role', role)

    def _media_rows(self, form, item):
        d = item.data
        form.addRow(QLabel(Path(d.get('src', '')).name))
        replace = QPushButton('Replace…')
        replace.clicked.connect(lambda: self._replace_media(item))
        form.addRow(replace)
        fit = QComboBox()
        for key, label in (('contain', 'Fit inside'), ('cover', 'Fill (crop)'), ('stretch', 'Stretch')):
            fit.addItem(label, key)
        fit.setCurrentIndex(max(0, fit.findData(d.get('fit', 'contain'))))
        fit.currentIndexChanged.connect(lambda _i: self._set_prop(item, 'fit', fit.currentData()))
        form.addRow('Fit', fit)
        if d['type'] == 'video':
            for key, label in (('autoplay', 'Play automatically in the slide show'), ('loop', 'Loop'),
                               ('muted', 'Muted')):
                box = QCheckBox(label)
                box.setChecked(bool(d.get(key)))
                box.toggled.connect(lambda on, k=key: self._set_prop(item, k, bool(on)))
                form.addRow(box)
            play = QPushButton('Play / pause here')
            play.clicked.connect(item.toggle)
            form.addRow(play)
        else:
            form.addRow('Border', color_button(d.get('line_color', ''), 'Border colour',
                                               lambda c: self._set_prop(item, 'line_color', c), allow_none=True))
            width = self._spin(d.get('line_width', 0), 0, 30, 0.5, 1, ' pt')
            width.valueChanged.connect(lambda v: self._set_prop(item, 'line_width', float(v)))
            form.addRow('Border width', width)
            radius = self._spin(d.get('radius', 0), 0, 200, 1, 0, ' pt')
            radius.valueChanged.connect(lambda v: self._set_prop(item, 'radius', float(v)))
            form.addRow('Corners', radius)

    def _replace_media(self, item):
        kind = item.data['type']
        file, _ = QFileDialog.getOpenFileName(self, 'Replace', str(Path.home()), MEDIA_FILTER.get(kind, '*'))
        if file:
            item.data['src'] = deck_model.add_media(self.project_dir, Path(file))
            item.sync_from_data()
            self.commit()

    def _shape_rows(self, form, item):
        d = item.data
        kind = QComboBox()
        for key, label in (('rect', 'Rectangle'), ('rounded', 'Rounded rectangle'), ('ellipse', 'Ellipse'),
                           ('triangle', 'Triangle'), ('line', 'Line'), ('arrow', 'Arrow')):
            kind.addItem(label, key)
        kind.setCurrentIndex(max(0, kind.findData(d.get('shape', 'rect'))))
        kind.currentIndexChanged.connect(lambda _i: self._set_prop(item, 'shape', kind.currentData()))
        form.addRow('Shape', kind)
        form.addRow('Fill', color_button(d.get('fill_color', ''), 'Fill colour',
                                         lambda c: self._set_prop(item, 'fill_color', c), allow_none=True))
        form.addRow('Line', color_button(d.get('line_color', ''), 'Line colour',
                                         lambda c: self._set_prop(item, 'line_color', c), allow_none=True))
        width = self._spin(d.get('line_width', 0), 0, 40, 0.5, 1, ' pt')
        width.valueChanged.connect(lambda v: self._set_prop(item, 'line_width', float(v)))
        form.addRow('Line width', width)
        radius = self._spin(d.get('radius', 12), 0, 300, 1, 0, ' pt')
        radius.valueChanged.connect(lambda v: self._set_prop(item, 'radius', float(v)))
        form.addRow('Corner radius', radius)
        text = QLineEdit(deck_model.plain_text(d.get('html', '')))
        text.setPlaceholderText('Text inside the shape')
        text.editingFinished.connect(lambda: self._set_prop(item, 'html', deck_model.text_html(
            text.text(), size=float(self._theme().get('body_size', 20)) * 0.8, color='#FFFFFF' if d.get('fill_color') else
            self._theme().get('text_color', '#1A1D22'), font=self._theme().get('body_font', 'Inter'), align='center')
            if text.text().strip() else ''))
        form.addRow('Text', text)

    def _build_slide_page(self):
        form = self._clear_page(self.slide_page)
        slide = self.current_slide()
        self._section(form, f'Slide {self.index + 1}')
        layout = QComboBox()
        for key, label in deck_model.LAYOUTS.items():
            layout.addItem(label, key)
        layout.setCurrentIndex(max(0, layout.findData(slide.get('layout', 'blank'))))
        form.addRow('Layout', layout)
        reset = QPushButton('Apply this layout (replaces the slide content)')
        reset.clicked.connect(lambda: self._reset_layout(layout.currentData()))
        form.addRow(reset)
        form.addRow('Background', color_button(slide.get('background_color', ''), 'Slide background (empty = theme)',
                                               lambda c: self._slide_prop('background_color', c), allow_none=True))
        row = QHBoxLayout()
        pick = QPushButton('Picture…')
        pick.clicked.connect(lambda: self._background_image(slide=True))
        clear = QPushButton('None')
        clear.clicked.connect(lambda: self._slide_prop('background_image', ''))
        row.addWidget(pick)
        row.addWidget(clear)
        holder = QWidget()
        holder.setLayout(row)
        form.addRow('Background picture', holder)
        transition = QComboBox()
        for key, label in (('none', 'None'), ('fade', 'Fade'), ('push', 'Push')):
            transition.addItem(label, key)
        transition.setCurrentIndex(max(0, transition.findData(slide.get('transition', 'none'))))
        transition.currentIndexChanged.connect(lambda _i: self._slide_prop('transition', transition.currentData()))
        form.addRow('Transition', transition)
        hidden = QCheckBox('Hide in the slide show')
        hidden.setChecked(bool(slide.get('hidden')))
        hidden.toggled.connect(self._toggle_hidden)
        form.addRow(hidden)

    def _slide_prop(self, key, value):
        self.current_slide()[key] = value
        self.commit()
        self._rebuild_current()

    def _reset_layout(self, layout):
        if self.current_slide()['items'] and not MessageDialog.confirm(
                self, 'Apply layout', 'Replace everything on this slide by the layout placeholders?', 'Replace'):
            return
        fresh = deck_model.new_slide(layout, self._theme(), self.slide_size())
        self.current_slide()['layout'] = layout
        self.current_slide()['items'] = fresh['items']
        self.commit()
        self._rebuild_current()

    def _background_image(self, slide=True):
        file, _ = QFileDialog.getOpenFileName(self, 'Background picture', str(Path.home()), MEDIA_FILTER['image'])
        if not file:
            return
        rel = deck_model.add_media(self.project_dir, Path(file))
        if slide:
            self._slide_prop('background_image', rel)
        else:
            self._theme_prop('background_image', rel)

    def _build_design_page(self):
        form = self._clear_page(self.design_page)
        t = self._theme()
        self._section(form, 'Theme')
        for key, label in (('background_color', 'Background'), ('text_color', 'Text'), ('muted_color', 'Secondary text'),
                           ('accent_color', 'Accent')):
            form.addRow(label, color_button(t.get(key, '#000000'), label + ' colour',
                                            lambda c, k=key: self._theme_prop(k, c or '#FFFFFF')))
        for key, label in (('title_font', 'Title font'), ('body_font', 'Text font')):
            box = QFontComboBox()
            box.setCurrentFont(QFont(t.get(key, 'Inter')))
            box.currentFontChanged.connect(lambda f, k=key: self._theme_prop(k, f.family()))
            form.addRow(label, box)
        for key, label in (('title_size', 'Title size'), ('body_size', 'Text size')):
            spin = self._spin(t.get(key, 20), 8, 120, 1, 0, ' pt')
            spin.valueChanged.connect(lambda v, k=key: self._theme_prop(k, float(v)))
            form.addRow(label, spin)
        bar = QCheckBox('Coloured band behind slide titles')
        bar.setChecked(bool(t.get('title_bar')))
        bar.toggled.connect(lambda on: self._theme_prop('title_bar', bool(on)))
        form.addRow(bar)
        form.addRow('Band colour', color_button(t.get('title_bar_color', '#0F7C6F'), 'Title band colour',
                                                lambda c: self._theme_prop('title_bar_color', c or '#0F7C6F')))
        footer = QLineEdit(t.get('footer', ''))
        footer.setPlaceholderText('Text at the bottom of every slide')
        footer.editingFinished.connect(lambda: self._theme_prop('footer', footer.text()))
        form.addRow('Footer', footer)
        numbers = QCheckBox('Slide numbers')
        numbers.setChecked(bool(t.get('slide_numbers', True)))
        numbers.toggled.connect(lambda on: self._theme_prop('slide_numbers', bool(on)))
        form.addRow(numbers)
        row = QHBoxLayout()
        pick = QPushButton('Picture…')
        pick.clicked.connect(lambda: self._background_image(slide=False))
        clear = QPushButton('None')
        clear.clicked.connect(lambda: self._theme_prop('background_image', ''))
        row.addWidget(pick)
        row.addWidget(clear)
        holder = QWidget()
        holder.setLayout(row)
        form.addRow('Background picture', holder)
        size = QComboBox()
        for key in doc_settings.SLIDE_SIZES:
            size.addItem(key, key)
        size.setCurrentIndex(max(0, size.findData(self.deck.get('size', '16:9'))))
        size.currentIndexChanged.connect(lambda _i: self._set_size(size.currentData()))
        form.addRow('Slide size', size)
        self._section(form, 'LaTeX boxes')
        preamble = QPlainTextEdit(self.deck.get('formula_preamble', '') or self.conf.get('formula_preamble', ''))
        preamble.setMaximumHeight(90)
        preamble.setToolTip('\\usepackage lines used by every LaTeX box of this presentation')
        apply = QPushButton('Apply packages')
        apply.clicked.connect(lambda: self._set_preamble(preamble.toPlainText()))
        form.addRow(QLabel('Packages (preamble)'))
        form.addRow(preamble)
        form.addRow(apply)
        self._section(form, 'Templates')
        b = QPushButton('Apply a template…')
        b.clicked.connect(self._apply_template)
        form.addRow(b)
        b = QPushButton('Save as template…')
        b.clicked.connect(self._save_as_template)
        form.addRow(b)

    def _theme_prop(self, key, value):
        old = dict(self._theme())
        self._theme()[key] = value
        if key in ('text_color', 'title_font', 'body_font', 'accent_color'):
            self._retheme(old, self._theme())
        self.commit()
        self._rebuild_current()
        self.refresh_thumbs()

    def _retheme(self, old, new):
        """Text written with the old theme colours / fonts follows the new theme."""
        pairs = []
        for key in ('text_color', 'muted_color', 'accent_color'):
            if old.get(key) and new.get(key) and old[key].lower() != new[key].lower():
                pairs.append((old[key], new[key]))
        for key in ('title_font', 'body_font'):
            if old.get(key) and new.get(key) and old[key] != new[key]:
                pairs.append((f"'{old[key]}'", f"'{new[key]}'"))
        if not pairs:
            return
        import re as _re
        for slide in self.slides():
            for item in slide['items']:
                for field in ('html',):
                    if item.get(field):
                        text = item[field]
                        for a, b in pairs:
                            text = _re.sub(_re.escape(a), b, text, flags=_re.I)
                        item[field] = text
                if item.get('type') == 'latex' and item.get('color', '').lower() == old.get('text_color', '').lower():
                    item['color'] = new.get('text_color', item['color'])

    def _set_size(self, size):
        w, h = deck_model.slide_size(size)
        self.deck.update({'size': size, 'width': w, 'height': h})
        self.commit()
        self._rebuild_current()
        self.refresh_thumbs()

    def _set_preamble(self, text):
        self.deck['formula_preamble'] = text
        self.commit()
        self._rebuild_current()
        self.refresh_thumbs()

    # ================================================================== files
    def save(self) -> bool:
        self._finish_text_edits()
        self.commit()
        try:
            deck_model.save(self.deck, self.deck_path)
        except (OSError, ValueError) as exc:
            MessageDialog.warning(self, 'Not saved', str(exc))
            return False
        self._dirty = False
        self._set_title()
        self.statusBar().showMessage('Saved', 2000)
        return True

    def _autosave(self):
        if self._dirty:
            self.save()

    def _open(self):
        file, _ = QFileDialog.getOpenFileName(self, 'Open presentation', str(doc_settings.slides_root()),
                                              f'Presentations (*{deck_model.SUFFIX})')
        if file and self.hub:
            self.hub.open_slides(file)

    def _import_pptx(self):
        file, _ = QFileDialog.getOpenFileName(self, 'Import PowerPoint', str(Path.home()), 'PowerPoint (*.pptx)')
        if not file:
            return
        from .pptx_io import import_pptx
        try:
            path = import_pptx(file, doc_settings.slides_root())
        except Exception as exc:
            MessageDialog.warning(self, 'Import PowerPoint', str(exc))
            return
        if self.hub:
            self.hub.open_slides(path)

    def _switch_to(self, path):
        self.deck_path = Path(path)
        self.project_dir = self.deck_path.parent
        self.ctx.project_dir = self.project_dir
        self.deck.clear()
        self.deck.update(deck_model.load(self.deck_path))
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._state = self._serialise()
        self._dirty = False
        self._set_title()
        doc_settings.add_recent('slides', self.deck_path)
        self.index = 0
        self.refresh_thumbs()
        self.show_slide(0)
        self._build_design_page()

    def _save_as(self):
        self.save()
        parent = QFileDialog.getExistingDirectory(self, 'Save the presentation as… (choose where)',
                                                  str(self.project_dir.parent))
        if not parent:
            return
        name, ok = TextInputDialog.getText(self, 'Save as', 'Name:', text=self.title() + ' copy')
        if ok and name.strip():
            self._switch_to(deck_model.copy_project(self.deck_path, parent, name.strip()))

    def _rename(self):
        name, ok = TextInputDialog.getText(self, 'Rename', 'Title of the presentation:', text=self.title())
        if ok and name.strip():
            self.deck['title'] = name.strip()
            self.commit()
            self._set_title()

    def _save_as_template(self):
        name, ok = TextInputDialog.getText(self, 'Save as template', 'Template name:', text=self.title())
        if not ok or not name.strip():
            return
        slides = MessageDialog.question(self, 'Save as template', 'Keep the slides as starter slides of the template? '
                                        '(No: only the theme and size.)') == MessageDialog.StandardButton.Yes
        try:
            target = templates.save_slides_template(self.deck, name.strip(), include_slides=slides,
                                                    media_root=self.project_dir)
        except (OSError, ValueError) as exc:
            MessageDialog.warning(self, 'Save as template', str(exc))
            return
        MessageDialog.information(self, 'Template saved', f'“{name}” is now in the template list.\n\n{target}')

    def _apply_template(self):
        items = templates.list_templates('slides')
        if not items:
            return
        labels = [t.label for t in items]
        chosen, ok = TextInputDialog.getItem(self, 'Apply a template', 'Theme of:', labels, 0, False)
        if not ok:
            return
        template = templates.load_slides_template(items[labels.index(chosen)].path)
        old = dict(self._theme())
        self._theme().update(template.get('theme', {}))
        self._retheme(old, self._theme())
        self.commit()
        self._rebuild_current()
        self.refresh_thumbs()
        self._build_design_page()

    def _export_zip(self):
        self.save()
        destination, _ = QFileDialog.getSaveFileName(self, 'Export as .zip', str(Path.home() / f'{self.title()}.zip'),
                                                     'Zip archive (*.zip)')
        if destination:
            deck_model.export_zip(self.deck_path, destination)
            self.statusBar().showMessage(f'Saved {destination}', 4000)

    def _prepare_formulas(self):
        """Render every LaTeX box before an export (waits for TeX, at most a few seconds each)."""
        for slide in self.slides():
            for item in slide['items']:
                if item['type'] == 'latex':
                    self.renderer.render_blocking(item.get('source', ''), item.get('color', '#000000'),
                                                  float(item['w']) / max(0.1, float(item.get('size', 24)) / 10.0),
                                                  item.get('align', 'center'), self.deck.get('formula_preamble', ''))

    def export_pdf(self, destination=None):
        if destination is None:
            destination, _ = QFileDialog.getSaveFileName(self, 'Export as PDF', str(self.project_dir / f'{self.title()}.pdf'),
                                                         'PDF (*.pdf)')
            if not destination:
                return None
        from PySide6.QtGui import QPdfWriter, QPageSize, QPageLayout
        self._finish_text_edits()
        self._prepare_formulas()
        w, h = self.slide_size()
        writer = QPdfWriter(str(destination))
        writer.setResolution(300)
        writer.setPageSize(QPageSize(QSizeF(w, h), QPageSize.Unit.Point, 'slide', QPageSize.SizeMatchPolicy.ExactMatch))
        writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Point)
        writer.setTitle(self.title())
        writer.setCreator('SPM Studio')
        painter = QPainter(writer)
        try:
            first = True
            for index, slide in enumerate(self.slides()):
                if slide.get('hidden'):
                    continue
                if not first:
                    writer.newPage()
                first = False
                paint_slide(painter, QRectF(0, 0, writer.width(), writer.height()), self.deck, index,
                            self.project_dir, self.renderer)
        finally:
            painter.end()
        self.statusBar().showMessage(f'Exported {destination}', 5000)
        return Path(destination)

    def export_png(self):
        folder = QFileDialog.getExistingDirectory(self, 'Folder for the slide images', str(self.project_dir))
        if not folder:
            return
        self._prepare_formulas()
        for index in range(len(self.slides())):
            render_slide(self.deck, index, self.project_dir, 1920, self.renderer).save(
                str(Path(folder) / f'{self.project_dir.name}_slide_{index + 1:02d}.png'))
        self.statusBar().showMessage(f'{len(self.slides())} images saved in {folder}', 5000)

    def export_pptx(self, destination=None):
        from .pptx_io import export_pptx, PptxUnavailable
        if destination is None:
            destination, _ = QFileDialog.getSaveFileName(self, 'Export as PowerPoint',
                                                         str(self.project_dir / f'{self.title()}.pptx'),
                                                         'PowerPoint (*.pptx)')
            if not destination:
                return None
        self._finish_text_edits()
        self._prepare_formulas()
        temp = self.project_dir / '.spm_render' / 'pptx'
        temp.mkdir(parents=True, exist_ok=True)

        def rasterize(item):
            out = temp / f'{item["id"]}.png'
            if item['type'] == 'latex':
                scale = max(0.1, float(item.get('size', 24)) / 10.0)
                result = self.renderer.render_blocking(item.get('source', ''), item.get('color', '#000000'),
                                                       float(item['w']) / scale, item.get('align', 'center'),
                                                       self.deck.get('formula_preamble', ''))
                if result is None:
                    return None
                result[0].save(str(out))
                return out
            if item['type'] == 'image':
                svg_to_image(self.project_dir / item['src'], 2400).save(str(out))
                return out
            return None
        try:
            path = export_pptx(self.deck, self.project_dir, destination, rasterize)
        except PptxUnavailable as exc:
            MessageDialog.warning(self, 'PowerPoint', str(exc))
            return None
        except Exception as exc:
            MessageDialog.warning(self, 'PowerPoint', f'Export failed: {exc}')
            return None
        self.statusBar().showMessage(f'Exported {path}', 5000)
        return path

    def present(self, start=0):
        from .slideshow import SlideShow
        self._finish_text_edits()
        self.commit()
        self._slideshow = SlideShow(self.deck, self.project_dir, start, self.renderer)
        self._slideshow.start()

    def _export_from_scan(self, mode):
        main = getattr(self.hub, 'main_window', None) if self.hub else None
        if main is None:
            return
        if getattr(main, 'scan', None) is None:
            MessageDialog.information(self, 'No scan', 'Open a scan in the SPM Studio window first.')
            return
        main.raise_()
        main.activateWindow()
        main.export_current(targets={'slides': self, 'slides_mode': mode})

    # ================================================================== assistant
    def ai_state(self) -> str:
        return (f'Presentation “{self.title()}” ({self.deck_path}), slide {self.index + 1} of {len(self.slides())}, '
                f'{self.deck["size"]}')

    def _slide_index(self, value) -> int:
        if value in (None, 'current'):
            return self.index
        if value == 'last':
            return len(self.slides()) - 1
        if value == 'new':
            self.new_slide('blank')
            return self.index
        index = int(value) - 1
        if not 0 <= index < len(self.slides()):
            raise ValueError(f'There is no slide {value} (the presentation has {len(self.slides())})')
        return index

    def _go(self, index):
        if index != self.index:
            self.show_slide(index)

    def ai_action(self, r) -> str:
        action = r['action']
        if action == 'read':
            outline = deck_model.outline(self.deck)
            return json.dumps({'title': self.title(), 'file': str(self.deck_path), 'size': self.deck['size'],
                               'width_pt': self.deck['width'], 'height_pt': self.deck['height'],
                               'current_slide': self.index + 1, 'theme': self._theme(), 'slides': outline},
                              ensure_ascii=False, indent=1)[:60000]
        if action == 'add_slide':
            after = r.get('after')
            slide = self.new_slide(r.get('layout', 'title_content'), title=r.get('title', ''), body=r.get('body'),
                                   after=after if after is None else int(after))
            if r.get('notes'):
                slide['notes'] = r['notes']
                self.notes.setPlainText(r['notes'])
            self.commit()
            return f'Added slide {self.index + 1} ({slide["layout"]})'
        if action == 'go_to':
            self._go(self._slide_index(r.get('slide')))
            return f'Showing slide {self.index + 1}'
        if action == 'set_theme':
            for key in ('background_color', 'text_color', 'accent_color', 'title_font', 'body_font', 'title_size',
                        'body_size'):
                if key in r:
                    self._theme_prop(key, r[key])
            self._build_design_page()
            return 'Theme updated'
        if action == 'delete_slide':
            index = self._slide_index(r.get('slide'))
            self.delete_slide(index)
            return f'Deleted slide {index + 1}'
        index = self._slide_index(r.get('slide'))
        self._go(index)
        slide = self.current_slide()
        t = self._theme()
        if action == 'add_text':
            data = self.add_text(r.get('text', ''), r.get('x', 48.0), r.get('y', 140.0), r.get('w', self.slide_size()[0] - 96),
                                 r.get('h', 80.0), r.get('size'), r.get('color'), bool(r.get('bold')))
            return f'Added text box {data["id"]} on slide {index + 1}'
        if action == 'add_latex':
            data = self.add_latex(r.get('source', ''), r.get('x', 48.0), r.get('y', 160.0),
                                  r.get('w', self.slide_size()[0] - 96), r.get('h', 80.0), r.get('size', 28.0), r.get('color'))
            return f'Added LaTeX box {data["id"]} on slide {index + 1} (rendering automatically)'
        if action == 'add_shape':
            data = self.add_shape(r.get('shape', 'rect'), r.get('x'), r.get('y'), r.get('w'), r.get('h'),
                                  r.get('fill_color'))
            return f'Added shape {data["id"]} on slide {index + 1}'
        if action == 'set_notes':
            slide['notes'] = r.get('notes', '')
            self.notes.setPlainText(slide['notes'])
            self.commit()
            return f'Notes of slide {index + 1} updated'
        target = next((i for i in slide['items'] if i['id'] == r.get('item')), None)
        if target is None:
            raise ValueError(f'No item {r.get("item")!r} on slide {index + 1} (use read to see the ids)')
        if action == 'delete_item':
            slide['items'].remove(target)
            self.commit()
            self._rebuild_current()
            return f'Deleted item {target["id"]}'
        if action == 'update_item':
            for key in ('x', 'y', 'w', 'h', 'rotation', 'opacity', 'line_width'):
                if key in r:
                    target[key] = float(r[key])
            if 'source' in r and target['type'] == 'latex':
                target['source'] = r['source']
            if 'size' in r and target['type'] == 'latex':
                target['size'] = float(r['size'])
            if 'color' in r and target['type'] == 'latex':
                target['color'] = r['color']
            for key in ('fill_color', 'line_color', 'shape'):
                if key in r:
                    target[key] = r[key]
            if 'text' in r and target['type'] in ('text', 'shape'):
                size = r.get('size') or (t.get('title_size', 34) if target.get('role') == 'title' else t.get('body_size', 20))
                target['html'] = deck_model.text_html(r['text'], size=float(size), color=r.get('color') or t.get('text_color'),
                                                      font=t.get('title_font' if target.get('role') == 'title' else 'body_font'),
                                                      bold=bool(r.get('bold', target.get('role') == 'title')),
                                                      align=r.get('align', 'left'))
            self.commit()
            self._rebuild_current()
            return f'Updated item {target["id"]}'
        raise ValueError(f'Unknown action {action}')

    # ================================================================== window
    def changeEvent(self, event):
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow() and self.hub is not None:
            self.hub.note_active(self)
        super().changeEvent(event)

    def closeEvent(self, event):
        self._finish_text_edits()
        self.commit()
        if self._dirty:
            if self.conf.get('slides_autosave', True):
                if not self.save():
                    event.ignore()
                    return
            else:
                answer = MessageDialog.question(self, 'Unsaved changes', 'Save the presentation?',
                                                MessageDialog.StandardButton.Save | MessageDialog.StandardButton.Discard |
                                                MessageDialog.StandardButton.Cancel)
                if answer == MessageDialog.StandardButton.Cancel or (
                        answer == MessageDialog.StandardButton.Save and not self.save()):
                    event.ignore()
                    return
        for item in self.scene.graphics.values():
            if hasattr(item, 'stop'):
                item.stop()
        QSettings('SPM Studio', 'Documents').setValue('slides_geometry', self.saveGeometry())
        if self.hub is not None:
            self.hub.unregister(self)
        event.accept()
