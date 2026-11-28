"""Standalone Agent Hub (no host application): ``agent-hub`` / ``python -m agent_hub``."""
from __future__ import annotations

import argparse
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='agent-hub', description='Agent Hub — AI assistant')
    parser.add_argument('--data', help='data folder (default: the per-user Agent Hub folder)')
    parser.add_argument('--version', action='store_true')
    args, qt_args = parser.parse_known_args(argv if argv is not None else sys.argv[1:])
    from . import __version__
    if args.version:
        print('agent-hub', __version__)
        return 0
    import os
    if args.data:
        os.environ['AGENT_HUB_DATA'] = args.data
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([sys.argv[0], *qt_args])
    app.setApplicationName('Agent Hub')
    app.setOrganizationName('SPM Studio')
    app.setDesktopFileName('agent-hub')
    from .host import current
    from .instance import InstanceGuard
    guard = InstanceGuard(current().data_dir())
    if not guard.acquire():
        if guard.ask_owner_to_show():
            return 0
        QMessageBox.information(None, 'Agent Hub', 'Agent Hub is already open in another program (for example '
                                'SPM Studio) and owns the chats. Open it there, or close it and start again.')
        return 1
    from .core import HubCore
    from .ui import theme
    from .ui.onboarding import maybe_run
    from .ui.window import HubWindow
    core = HubCore()
    theme.set_standalone(core.conf.get('standalone_theme', 'light'))
    window = HubWindow(core)
    guard.activateRequested.connect(lambda: (window.showNormal(), window.raise_(), window.activateWindow()))
    window.show()
    from PySide6.QtCore import QTimer
    QTimer.singleShot(300, lambda: maybe_run(core, window.hub))
    code = app.exec()
    guard.release()
    return code


if __name__ == '__main__':
    sys.exit(main())
