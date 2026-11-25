"""Qt side of the guided tutorial: manager, callout, highlight, welcome panel.

* Esc ends the lesson at once, from anywhere (main window, a dialog, a combo box popup); the key still reaches
  the dialog so it closes as usual. Every overlay, filter and timer is released.
* Steps with an expected action unlock **Next** only when the real application state says it is done.
* The highlight is drawn *on top* of the target's window and lets every click through; nothing is clicked or
  typed for the user.
* Extensions may decorate the callout (``add_decorator``); the tour is complete without any.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout,
                               QWidget)

from . import course as course_mod
from . import state

SKIP_TEXT = 'La science n’attend pas !'


def _accent() -> QColor:
    color = QApplication.palette().highlight().color()
    return color if color.isValid() else QColor('#2f80ed')


class Highlight(QWidget):
    """Dims the target's window outside the target and rings the target; transparent for the mouse."""

    def __init__(self, host: QWidget, dim: bool = True):
        super().__init__(host)
        self.setObjectName('TutorialHighlightV0013')
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.dim = dim
        self.hole = QRect()

    def place(self, target: QWidget | None):
        host = self.parentWidget()
        self.setGeometry(host.rect())
        if target is not None and target.isVisible():
            top_left = target.mapTo(host, QPoint(0, 0))
            self.hole = QRect(top_left, target.size()).adjusted(-6, -6, 6, 6)
        else:
            self.hole = QRect()
        self.raise_()
        self.show()
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.dim:
            path = QPainterPath()
            path.addRect(self.rect().toRectF())
            if not self.hole.isNull():
                hole = QPainterPath()
                hole.addRoundedRect(self.hole.toRectF(), 8, 8)
                path = path.subtracted(hole)
            painter.fillPath(path, QColor(0, 0, 0, 70))
        if not self.hole.isNull():
            painter.setPen(QPen(_accent(), 3))
            painter.drawRoundedRect(self.hole, 8, 8)


class Callout(QFrame):
    """The speech bubble: step title, text, progress, Back / Skip step / Next / Exit."""
    back = Signal()
    skip = Signal()
    next = Signal()
    exit = Signal()
    extra = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setObjectName('TutorialCalloutV0013')
        self.setAccessibleName('Guided tutorial')
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFixedWidth(400)
        self.setStyleSheet('#TutorialCalloutV0013 { border: 2px solid palette(highlight); border-radius: 10px; }')
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        self.decoration = QHBoxLayout()          # extensions may add an avatar here
        self.decoration.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        head.addLayout(self.decoration)
        self.title = QLabel()
        self.title.setObjectName('heading')
        self.title.setWordWrap(True)
        head.addWidget(self.title, 1)
        self.step_label = QLabel()
        self.step_label.setObjectName('muted')
        head.addWidget(self.step_label)
        root.addLayout(head)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.text)
        self.todo = QLabel()
        self.todo.setObjectName('muted')
        self.todo.setWordWrap(True)
        root.addWidget(self.todo)
        self.extra_button = QPushButton()
        self.extra_button.setObjectName('TutorialActionButtonV0013')
        self.extra_button.setProperty('primary', True)
        self.extra_button.clicked.connect(self.extra)
        root.addWidget(self.extra_button)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(5)
        root.addWidget(self.progress)
        row = QHBoxLayout()
        self.back_button = QPushButton('Back')
        self.skip_button = QPushButton('Skip step')
        self.next_button = QPushButton('Next')
        self.next_button.setProperty('primary', True)
        self.exit_button = QPushButton('Exit (Esc)')
        for name, button, signal in (('Back', self.back_button, self.back), ('Skip', self.skip_button, self.skip),
                                     ('Next', self.next_button, self.next), ('Exit', self.exit_button, self.exit)):
            button.setObjectName(f'Tutorial{name}V0013')
            button.clicked.connect(signal)
        row.addWidget(self.exit_button)
        row.addStretch(1)
        row.addWidget(self.back_button)
        row.addWidget(self.skip_button)
        row.addWidget(self.next_button)
        root.addLayout(row)

    def show_step(self, step: course_mod.Step, index: int, total: int, done: bool, last: bool):
        self.title.setText(step.title)
        self.step_label.setText(f'Step {index + 1} / {total}')
        self.text.setText(step.text)
        if step.action:
            self.todo.setText(('✓ Done: ' if done else '➜ To do: ') + step.action)
        self.todo.setVisible(bool(step.action))
        self.extra_button.setVisible(step.button is not None)
        if step.button:
            self.extra_button.setText(step.button[0])
        self.progress.setRange(0, total)
        self.progress.setValue(index + (1 if done or not step.action else 0))
        self.back_button.setEnabled(index > 0)
        self.skip_button.setVisible(bool(step.action) and not done)
        self.next_button.setEnabled(done or not step.action)
        self.next_button.setText('Finish' if last else 'Next')
        self.setAccessibleDescription(f'{step.title}. {step.text}')
        self.adjustSize()

    def place_near(self, target: QWidget | None, fallback: QWidget):
        """Beside the target, never over it, kept on its screen."""
        self.adjustSize()
        anchor = target if target is not None and target.isVisible() else fallback
        rect = QRect(anchor.mapToGlobal(QPoint(0, 0)), anchor.size())
        screen = (anchor.screen() or QApplication.primaryScreen()).availableGeometry()
        w, h = self.width(), self.height()
        if anchor is fallback:
            pos = QPoint(rect.right() - w - 24, rect.bottom() - h - 24)
        else:
            candidates = [QPoint(rect.right() + 14, rect.top()), QPoint(rect.left() - w - 14, rect.top()),
                          QPoint(rect.left(), rect.bottom() + 14), QPoint(rect.left(), rect.top() - h - 14)]
            pos = next((p for p in candidates if screen.contains(QRect(p, self.size()))), candidates[0])
        pos.setX(max(screen.left() + 8, min(pos.x(), screen.right() - w - 8)))
        pos.setY(max(screen.top() + 8, min(pos.y(), screen.bottom() - h - 8)))
        self.move(pos)


class TutorialManager(QObject):
    """Runs one course on the main window. ``start()`` / ``stop()``; Esc always stops."""
    finished = Signal(str)          # 'completed' | 'exited' | 'escape'
    stepChanged = Signal(int)

    def __init__(self, window, decorators=None):
        super().__init__(window)
        self.window = window
        self.decorators = decorators if decorators is not None else []
        self.steps: list[course_mod.Step] = []
        self.kind = 'basics'
        self.index = -1
        self.done = False
        self.ctx: course_mod.Context | None = None
        self.callout: Callout | None = None
        self.highlight: Highlight | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._poll)

    # ---------------------------------------------------------------- lifecycle
    @property
    def active(self) -> bool:
        return self.callout is not None

    def start(self, steps=None, position: int = 0, kind: str = 'basics'):
        self.stop('restart', emit=False)
        self.kind = kind
        self.steps = list(steps if steps is not None else course_mod.basics())
        self.callout = Callout(self.window)
        self.callout.back.connect(lambda: self.go(self.index - 1))
        self.callout.skip.connect(lambda: self.go(self.index + 1))
        self.callout.next.connect(self._next)
        self.callout.exit.connect(lambda: self.stop('exited'))
        self.callout.extra.connect(self._extra)
        for decorate in list(self.decorators):
            try:
                decorate(self.callout, self)
            except Exception as exc:                       # an extension must never break the tour
                self._log(f'Tutorial decoration failed: {exc}')
        QApplication.instance().installEventFilter(self)
        if kind == 'basics':
            state.update(started=True, skipped=False, welcome_shown=True)
        self._timer.start()
        self.go(max(0, min(position, len(self.steps) - 1)))

    def stop(self, reason: str = 'exited', emit: bool = True):
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._timer.stop()
        for widget in (self.callout, self.highlight):
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        was_active = self.callout is not None
        self.callout = self.highlight = None
        if was_active and self.kind == 'basics' and reason != 'completed' and 0 <= self.index < len(self.steps):
            state.update(resume_position=self.index)
        self.index = -1
        if was_active and emit:
            self.finished.emit(reason)

    # ---------------------------------------------------------------- navigation
    def go(self, index: int):
        if not self.steps:
            return
        if index >= len(self.steps):
            return self._complete()
        self.index = max(0, index)
        step = self.steps[self.index]
        self.ctx = course_mod.Context(self.window, started=time.time(), visible_window_types=self._window_types)
        if step.setup:
            try:
                step.setup(self.ctx)
            except Exception as exc:
                self._log(f'Tutorial step setup failed: {exc}')
        self.done = self._check(step)
        if self.kind == 'basics':
            state.update(resume_position=self.index)
        self._render()
        self.stepChanged.emit(self.index)

    def _next(self):
        step = self.steps[self.index]
        if step.action and not self.done:
            return                                  # a real action is expected: Next alone does not count
        self.go(self.index + 1)

    def _complete(self):
        if self.kind == 'basics':
            state.update(completed=True, resume_position=0)
        elif self.kind == 'whats_new':
            from spm_studio.core.updates import current_version
            state.update(whats_new_seen=current_version())
        self.stop('completed')

    def _extra(self):
        step = self.steps[self.index]
        if not step.button:
            return
        method = getattr(self.window, step.button[1], None)
        if callable(method):
            method()

    # ---------------------------------------------------------------- state
    def _check(self, step) -> bool:
        if not step.check:
            return False
        try:
            return bool(step.check(self.ctx))
        except Exception:
            return False

    def _poll(self):
        if self.callout is None or not (0 <= self.index < len(self.steps)):
            return
        step = self.steps[self.index]
        if step.action and not self.done and self._check(step):
            self.done = True
            self._render()
        else:
            self._place()                            # follow moves, resizes, scale changes, vanished targets

    def _target(self):
        step = self.steps[self.index]
        widget = course_mod.resolve(self.window, step.target) if step.target else None
        return widget if isinstance(widget, QWidget) else None

    def _render(self):
        step = self.steps[self.index]
        self.callout.show_step(step, self.index, len(self.steps), self.done, self.index == len(self.steps) - 1)
        self._place()
        self.callout.show()

    def _place(self):
        target = self._target()
        host = target.window() if target is not None else self.window
        if self.highlight is None or self.highlight.parentWidget() is not host:
            if self.highlight is not None:
                self.highlight.deleteLater()
            self.highlight = Highlight(host, dim=host is self.window)
        self.highlight.place(target)
        self.callout.place_near(target, self.window)

    @staticmethod
    def _window_types() -> set:
        return {type(w).__name__ for w in QApplication.topLevelWidgets() if w.isVisible()}

    def _log(self, text):
        try:
            self.window._log(text)
        except Exception:
            pass

    # ---------------------------------------------------------------- Esc from anywhere
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape and self.callout is not None:
            QTimer.singleShot(0, lambda: self.stop('escape'))
        return False                                 # the key still closes the dialog / popup it was meant for


class WelcomePanel(QFrame):
    """Non-blocking first-run card in the corner of the main window."""
    start = Signal()
    skip = Signal()
    whats_new = Signal()

    def __init__(self, window, offer_whats_new: bool = False):
        super().__init__(window)
        self.setObjectName('TutorialWelcomeV0013')
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet('#TutorialWelcomeV0013 { border: 2px solid palette(highlight); border-radius: 12px;'
                           ' background: palette(window); }')
        self.setFixedWidth(380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        title = QLabel('Welcome to SPM Studio')
        title.setObjectName('heading')
        layout.addWidget(title)
        text = QLabel('A 10-minute guided tour on three real KBr(001) scans: open, inspect, apply a profile, '
                      'use a tool, export. It works offline and changes none of your data. Esc ends it at any time.')
        text.setWordWrap(True)
        layout.addWidget(text)
        row = QHBoxLayout()
        go = QPushButton('Start guided tutorial')
        go.setObjectName('TutorialStartV0013')
        go.setProperty('primary', True)
        go.clicked.connect(self.start)
        later = QPushButton(SKIP_TEXT)
        later.setObjectName('TutorialSkipWelcomeV0013')
        later.clicked.connect(self.skip)
        row.addWidget(go)
        row.addWidget(later)
        layout.addLayout(row)
        if offer_whats_new:
            news = QPushButton('What’s new in this update?')
            news.setObjectName('TutorialWhatsNewV0013')
            news.setFlat(True)
            news.clicked.connect(self.whats_new)
            layout.addWidget(news)
        self.adjustSize()

    def place(self):
        parent = self.parentWidget()
        self.adjustSize()
        self.move(parent.width() - self.width() - 24, parent.height() - self.height() - 48)
        self.raise_()


def whats_new_steps(version: str) -> list[course_mod.Step]:
    from spm_studio.core import paths
    try:
        text = (paths.bundled_studio_root() / 'CHANGELOG.md').read_text(encoding='utf8')
    except OSError:
        text = ''
    targets = {'tutorial': 'settings_button', 'update': 'settings_button', 'beta': 'settings_button',
               'to-do': 'todo_button', 'assistant': 'ai_toolbar_button', 'export': 'export_tool',
               'project': 'folder_button', 'compare': 'compare_tool', 'settings': 'settings_button',
               'theme': 'settings_button', 'scan list': 'browser.files'}
    steps = []
    for page in state.whats_new_pages(text, version):
        target = next((t for key, t in targets.items() if key in page['title'].lower()), '')
        steps.append(course_mod.Step('news', page['title'], page['text'] or page['title'], target=target))
    return steps
