"""Small Qt shell; scientific work is delegated to pure services and subprocess modules."""
from __future__ import annotations
from dataclasses import asdict, replace
from pathlib import Path
import json, os, shutil, sys, time, uuid, subprocess
from datetime import datetime
import numpy as np
from PySide6.QtCore import (Qt, QEvent, QTimer, QThreadPool, QThread, QProcess, QProcessEnvironment,
                           Signal, QSettings, QUrl, Slot, QFileSystemWatcher)
from PySide6.QtGui import QAction, QKeySequence, QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (QMainWindow,QCheckBox,QWidget,QVBoxLayout,QHBoxLayout,QSplitter,QTabWidget,
    QScrollArea,QDockWidget,QFileDialog,QMessageBox,QInputDialog,QPushButton,QListWidgetItem,QToolBar,QComboBox,QLabel,QApplication,QSizePolicy,QLineEdit,QTextEdit,QPlainTextEdit,QAbstractSpinBox)
from spm_studio.shared.dialogs import MessageDialog as QMessageBox, TextInputDialog as QInputDialog
from ..core.io import read_scan, discover
from ..core.models import ImageStyle, ProcessingStep, ROI, Channel, Geometry, Scan
from ..core.processing import apply, display_zero_enabled
from ..core.display import render_rgb, bounds, preview_bounds
from ..core.painting import qimage_rgb
from ..core.cache import ArrayCache
from ..core import paths
from ..core.plot_settings import available_styles, DEFAULT_PLOT, ensure_bundled_styles, display_cmap
from .plot_options import PlotOptions
from ..core.registry import discover_modules,validate_params
from ..core.module_api import select_snapshot_arrays
from ..core.presets import THEMES, DEFAULT_PROFILE, DEFAULT_EXPORT, read_json, write_json, validate_profile
from ..core.export import export_scan
from .browser_panel import BrowserPanel
from .inspector_panel import InspectorPanel
from .image_view import ImageView
from .interactive_tool_palette import InteractiveToolPalette
from ..core.interactive_tools import TOOL_BY_ID, measure, roi_slice, point_pixel, three_point_plane_coefficients
from ..core.cropping import CropRegion, crop_channel, CropAlignmentError
from .module_panel import ModulePanel
from .log_panel import LogPanel
from .jobs import Task
from .export_dialog import PublicationDialog
from ..core.export_layout import export_publication, export_publication_formats, export_numerical_panel
from ..core.shortcuts import ACTIONS, ACTION_BY_ID, DEFAULT_BINDINGS, read_profiles
from .shortcut_options import ShortcutOptions, normalize_key
from ..core.research_records import make_record, format_record, execution_key
from ..core.result_library import organize_run, run_path, public_files, preview_files
from .result_view import ResultPreview
from spm_studio.shared import ResearchStore
from spm_studio.shared.ui_strings import ui_label, add_key_items, combo_key, set_combo_key

class FileCrawler(QThread):
    found=Signal(str)
    failed=Signal(str)
    def __init__(self,folder):
        super().__init__()
        self.folder=Path(folder)
    def run(self):
        try:
            for item in discover(self.folder):
                if self.isInterruptionRequested():break
                self.found.emit(str(item))
        except Exception as exc:
            self.failed.emit(str(exc))


def make_snapshot(run_dir, scan, channel, direction, selected_data, parameters, source_paths, roi, steps, rois=None, plot_config=None, plot_formats=None, snapshot_channels='selected', extra_channels=()):
    """Run snapshot creation is performed off the UI thread."""
    run_dir.mkdir(parents=True,exist_ok=False)
    from spm_studio.shared import fingerprint
    source_start_stat=scan.path.stat()
    source_sha256=fingerprint(scan.path)  # background snapshot worker, not Qt GUI thread
    source_end_stat=scan.path.stat()
    source_changed_during_snapshot=(source_start_stat.st_size!=source_end_stat.st_size or
        source_start_stat.st_mtime_ns!=source_end_stat.st_mtime_ns)
    # Light modules only need the selected channel (both traces).
    # Multi-channel modules retain the complete snapshot contract.
    arrays=select_snapshot_arrays(scan,channel,snapshot_channels,extra_channels)
    key=f'{channel}|{direction}'
    arrays[key]=selected_data
    filename=run_dir/'arrays.npz'
    np.savez(filename,**arrays)
    info={'api_version':'1.0','source_sha256':source_sha256,'source_size':source_end_stat.st_size,
          'source_mtime_ns':source_end_stat.st_mtime_ns,
          'source_changed_during_snapshot':source_changed_during_snapshot, 'scan_path':str(scan.path),'channel':channel,
          'direction':direction,'unit':scan.channels[channel].unit,
          'geometry':scan.channels[channel].geometry.to_dict(),
          'channel_geometries':{name:c.geometry.to_dict() for name,c in scan.channels.items()},
          'channel_units':{name:c.unit for name,c in scan.channels.items()},
          'metadata':scan.metadata,'parameters':parameters,
          'source_paths':list(map(str,source_paths)),
          'roi':roi.to_dict() if roi else None,
          'processing':[asdict(s) for s in steps],
          'rois':[r.to_dict() for r in (rois or [])],
          'plot_config': plot_config or DEFAULT_PLOT,
          'plot_formats': list(plot_formats or ('png','pdf')),
          'selected_key':key,'array_file':str(filename), 'output_dir':str(run_dir)}
    context=run_dir/'context.json'
    context.write_text(json.dumps(info,ensure_ascii=False,default=str,indent=2),encoding='utf8')
    return context

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('SPM Studio')
        self.resize(1340,860)
        self.setAcceptDrops(True)
        self.settings=QSettings('SPM Studio','SPM Studio AI 0.7')
        # Existing persistent records from pre-v0.5.1 must never restore a scan
        # or CPD masks. User-created JSON profiles and global preferences remain.
        self.settings.remove('last_file')
        self.settings.remove('last_folder')
        for key in self.settings.allKeys():
            if key.startswith('masks_'):
                self.settings.remove(key)
        self._dialog_folder=Path.home()
        self._session_folder=None  # the dataset folder the listed scans came from (v26 recap export)
        self._session_masks={}
        self._interactive_masks={}
        self._interactive_points=[]
        self._interactive_preview_roi=None
        self._interactive_cursor=None
        self._removed_paths=set()
        self._followup_view=None
        self._pending_view_request=None
        self._pending_load_path=None
        self.pool=QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(2)
        self._active_tasks = {}  # retain QRunnables until their queued signals complete
        self.cache=ArrayCache(384)
        self.scans={}
        # One view configuration per *source scan*, never a dataset-wide profile.
        # Style/processing arrays already have (path, channel, trace) keys.
        self._scan_view_states={}
        self._scan_profile_keys={}
        # A bulk profile affects the current file list only, and is installed
        # lazily for unopened scans (no large dataset-wide image decoding).
        self._pending_bulk_profiles=set()
        self._bias_figure_dialog=None
        self.research_store=ResearchStore()
        self._displayed_run_id=None
        self._run_source_sha=None
        self.scan=None
        self.processed=None
        self._current_channel=None
        self.styles={}
        self.pipelines={}
        self._crop_region=None
        self._crop_sources={}
        self._crop_applied=set()
        self._load_token=0
        self._process_token=0
        self._job_token=0
        self._pending_proc_key=None
        self._last_loaded_at=0.0
        self._syncing=False
        self._preserve_view=False
        self._last_roi=None
        self._source_paths=[]
        self._crawlers=[]
        self.job=None
        self._run_context=None
        self._run_module=None
        self._run_log=None
        self._stdout_buffer=''
        self._stderr_buffer=''
        self._run_started=0
        self._run_files=[]
        self._live_preview_roi=None
        self._multi_token=0
        self._secondary_views={}
        self._channel_titles={}
        self._result_records={}
        self._result_view=None
        self._active_result_module_id=None
        self._secondary_prepared=set()
        self._secondary_pending=set()
        self.modules={}
        self.last_export_dir=Path(str(self.settings.value('export_folder', str(Path.home()))))
        # Factory modules are real editable folders, never executed at startup.
        paths.install_factory_modules()
        self._module_upgrade_messages=paths.ensure_factory_channel_overlay_v27()
        self._module_upgrade_messages+=paths.upgrade_factory_modules()
        self._module_upgrade_messages+=paths.upgrade_factory_modules_v043()
        self._module_upgrade_messages+=paths.upgrade_factory_modules_v050()
        self._module_upgrade_messages+=paths.upgrade_factory_modules_v055()
        self._module_upgrade_messages+=paths.install_new_factory_modules()
        self._module_upgrade_messages += paths.upgrade_factory_lattice_20261108()
        self._module_upgrade_messages += paths.upgrade_factory_lattice_v5()
        # Always heal absent factory helper files even on existing installations
        # whose one-time upgrade markers are already present. Never overwrite edits.
        self._module_upgrade_messages += paths.repair_missing_factory_helpers()
        self._module_upgrade_messages += paths.upgrade_factory_analysis_v13()
        self._module_upgrade_messages += paths.synchronize_molecule_tools_v14()
        self._module_upgrade_messages += paths.upgrade_factory_overlays_v15()
        self._module_upgrade_messages += paths.upgrade_factory_overlays_v16()
        self._module_upgrade_messages += paths.upgrade_factory_tools_v080()
        paths.install_factory_customization()
        self._module_upgrade_messages += paths.upgrade_factory_profiles_v7()
        self._module_upgrade_messages += paths.upgrade_factory_brand_themes_v054()
        self._module_upgrade_messages += paths.upgrade_factory_customization()
        self._module_upgrade_messages += paths.upgrade_factory_customization_v051()
        self._module_upgrade_messages += paths.migrate_themes_v080()
        # v0.0.5: one KPFM profile, and a README.md guide in every scripts / customization folder
        # (read by people and by the assistant before a script or profile is created).
        self._module_upgrade_messages += paths.cleanup_kpfm_profiles_v005()
        try:self._module_upgrade_messages += paths.ensure_guides()
        except OSError as exc:self._module_upgrade_messages.append(f'Guides not installed: {exc}')
        # v0.0.8: LaTeX / presentation templates (folders) of the document editors.
        try:self._module_upgrade_messages += paths.install_factory_templates()
        except OSError as exc:self._module_upgrade_messages.append(f'Templates not installed: {exc}')
        self._shortcut_actions={}
        self._shortcut_dialog=None
        self._shortcut_bindings=DEFAULT_BINDINGS.copy()
        self._setup_ui()
        self._update_crop_buttons()
        self._create_actions()
        self._create_ai_dock()
        # v0.0.8: the hub links this window, the LaTeX / presentation editors and the assistant.
        from spm_studio.documents.ui.hub import hub as _document_hub
        self.documents=_document_hub()
        self.documents.set_main_window(self)
        self.refresh_document_buttons()
        self._setup_v0013()
        self._load_shortcuts()
        self._setup_shortcut_watch()
        self.refresh_modules()
        self._start_scripts_watch()
        self._load_profiles()
        self._load_colormaps()
        self._load_export_presets()
        ensure_bundled_styles(paths.customization_dir()/'plot_styles')
        self.viewer.plot_profile=self._plot_profile_for_run()
        self._initializing_appearance=True
        self._apply_theme(str(self.settings.value('theme','graphite')))
        self._initializing_appearance=False
        geometry=self.settings.value('geometry')
        if geometry:self.restoreGeometry(geometry)
        state=self.settings.value('window_state')
        if state:self.restoreState(state)
        # v0.0.18: the Logs panel starts closed; it opens with its button or on an error.
        self.log_dock.hide()
        self._update_channel_navigation()
        self.viewer.cursorChanged.connect(self.statusBar().showMessage)
        self.viewer.roiChanged.connect(self._on_roi)
        self.viewer.roiPreview.connect(self._preview_roi)
        self.viewer.roiEdited.connect(self._on_roi_edited)
        self.viewer.deleteSelectedRequested.connect(
            lambda:self._delete_selection(self.viewer.selected_roi_index))
        self.viewer.roiSelected.connect(self._roi_clicked)
        self.viewer.cursorPixelChanged.connect(self._interactive_cursor_move)
        self.interactive_palette.toolSelected.connect(self._interactive_select)
        self.interactive_palette.actionRequested.connect(self._interactive_action)
        self.module_panel.roiToolRequested.connect(self._choose_roi_tool)
        self.module_panel.undoLineRequested.connect(self._undo_line)
        self.module_panel.clearLinesRequested.connect(self._clear_lines)
        self.module_panel.deleteSelectionRequested.connect(self._delete_selection)
        self.module_panel.selectionChosen.connect(self._select_roi)
        self.inspector.visibleChannelsChanged.connect(self._sync_multiview)
        self.module_panel.changed.connect(self._queue_live_preview)
        self.module_panel.changed.connect(self._indicate_staleness)
        self.module_panel.masksChanged.connect(self._on_masks_changed)
        self.module_panel.gifExportRequested.connect(self._export_overlay_gif)
        self.module_panel.channelTitleEdited.connect(self._tool_title_edited)
        self.module_panel.use_scan_display.setChecked(str(self.settings.value('use_scan_display','true')).lower()=='true')
        self.module_panel.viewerDisplayToggled.connect(lambda v:self.settings.setValue('use_scan_display','true' if v else 'false'))
        self.inspector.selectionChanged.connect(self._change_selection)
        self.inspector.styleChanged.connect(self._update_style)
        self.inspector.processingChanged.connect(self._update_steps)
        self.inspector.openGwyddion.connect(self._open_in_gwyddion)
        self.inspector.fixZeroRequested.connect(self._apply_fix_zero_display)
        self.inspector.applyAll.connect(self._apply_all)
        self.browser.fileSelected.connect(self._load_file)
        self.browser.removeRequested.connect(self.remove_scan)
        self.browser.exportSelectionRequested.connect(self.export_scan_selection)
        self.browser.files.installEventFilter(self)
        self.browser.moduleSelected.connect(self._show_module)
        self.browser.tools.itemDoubleClicked.connect(
            lambda item:self.open_bias_figure_composer()
            if item.data(Qt.ItemDataRole.UserRole)=='__bias_figure_composer__' else None)
        self.module_panel.runRequested.connect(self.run_module)
        self.module_panel.runSelectionChanged.connect(self._select_saved_run)
        self.module_panel.saveCommentRequested.connect(self._save_research_note)
        self.module_panel.preferRequested.connect(self._prefer_run)
        self.logs.cancelRequested.connect(self.cancel_job)
        self.logs.resultChosen.connect(self._show_result)
        self._process_timer=QTimer(self)
        self._process_timer.setSingleShot(True)
        self._process_timer.setInterval(90)
        self._process_timer.timeout.connect(self._process_selection)
        self._live_timer=QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.setInterval(80)
        self._live_timer.timeout.connect(self._refresh_live_preview)
        self._interactive_timer=QTimer(self)
        self._interactive_timer.setSingleShot(True)
        self._interactive_timer.setInterval(75)
        self._interactive_timer.timeout.connect(self._interactive_update)
        # Start with an empty session. No scan, tool selection, ROI or mask is
        # automatically restored; only application-wide preferences persist.
        QApplication.instance().installEventFilter(self)

    def _setup_ui(self):
        from spm_studio.shared.appearance import tool_button, separator, set_icon
        from PySide6.QtWidgets import QFrame, QToolButton, QMenu
        central=QWidget()
        central.setObjectName('workbenchRoot')
        v=QVBoxLayout(central)
        v.setContentsMargins(0,0,0,0)
        v.setSpacing(0)
        # v0.8 header: one compact row, grouped actions, secondary commands in menus.
        self.topbar=QHBoxLayout()
        self.topbar.setContentsMargins(12,6,12,6)
        self.topbar.setSpacing(6)
        self.brand_mark=QLabel()
        self.brand_mark.setObjectName('BrandMark')
        self.brand_mark.setFixedSize(24,24)
        self.brand_mark.setScaledContents(True)
        self.brand_mark.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.brand_copy=QWidget()
        brand_layout=QVBoxLayout(self.brand_copy)
        brand_layout.setContentsMargins(0,0,0,0)
        brand_layout.setSpacing(0)
        self.brand_name=QLabel('SPM Studio')
        self.brand_name.setObjectName('BrandName')
        self.brand_subtitle=QLabel('Scientific image & data analysis')
        self.brand_subtitle.setObjectName('BrandSubtitle')
        self.brand_subtitle.hide()
        brand_layout.addWidget(self.brand_name)
        brand_layout.addWidget(self.brand_subtitle)
        self.topbar.addWidget(self.brand_mark)
        self.topbar.addWidget(self.brand_copy)
        self.topbar.addSpacing(10)
        self.open_button=QPushButton('Open')
        self.open_button.setProperty('primary',True)
        self.open_button.setToolTip('Open scan files (Ctrl+O)')
        set_icon(self.open_button,'open',color_token='accent_fg')
        self.open_button.clicked.connect(self.open_file)
        self.folder_button=QPushButton('Dataset')
        self.folder_button.setToolTip('Open every scan of a folder')
        set_icon(self.folder_button,'dataset')
        self.folder_button.clicked.connect(self.open_folder)
        self.profile_combo=QComboBox()
        self.profile_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)   # v0.0.18: never clipped
        self.profile_combo.setSizePolicy(QSizePolicy.Policy.Fixed,QSizePolicy.Policy.Fixed)
        self.profile_combo.setMinimumWidth(150)
        self.profile_combo.setToolTip('Processing / display profile')
        self.apply_profile_button=QPushButton('Apply profile')
        self.apply_profile_button.setToolTip('Apply only to the selected scan (other scans retain their own profiles)')
        self.apply_profile_button.clicked.connect(self.apply_profile)
        self.apply_all_profiles_button=QPushButton('Apply to all files')
        self.apply_all_profiles_button.setObjectName('ApplyProfileToAllFilesV18')
        self.apply_all_profiles_button.setToolTip('Apply the selected processing/display profile to EVERY scan currently listed; unopened files are updated when first visited. No raw files are changed.')
        self.apply_all_profiles_button.clicked.connect(self.apply_profile_to_all_files)
        self.scan_profile_label=QLabel('Scan profile: none')
        self.scan_profile_label.setObjectName('ActiveScanProfileV13')
        self.scan_profile_label.setToolTip('Profile applied to this scan in the current session')
        self.scan_profile_label.setProperty('chip',True)
        self.scan_profile_label.hide()
        self.save_profile_button=QPushButton('Save profile…')
        self.save_profile_button.setObjectName('SaveCurrentMultiChannelProfile')
        self.save_profile_button.setToolTip('Save visible channels, their individual processing steps, colormaps, and display titles under a new name')
        self.save_profile_button.clicked.connect(self.save_profile)
        self.export_preset_combo=QComboBox()
        self.export_preset_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)   # v0.0.18: never clipped
        self.export_preset_combo.setSizePolicy(QSizePolicy.Policy.Fixed,QSizePolicy.Policy.Fixed)
        self.export_preset_combo.setMinimumWidth(130)
        self.export_preset_combo.setToolTip('Figure size preset (Export… and analysis figures)')
        self.compare_button=QPushButton('Compare…')
        self.compare_button.clicked.connect(self.open_research_comparison)
        self.export_button=QPushButton('Export…')
        self.export_button.clicked.connect(self.export_current)
        self.bias_figure_button=QPushButton('Spectroscopy figure…')
        self.bias_figure_button.setObjectName('BiasFigureComposerV18')
        self.bias_figure_button.setToolTip('Build publication-ready multi-channel images and bias spectroscopy figures with live PDF preview')
        self.bias_figure_button.clicked.connect(self.open_bias_figure_composer)
        self.profile_autocrop=QCheckBox('Auto-crop')
        self.profile_autocrop.setObjectName('ProfileAutoCropIncomplete_v32')
        self.profile_autocrop.setToolTip('When a profile with auto-crop (AFM Dissipation / AFM Molecular) is applied, '
                                         'crop away the unmeasured part of an aborted scan. Complete scans are never cropped.')
        self.profile_autocrop.setChecked(str(self.settings.value('profile_autocrop','true')).lower()=='true')
        self.profile_autocrop.toggled.connect(lambda v:self.settings.setValue('profile_autocrop','true' if v else 'false'))
        # Profile group: combo + one split button (click = apply, arrow = more).
        profile_menu=QMenu(self)
        profile_menu.addAction('Apply to all listed files',self.apply_all_profiles_button.click)
        profile_menu.addAction('Save current display as profile…',self.save_profile_button.click)
        profile_menu.addSeparator()
        self._autocrop_action=profile_menu.addAction('Auto-crop incomplete scans')
        self._autocrop_action.setCheckable(True)
        self._autocrop_action.setChecked(self.profile_autocrop.isChecked())
        self._autocrop_action.toggled.connect(self.profile_autocrop.setChecked)
        self.profile_autocrop.toggled.connect(self._autocrop_action.setChecked)
        self.apply_profile_tool=tool_button('Apply',None,'Apply the profile to this scan',menu=profile_menu,flat=False)
        self.apply_profile_tool.setObjectName('ApplyProfileSplitV08')
        self.apply_profile_tool.clicked.connect(self.apply_profile_button.click)
        self.export_tool=tool_button('Export','export','Publication export (same layout as analysis figures)',flat=False)
        self.export_tool.setObjectName('ExportSplitV08')
        self.export_tool.clicked.connect(self.export_button.click)
        self.compare_tool=tool_button('Compare','compare','Compare saved analysis runs')
        self.compare_tool.clicked.connect(self.compare_button.click)
        self.ai_toolbar_button=QPushButton('Assistant')
        self.ai_toolbar_button.setObjectName('AiAssistantToggleV08')
        self.ai_toolbar_button.setCheckable(True)
        self.ai_toolbar_button.setProperty('flat',True)
        self.ai_toolbar_button.setToolTip('Show / hide the AI assistant (dockable, detachable)')
        set_icon(self.ai_toolbar_button,'ai')
        self.ai_toolbar_button.clicked.connect(self.toggle_ai_assistant)
        # v0.0.5: the menu bar is gone. Logs get a visible toggle, and everything that had no other
        # place lives behind one gear button (Settings).
        self.logs_toolbar_button=tool_button('Logs','logs','Show / hide the Logs panel (run output and result files)',
                                             checkable=True)
        self.logs_toolbar_button.setObjectName('LogsToggleV005')
        self.logs_toolbar_button.clicked.connect(self._toggle_logs)
        self.settings_button=tool_button('','gear','Settings: library, literature sources, theme, shortcuts, '
                                         'assistant, updates, about',icon_only=True)
        self.settings_button.setObjectName('SettingsGearV005')
        self.settings_button.setAccessibleName('Settings')
        from PySide6.QtCore import QSize as _QSize
        self.settings_button.setIconSize(_QSize(20,20))
        self.settings_button.clicked.connect(lambda:self.open_settings())
        for w in (self.open_button,self.folder_button):self.topbar.addWidget(w)
        self.topbar.addStretch(1)
        self.topbar.addWidget(self.scan_profile_label)
        self.topbar.addWidget(self.profile_combo)
        self.topbar.addWidget(self.apply_profile_tool)
        self.topbar.addWidget(separator())
        self.topbar.addWidget(self.export_preset_combo)
        self.topbar.addWidget(self.export_tool)
        self.topbar.addWidget(separator())
        self.topbar.addWidget(self.compare_tool)
        # v0.0.8: shown only when switched on in Settings › Documents.
        self.latex_button=tool_button('LaTeX','latex','LaTeX editor: new project, open, import (Overleaf-like, live PDF)')
        self.latex_button.setObjectName('OpenLatexEditorV008')
        self.latex_button.clicked.connect(self.open_latex_editor)
        self.slides_button=tool_button('Slides','slides','Presentation editor: new presentation, open, import')
        self.slides_button.setObjectName('OpenSlidesEditorV008')
        self.slides_button.clicked.connect(self.open_slides_editor)
        self.todo_button=tool_button('To-do','todo','To-do list & notes, connected to the assistant (opens in its own window)')
        self.todo_button.setObjectName('OpenTodoV0012')
        self.todo_button.clicked.connect(self.open_todo)
        self.topbar.addWidget(self.latex_button)
        self.topbar.addWidget(self.slides_button)
        self.topbar.addWidget(self.todo_button)
        self.topbar.addWidget(self.logs_toolbar_button)
        self.topbar.addWidget(self.ai_toolbar_button)
        self.topbar.addWidget(separator())
        self.topbar.addWidget(self.settings_button)
        # v26: the Bias figure button leaves the top bar; the composer stays in the Analysis menu.
        self.bias_figure_button.hide()
        # Legacy widgets stay alive (shortcuts, tests, profiles) but are not duplicated on screen.
        for hidden in (self.apply_profile_button,self.apply_all_profiles_button,self.save_profile_button,
                       self.profile_autocrop,self.export_button,self.compare_button,self.bias_figure_button):
            hidden.hide();hidden.setParent(central)
        header=QFrame();header.setObjectName('appHeader')
        header_layout=QVBoxLayout(header);header_layout.setContentsMargins(0,0,0,0);header_layout.setSpacing(0)
        from spm_studio.shared.appearance import scroll_toolbar
        self.action_scroll=scroll_toolbar(self.topbar,header_layout,height=48)
        v.addWidget(header)
        body=QWidget();body_layout=QVBoxLayout(body);body_layout.setContentsMargins(8,8,8,6);body_layout.setSpacing(6)
        v.addWidget(body,1)
        splitter=QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName('WorkspaceSplitter')
        splitter.setChildrenCollapsible(False)
        self.workspace_splitter=splitter
        self.browser=BrowserPanel()
        self.browser.setMinimumWidth(215)
        self.viewer=ImageView()
        self.view_area=QWidget()
        vl=QVBoxLayout(self.view_area)
        vl.setContentsMargins(0,0,0,0)
        vl.setSpacing(6)
        # v0.8: one compact image toolbar; rarely used commands live in the Crop menu.
        buttons=QHBoxLayout()
        buttons.setContentsMargins(0,0,0,0)
        buttons.setSpacing(2)
        self.fit_button=tool_button('','fit','Fit all previews',icon_only=True)
        self.fit_button.clicked.connect(self.fit_all_views)
        self.line_button=tool_button('Line','line','Draw a line selection')
        self.rect_button=tool_button('Region','rect','Draw a rectangular region')
        for button,tool in ((self.line_button,'line'),(self.rect_button,'rectangle')):
            button.clicked.connect(lambda _=False,name=tool:self.viewer.set_roi_tool(name))
        self.keep_lines=tool_button('','keep','Keep lines: each new line is added instead of replacing the last one',
                                    checkable=True,icon_only=True)
        self.keep_lines.setObjectName('KeepLinesMultiLineV32')
        self.keep_lines.setChecked(True)
        self.line_profiles_button=tool_button('Profiles','profile','Line profiles of every drawn line, on one or more channels')
        self.line_profiles_button.setObjectName('OpenMultiLineProfilesV32')
        self.line_profiles_button.clicked.connect(self.open_line_profiles)
        self.manual_molecules_button=tool_button('Molecules','molecule','Place molecules by hand at true scale')
        self.manual_molecules_button.setObjectName('OpenManualMoleculesV32')
        self.manual_molecules_button.clicked.connect(self.open_manual_molecules)
        self.crop_region_button=QPushButton('Crop ROI')
        self.crop_region_button.setObjectName('CropRegionButton_v10')
        self.crop_region_button.setToolTip('Crop every visible channel to the drawn region')
        self.crop_region_button.clicked.connect(self._crop_from_toolbar)
        self.crop_all_button=QPushButton('Crop all')
        self.crop_all_button.setObjectName('CropOtherChannelsButton_v10')
        self.crop_all_button.setToolTip('Apply the current crop also to every unopened data channel')
        self.crop_all_button.clicked.connect(self._crop_other_channels)
        self.reset_crop_button=QPushButton('Reset crop')
        self.reset_crop_button.setObjectName('ResetCropButton_v10')
        self.reset_crop_button.setToolTip('Restore all channels to the full scan')
        self.reset_crop_button.clicked.connect(self._reset_session_crop)
        self.auto_crop_button=QPushButton('Auto-crop incomplete')
        self.auto_crop_button.setObjectName('AutoCropIncompleteButton_v32')
        self.auto_crop_button.setToolTip('Crop an aborted scan to its measured part; complete scans are untouched')
        self.auto_crop_button.clicked.connect(lambda:self.auto_crop_incomplete(interactive=True))
        crop_menu=QMenu(self)
        self._crop_all_action=crop_menu.addAction('Apply crop to all channels',self.crop_all_button.click)
        self._reset_crop_action=crop_menu.addAction('Reset crop',self.reset_crop_button.click)
        crop_menu.addSeparator()
        crop_menu.addAction('Auto-crop incomplete scan',self.auto_crop_button.click)
        self.crop_tool=tool_button('Crop','crop','Crop all visible channels to the drawn region',menu=crop_menu)
        self.crop_tool.setObjectName('CropSplitV08')
        self.crop_tool.clicked.connect(self.crop_region_button.click)
        self.metadata_button=QPushButton('Metadata')
        self.metadata_button.setObjectName('ShowMetadataButton_v10')
        self.metadata_button.setToolTip('Show the full SXM/GWY acquisition header in the left-hand Metadata panel')
        self.metadata_button.clicked.connect(self._show_metadata)
        self.prev_channel_button=tool_button('','prev','Scroll previews left',icon_only=True)
        self.next_channel_button=tool_button('','next','Scroll previews right',icon_only=True)
        self.prev_channel_button.clicked.connect(lambda:self._scroll_channels(-1))
        self.next_channel_button.clicked.connect(lambda:self._scroll_channels(1))
        self.back_to_scan_button=tool_button('Back to scan','back','Leave the result view')
        self.back_to_scan_button.clicked.connect(self._back_to_scan)
        for w in (self.fit_button,separator(),self.line_button,self.rect_button,self.keep_lines,separator(),
                  self.crop_tool,separator(),self.line_profiles_button,self.manual_molecules_button):
            buttons.addWidget(w)
        buttons.addStretch(1)
        for w in (self.back_to_scan_button,self.prev_channel_button,self.next_channel_button):
            buttons.addWidget(w)
        crop_buttons=QHBoxLayout()   # kept for compatibility; its widgets are reached via the Crop menu
        for hidden in (self.crop_region_button,self.crop_all_button,self.reset_crop_button,
                       self.auto_crop_button,self.metadata_button):
            hidden.hide();hidden.setParent(self.view_area)
        toolbar_frame=QFrame();toolbar_frame.setObjectName('viewToolbar')
        toolbar_frame.setLayout(buttons)
        vl.addWidget(toolbar_frame)
        # Keep individual views large enough to read. A splitter made each
        # raster unusably narrow when more than four channels were selected.
        self.channel_scroll=QScrollArea()
        self.channel_scroll.setObjectName('ChannelPreviewScroll')
        self.channel_scroll.setWidgetResizable(True)
        self.channel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.channel_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.channel_scroll.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.channel_scroll.setToolTip('←/→ move between channel previews; ↑/↓ switch scans (no click required). Shift+wheel scrolls horizontally.')
        self.channel_content=QWidget()
        self.channel_layout=QHBoxLayout(self.channel_content)
        self.channel_layout.setContentsMargins(0,0,0,0)
        self.channel_layout.setSpacing(6)
        self.viewer.setMinimumWidth(460)
        self.viewer.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
        self.channel_layout.addWidget(self.viewer,1)
        self.channel_scroll.setWidget(self.channel_content)
        self.channel_scroll.horizontalScrollBar().rangeChanged.connect(
            lambda *_:(self._update_channel_navigation(),QTimer.singleShot(0,self._load_visible_channels)))
        self.channel_scroll.horizontalScrollBar().valueChanged.connect(
            lambda *_:(self._update_channel_navigation(),self._load_visible_channels()))
        vl.addWidget(self.channel_scroll,1)
        self.right_tabs=QTabWidget()
        self.inspector=InspectorPanel()
        self.module_panel=ModulePanel()
        self.interactive_palette=InteractiveToolPalette()
        view_scroll=QScrollArea()
        view_scroll.setWidgetResizable(True)
        view_scroll.setWidget(self.inspector)
        tool_scroll=QScrollArea()
        tool_scroll.setWidgetResizable(True)
        for area in (view_scroll,tool_scroll):area.setFrameShape(QScrollArea.Shape.NoFrame)
        tool_scroll.setWidget(self.module_panel)
        self.module_tools_scroll=tool_scroll
        self.right_tabs.addTab(view_scroll,'Inspector')
        interactive_scroll=QScrollArea()
        interactive_scroll.setWidgetResizable(True)
        interactive_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        interactive_scroll.setWidget(self.interactive_palette)
        self.image_tools_scroll=interactive_scroll
        self.image_tools_scroll.setObjectName('ImageToolsPanel_v7')
        self.right_tabs.addTab(interactive_scroll,'Image tools')
        self.right_tabs.setTabToolTip(1,'Interactive measurements on the scan')
        self.right_tabs.setTabToolTip(0,'Channel, display and processing')
        self.right_tabs.addTab(tool_scroll,'Analysis')
        self.right_tabs.setTabToolTip(2,'Settings of the analysis tool selected in Tools')
        self.right_tabs.setMinimumWidth(312)
        for widget in (self.browser,self.view_area,self.right_tabs):
            splitter.addWidget(widget)
        splitter.setStretchFactor(0,0)
        splitter.setStretchFactor(1,1)
        splitter.setStretchFactor(2,0)
        splitter.setSizes([255,735,360])
        # Do not restore a narrow Inspector from old versions.  Users can
        # adjust the splitter and its size is saved from this version onward.
        saved=self.settings.value('workspace_splitter_v044')
        if saved:
            splitter.restoreState(saved)
        QTimer.singleShot(0,self._enforce_panel_widths)
        QTimer.singleShot(5000,self._start_update_check)
        body_layout.addWidget(splitter,1)
        self.setCentralWidget(central)
        self.logs=LogPanel()
        dock=QDockWidget('Logs',self)
        dock.setObjectName('ResultsDock')
        dock.setWidget(self.logs)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea,dock)
        dock.hide()
        from spm_studio.shared.appearance import style_dock_titlebar
        style_dock_titlebar(dock)
        self.log_dock=dock
        dock.visibilityChanged.connect(lambda _visible:self.logs_toolbar_button.setChecked(self.log_dock.isVisible()))
        dock.visibilityChanged.connect(lambda visible:visible and self._set_logs_attention(False))
        # v0.0.8: a result (graph, figure) can be sent to the LaTeX editor, a presentation or Overleaf.
        self.logs.outputs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.logs.outputs.customContextMenuRequested.connect(self._result_menu)
        self.statusBar().showMessage('Ready  ·  Ctrl+O open  ·  ↑↓ scans  ·  ←→ channels')

    # ---- v0.0.8: LaTeX editor, presentation editor, Overleaf (spm_studio/documents)
    def refresh_document_buttons(self):
        """Show the LaTeX / Slides buttons only when they are switched on in Settings › Documents."""
        from spm_studio.documents import settings as doc_settings
        conf=doc_settings.load()
        self.latex_button.setVisible(bool(conf.get('latex_enabled')))
        self.slides_button.setVisible(bool(conf.get('slides_enabled')))
        self.todo_button.setVisible(bool(conf.get('todo_enabled',True)))

    def open_todo(self):
        self.documents.open_todo()

    def open_latex_editor(self):
        self.documents.launch('latex',self)

    def open_slides_editor(self):
        self.documents.launch('slides',self)

    def _result_menu(self,pos):
        from PySide6.QtWidgets import QMenu
        item=self.logs.outputs.itemAt(pos)
        if item is None:return
        path=item.data(Qt.ItemDataRole.UserRole)
        if not path or not Path(path).is_file():return
        menu=QMenu(self)
        menu.addAction('Open',lambda:self._show_result(path))
        from spm_studio.documents import settings as doc_settings
        if doc_settings.any_enabled():
            menu.addAction('Send to LaTeX / presentation / Overleaf…',lambda:self.send_result(path))
        menu.addAction('Show in folder',lambda:self._open_directory(Path(path).parent))
        menu.exec(self.logs.outputs.viewport().mapToGlobal(pos))

    def send_result(self,path):
        """Send an existing result file (graph, figure) to the document editors / Overleaf."""
        files=[Path(path)]
        stem=Path(path).with_suffix('')
        for suffix in ('.pdf','.svg','.png'):
            sibling=stem.with_suffix(suffix)
            if sibling.is_file() and sibling not in files:files.append(sibling)
        self.documents.send_files_dialog(files,self)

    # ---- updates (GitHub releases; see core/updates.py)
    # ------------------------------------------------------------------ v0.0.13: tutorial, beta, extensions
    def _setup_v0013(self):
        import os
        from spm_studio.beta.api import ExtensionAPI
        from spm_studio.beta import client as beta_client
        self.tutorial_counters={}
        self.tutorial=None
        self._welcome=None
        self.beta_session=beta_client.Session()
        self.extension_api=ExtensionAPI(self)
        self._beta_workers=[]
        try:
            from spm_studio.beta import extensions
            report=extensions.load_enabled(self.extension_api,beta_client.offline_grace_ok())
            for ext_id,status in report.items():
                if status!='disabled':self._log(f'Extension {ext_id}: {status}')
        except Exception as exc:
            self._log(f'Extensions were not loaded: {exc}')
        headless=os.environ.get('QT_QPA_PLATFORM')=='offscreen' and not os.environ.get('SPM_STUDIO_FORCE_ONBOARDING')
        if not headless and not os.environ.get('SPM_STUDIO_NO_ONBOARDING'):
            QTimer.singleShot(1500,self._maybe_onboard)
        if not headless and self.beta_session.signed_in():
            QTimer.singleShot(8000,self._beta_background_check)

    def tutorial_event(self,name):
        counters=getattr(self,'tutorial_counters',None)
        if counters is not None:counters[name]=counters.get(name,0)+1

    def _tutorial_manager(self):
        from spm_studio.tutorial.ui import TutorialManager
        if self.tutorial is None:
            self.tutorial=TutorialManager(self,self.extension_api.tutorial_decorators)
            self.tutorial.finished.connect(self._tutorial_finished)
        return self.tutorial

    def start_tutorial(self,position=0):
        self._close_welcome()
        self._tutorial_manager().start(position=position,kind='basics')

    def start_whats_new(self):
        from spm_studio.core.updates import current_version
        from spm_studio.tutorial.ui import whats_new_steps
        self._close_welcome()
        steps=whats_new_steps(current_version())
        if not steps:
            self._log('No “what’s new” notes for this version.',important=True)
            return
        self._tutorial_manager().start(steps,kind='whats_new')

    def _tutorial_finished(self,reason):
        if reason=='completed' and self.tutorial is not None and self.tutorial.kind=='basics':
            self._log('Guided tutorial finished. Replay it from Settings › Tutorials or Help › Guided tutorial.',important=True)

    def open_tutorial_scans(self):
        from spm_studio.tutorial import dataset
        try:
            folder=dataset.prepare_workspace()
        except Exception as exc:
            QMessageBox.warning(self,'Tutorial scans',str(exc))
            return
        self.browser.tabs.setCurrentIndex(0)
        for name in dataset.FILES:
            self._add_file(str(folder/name))
        self._dialog_folder=folder
        self._log(f'Tutorial scans (unmodified copies, checksums verified): {folder}')

    def _maybe_onboard(self):
        from spm_studio.core.updates import current_version
        from spm_studio.tutorial import state
        from spm_studio.tutorial.ui import WelcomePanel
        action=state.startup_action(current_version())
        if action is None:return
        if action=='whats_new':
            self._log('What’s new in this update? Help › What’s new in this version (a 1-minute tour).',important=True)
            return
        self._welcome=WelcomePanel(self,offer_whats_new=False)
        self._welcome.start.connect(lambda:self.start_tutorial(0))
        self._welcome.skip.connect(self._skip_welcome)
        self._welcome.place();self._welcome.show()
        state.update(welcome_shown=True)

    def _skip_welcome(self):
        from spm_studio.tutorial import state
        state.update(skipped=True,welcome_shown=True)
        self._close_welcome()

    def _close_welcome(self):
        if getattr(self,'_welcome',None) is not None:
            self._welcome.hide();self._welcome.deleteLater();self._welcome=None

    def _beta_background_check(self):
        """Renew this computer's beta session (keeps the offline grace fresh); optionally look for updates."""
        import time
        from PySide6.QtCore import QThread,Signal
        from spm_studio.beta import client as beta_client
        state=beta_client.load_state()
        want_release=bool(state.get('auto_check')) and time.time()-float(state.get('last_release_check',0) or 0)>86400
        session=self.beta_session

        class _Check(QThread):
            done=Signal(str)
            def run(self):
                try:
                    session.refresh()
                    if want_release:
                        m=session.latest_release()
                        from spm_studio.beta import extensions
                        info=extensions.installed().get(m['id'])
                        if info is None or info['descriptor']['version']!=m['version']:
                            self.done.emit(f"{m['name']} {m['version']} is available (Settings › Beta Tester).")
                            return
                    self.done.emit('')
                except Exception as exc:
                    self.done.emit('Beta: '+beta_client.friendly(exc))
        worker=_Check(self)
        worker.done.connect(self._beta_check_done)
        worker.finished.connect(lambda:self._beta_workers.remove(worker) if worker in self._beta_workers else None)
        self._beta_workers.append(worker)
        worker.start()

    def _beta_check_done(self,text):
        if text:self._log(text)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if getattr(self,'_welcome',None) is not None:self._welcome.place()

    def open_update_dialog(self,result=None):
        from .update_dialog import UpdateDialog
        UpdateDialog(self,result).exec()

    def _start_update_check(self):
        import os
        if os.environ.get('QT_QPA_PLATFORM')=='offscreen' or os.environ.get('SPM_STUDIO_NO_UPDATE_CHECK'):
            return
        from .update_dialog import StartupCheck
        self._update_check=StartupCheck(self)
        self._update_check.available.connect(self._update_available)
        self._update_check.start()

    def _update_available(self,result):
        from PySide6.QtWidgets import QPushButton
        if getattr(self,'_update_button',None) is None:
            self._update_button=QPushButton()
            self._update_button.setFlat(True)
            self._update_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.statusBar().addPermanentWidget(self._update_button)
        self._update_button.setText(f"⬆ SPM Studio {result['latest']} available — what's new?")
        try:self._update_button.clicked.disconnect()
        except (RuntimeError,TypeError):pass
        self._update_button.clicked.connect(lambda:self.open_update_dialog(result))

    def _about_spm_studio(self):
        self.open_settings('about')

    # ---- v0.0.5: Settings window (gear button), Logs toggle, library reloads
    def open_settings(self,page='general'):
        from .settings_dialog import SettingsDialog
        dialog=SettingsDialog(self,page)
        self._settings_dialog=dialog
        try:
            dialog.exec()
        finally:
            self._settings_dialog=None
            dialog.deleteLater()

    @staticmethod
    def _fit_combo(combo):
        """v0.0.18: a top-bar list is always wide enough for its longest entry (never "Single colur")."""
        fm=combo.fontMetrics()
        longest=max((fm.horizontalAdvance(combo.itemText(i)) for i in range(combo.count())),default=60)
        combo.setMinimumWidth(min(320,longest+52))

    def _toggle_logs(self):
        self.log_dock.setVisible(not self.log_dock.isVisible())
        self.logs_toolbar_button.setChecked(self.log_dock.isVisible())

    def reload_library(self,kind):
        """Re-read one kind of user files after Settings › Library changed it (no restart needed)."""
        if kind=='scripts':
            self._scripts_sig=self._scripts_signature()
            self._live_refresh_modules()
        elif kind=='profiles':
            key=combo_key(self.profile_combo)
            self._load_profiles()
            if key in self.profiles:set_combo_key(self.profile_combo,key)
        elif kind=='exports':
            key=combo_key(self.export_preset_combo)
            self._load_export_presets()
            if key in self.export_presets:set_combo_key(self.export_preset_combo,key)
        elif kind=='themes':
            self._populate_theme_menu()
        elif kind=='colormaps':
            palette=self.inspector.palette
            key=combo_key(palette)
            palette.blockSignals(True)     # re-listing must not change the colormap of the open scan
            try:
                self._load_colormaps()
                index=palette.findData(key)
                if index>=0:palette.setCurrentIndex(index)
            finally:
                palette.blockSignals(False)
        elif kind=='plots':
            ensure_bundled_styles(paths.customization_dir()/'plot_styles')
            self.viewer.plot_profile=self._plot_profile_for_run()
        elif kind=='shortcuts':
            self._reload_shortcuts_from_disk()

    def restore_builtin_tools(self):
        """Replace the lattice / molecule tools by the versions shipped with this release (backup first)."""
        if QMessageBox.question(self,'Restore built-in tools',
                'Replace the installed Lattice measurements and Molecule placement scripts by the '
                'versions shipped with this release?\n\nYour current files are backed up first '
                '(scripts folder › .factory_backups_v080).')!=QMessageBox.StandardButton.Yes:
            return
        notes=paths.upgrade_factory_tools_v080(force=True)
        for note in notes:self._log('Built-in tools: '+note)
        self.refresh_modules()
        self.statusBar().showMessage('Built-in tools restored' if notes else 'Built-in tools already up to date',6000)

    def show_image_tools(self):
        """An always-visible route to the live measurement palette."""
        self.right_tabs.setCurrentWidget(self.image_tools_scroll)
        self.right_tabs.raise_()
        self.image_tools_scroll.ensureVisible(0,0)
        self.statusBar().showMessage('Image tools: choose a tool, then click/drag on the scan for live results', 7000)

    def _show_metadata(self):
        self.browser.show_metadata()
        self.statusBar().showMessage('Metadata: complete instrument acquisition parameters in the left panel',7000)

    def _crop_from_toolbar(self):
        if self.scan is None:
            QMessageBox.information(self,'Crop region','Load a scan before cropping.')
            return
        roi=self._interactive_current_roi()
        if roi is None or roi.kind!='rectangle':
            QMessageBox.information(self,'Crop region',
                'Click Rect ROI above the scan, drag a rectangular region on the main scan, '
                'then click Crop ROI. The same crop will be applied to every visible channel.')
            self.viewer.set_roi_tool('rectangle')
            return
        try:
            self._crop_selected_region(roi)
        except (ValueError,CropAlignmentError) as exc:
            self._log(f'Could not crop selected region: {exc}',important=True)
            QMessageBox.warning(self,'Crop failed',str(exc))

    def _update_crop_buttons(self):
        active=self.scan is not None and self._crop_region is not None
        self.crop_all_button.setEnabled(active)
        self.reset_crop_button.setEnabled(active)
        self.crop_region_button.setEnabled(self.scan is not None)
        if hasattr(self,'crop_tool'):
            self.crop_tool.setEnabled(self.scan is not None)
            self._crop_all_action.setEnabled(active)
            self._reset_crop_action.setEnabled(active)

    def _enforce_panel_widths(self):
        splitter=self.workspace_splitter
        sizes=splitter.sizes()
        if len(sizes)!=3:return
        available=sum(sizes)
        target=min(370,max(312,round(available*.28)))
        # Allow the central scan view to remain useful even on smaller screens.
        if sizes[2]<target:
            browser=max(215,min(sizes[0],285))
            center=max(260,available-browser-target)
            splitter.setSizes([browser,center,target])

    def _action(self,menu,text,action_id,fn):
        """Connect one command to menus, editable shortcuts and the help table."""
        action=QAction(text,self)
        action.triggered.connect(fn)
        menu.addAction(action)
        self.addAction(action)
        if action_id:
            if action_id in self._shortcut_actions:
                raise ValueError(f'Duplicate registered action {action_id}')
            self._shortcut_actions[action_id]=action
        return action

    def _create_actions(self):
        """Commands, their editable shortcuts and the shortcut help table.

        v0.0.5: the menu bar itself is hidden (File / Scan / Selection … duplicated the buttons of
        the window). The actions stay registered on the window, so every keyboard shortcut keeps
        working; commands that had no button are in Settings (gear button of the top bar).
        """
        bar=self.menuBar()
        bar.setNativeMenuBar(False)
        bar.setVisible(False)
        # ---- File
        menu_file=bar.addMenu('&File')
        self._action(menu_file,'Open scans…','file.open',self.open_file)
        self._action(menu_file,'Open dataset folder…','file.dataset',self.open_folder)
        self._action(menu_file,'Remove scan from list','file.remove',self.remove_scan)
        menu_file.addSeparator()
        self._action(menu_file,'Export figure…','file.export',self.export_current)
        menu_file.addAction('Copy listed scans to a recap folder…',self.export_scan_selection)
        menu_file.addSeparator()
        imports=menu_file.addMenu('Import')
        self._action(imports,'Profile…','file.import_profile',self.import_profile)
        self._action(imports,'Figure preset…','file.import_export',self.import_export_preset)
        self._action(imports,'Theme…','file.import_theme',self.import_theme)
        self._action(imports,'Colormap…','file.import_colormap',self.import_colormap)
        imports.addAction('Gwyddion gradients…',self.import_gwyddion_gradients)
        self._action(imports,'Shortcut file…','options.import_shortcuts',self.import_shortcuts)
        self._action(imports,'Analysis module…','tool.import',self.import_module)
        # ---- Scan
        scan_menu=bar.addMenu('&Scan')
        self._action(scan_menu,'Apply profile','view.profile_apply',self.apply_profile)
        scan_menu.addAction('Apply profile to all listed files',self.apply_profile_to_all_files)
        self._action(scan_menu,'Save display as profile…','file.save_profile',self.save_profile)
        self._action(scan_menu,'Next profile','view.profile_next',lambda:self._shift_combo(self.profile_combo,1))
        self._action(scan_menu,'Next figure preset','view.export_preset_next',lambda:self._shift_combo(self.export_preset_combo,1))
        scan_menu.addSeparator()
        scan_menu.addAction('Crop to region',self._crop_from_toolbar)
        scan_menu.addAction('Apply crop to all channels',self._crop_other_channels)
        scan_menu.addAction('Reset crop',self._reset_session_crop)
        scan_menu.addAction('Auto-crop incomplete scan',lambda:self.auto_crop_incomplete(interactive=True))
        scan_menu.addSeparator()
        self._action(scan_menu,'Next channel','view.active_channel_next',lambda:self._shift_active_channel(1))
        self._action(scan_menu,'Previous channel','view.active_channel_previous',lambda:self._shift_active_channel(-1))
        self._action(scan_menu,'Toggle forward / backward','view.trace_toggle',self._toggle_trace)
        scan_menu.addAction('Metadata',self._show_metadata)
        # ---- Selection
        sel=bar.addMenu('S&election')
        self._action(sel,'Line','view.line',lambda:self._shortcut_roi_tool('line'))
        self._action(sel,'Region','view.rectangle',lambda:self._shortcut_roi_tool('rectangle'))
        self._action(sel,'Point','view.point',lambda:self._shortcut_roi_tool('point'))
        sel.addSeparator()
        self._action(sel,'Undo last','view.undo_selection',self._undo_line)
        self._action(sel,'Delete selected','view.delete_selection',
                     lambda:self._delete_selection(self.module_panel.selection_list.currentRow()))
        self._action(sel,'Clear all','view.clear_selections',self._clear_lines)
        self._action(sel,'Clear active selection','view.clear_roi',self._clear_roi)
        # ---- Analysis
        tools=bar.addMenu('&Analysis')
        self._action(tools,'Run','tool.run',self.run_module)
        self._action(tools,'Cancel','tool.cancel',self.cancel_job)
        self._action(tools,'Next tool','tool.next',lambda:self._select_relative_tool(1))
        self._action(tools,'Previous tool','tool.previous',lambda:self._select_relative_tool(-1))
        tools.addSeparator()
        tools.addAction('Line profiles…',self.open_line_profiles)
        tools.addAction('Place molecules by hand…',self.open_manual_molecules)
        self._action(tools,'Spectroscopy figure composer…',None,self.open_bias_figure_composer)
        self._action(tools,'3D print (STL / STEP)…',None,self.open_print3d)
        self._action(tools,'Compare saved runs…',None,self.open_research_comparison)
        tools.addSeparator()
        self._action(tools,'Refresh modules','tool.refresh',self.refresh_modules)
        tools.addAction('Restore built-in tools…',self.restore_builtin_tools)
        self._action(tools,'Open scripts folder','tool.scripts_folder',lambda:self._open_directory(paths.scripts_dir()))
        self._action(tools,'Clear preview cache','tool.clear_cache',self._clear_cache)
        # ---- View
        view=bar.addMenu('&View')
        self._action(view,'Fit previews','view.fit',self.fit_all_views)
        self._action(view,'Back to scan','view.back_to_scan',self._back_to_scan)
        view.addSeparator()
        self._action(view,'Files','panel.files',lambda:self.browser.tabs.setCurrentIndex(0))
        self._action(view,'Tools','panel.tools',lambda:self.browser.tabs.setCurrentIndex(1))
        self._action(view,'Inspector','panel.inspector',lambda:self.right_tabs.setCurrentIndex(0))
        view.addAction('Image tools',self.show_image_tools)
        self._action(view,'Analysis settings','panel.tool_settings',lambda:self.right_tabs.setCurrentWidget(self.module_tools_scroll))
        self._action(view,'Logs','panel.logs',self._show_logs)
        self._action(view,'Show / hide logs','view.results',lambda:self.log_dock.setVisible(not self.log_dock.isVisible()))
        view.addSeparator()
        view.addAction('Assistant',self.toggle_ai_assistant)
        self._theme_menu=view.addMenu('Theme')
        # ---- Settings
        options=bar.addMenu('Se&ttings')
        self._action(options,'Results && figures…','options.plot',self.open_plot_options)
        self._action(options,'Keyboard shortcuts…','options.shortcuts',self.open_shortcut_options)
        self._action(options,'Export shortcut file…','options.export_shortcuts',self.export_shortcuts)
        options.addSeparator()
        options.addAction('AI assistant…',lambda:self.ai_dock.setup())
        options.addAction('Check for updates…',lambda:self.open_update_dialog())
        options.addSeparator()
        self._action(options,'Open customization folder','tool.customization_folder',lambda:self._open_directory(paths.customization_dir()))
        options.addAction('Open shortcuts folder',lambda:self._open_directory(paths.customization_dir()/'shortcuts'))
        # ---- Help
        help_menu=bar.addMenu('&Help')
        help_menu.addAction('Customization guide',lambda:QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(paths.customization_dir()/'README_CUSTOMIZATION.md'))))
        help_menu.addAction('Keyboard shortcuts',self.open_shortcut_options)
        help_menu.addSeparator()
        help_menu.addAction('Guided tutorial',lambda:self.start_tutorial(0))
        help_menu.addAction('What’s new in this version',self.start_whats_new)
        help_menu.addAction('KBr tutorial scans',self.open_tutorial_scans)
        help_menu.addSeparator()
        help_menu.addAction('Check for updates…',lambda:self.open_update_dialog())
        self._action(help_menu,'About SPM Studio',None,self._about_spm_studio)
        self._populate_theme_menu()
        # Position slots are bound through the same configurable shortcut registry.
        for i in range(1,9):
            item=QAction(self)
            item.triggered.connect(lambda checked=False,index=i:self._select_tool_slot(index))
            self.addAction(item)
            self._shortcut_actions[f'tool.slot{i}']=item
        missing=set(ACTION_BY_ID)-set(self._shortcut_actions)-{
            'nav.scan_previous','nav.scan_next','nav.channel_left','nav.channel_right'}
        if missing:raise RuntimeError('Unregistered keyboard actions: '+', '.join(sorted(missing)))

    def _create_ai_dock(self):
        # Persistent native dock. Hiding/undocking does not interrupt its tasks.
        from spm_studio.ai.chat_ui import AssistantDock
        self.ai_dock=AssistantDock(self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,self.ai_dock)
        self.ai_dock.hide()
        self.ai_dock.visibilityChanged.connect(lambda visible:self.ai_toolbar_button.setChecked(self.ai_dock.is_open()))
        self.ai_dock.shownChanged.connect(lambda shown:self.ai_toolbar_button.setChecked(self.ai_dock.is_open()))

    def open_ai_assistant(self):
        self.ai_dock.first_open()

    def toggle_ai_assistant(self):
        if self.ai_dock.is_open():
            self.ai_dock.close_panel()
        else:
            self.ai_dock.first_open()
        self.ai_toolbar_button.setChecked(self.ai_dock.is_open())

    @staticmethod
    def _shift_combo(combo,delta):
        if combo.count():combo.setCurrentIndex((combo.currentIndex()+delta)%combo.count())

    def _shift_active_channel(self,delta):
        self._shift_combo(self.inspector.channel,delta)

    def _toggle_trace(self):
        self._shift_combo(self.inspector.trace,1)

    def _show_logs(self):
        self.log_dock.show()
        self.logs.tabs.setCurrentIndex(0)

    def _select_tool_slot(self,index):
        if 0<=index-1<self.browser.tools.count():
            self.browser.tabs.setCurrentIndex(1)
            self.browser.tools.setCurrentRow(index-1)
            self.browser.tools.scrollToItem(self.browser.tools.currentItem())

    def _select_relative_tool(self,delta):
        tools=self.browser.tools
        visible=[i for i in range(tools.count()) if not tools.item(i).isHidden()]
        if not visible:return
        row=tools.currentRow()
        if row not in visible:chosen=visible[0 if delta>0 else -1]
        else:
            at=visible.index(row)+delta
            if at<0 or at>=len(visible):return
            chosen=visible[at]
        self.browser.tabs.setCurrentIndex(1)
        tools.setCurrentRow(chosen)
        tools.scrollToItem(tools.item(chosen))

    def _shortcut_roi_tool(self,tool):
        # A tool can offer a generic line/rectangle/point; active modules can
        # further constrain the allowed selection types in their manifest.
        if tool!='pan' and self._active_module_id() and tool not in self._selection_config().get('tools',[]):
            self.statusBar().showMessage(f'{tool.capitalize()} is not available for this module')
            return
        self.viewer.set_roi_tool(tool)
        self._queue_live_preview()

    def _shortcut_directory(self):
        folder=paths.customization_dir()/'shortcuts'
        folder.mkdir(parents=True,exist_ok=True)
        return folder

    def _load_shortcuts(self):
        preferred=str(self.settings.value('shortcut_profile','default'))
        profiles=read_profiles(self._shortcut_directory(),canonicalize=normalize_key)
        profile=profiles.get(preferred) or profiles['default']
        self._apply_shortcuts(profile['name'],profile['bindings'])

    def _apply_shortcuts(self,name,bindings):
        # Validate the complete proposed map before changing any QAction.
        from ..core.shortcuts import validate_profile
        validated=validate_profile({'schema_version':1,'name':name,'bindings':bindings},
                                   canonicalize=normalize_key)
        self._shortcut_bindings=validated['bindings']
        self.settings.setValue('shortcut_profile',name)
        for id_,action in self._shortcut_actions.items():
            action.setShortcut(QKeySequence(self._shortcut_bindings.get(id_,'')))
            # Embedded modules share the host window. Restrict commands to this
            # module's focused descendants so hidden editors cannot steal them.
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self.addAction(action)
            action.setToolTip(ACTION_BY_ID[id_].label+': '+(self._shortcut_bindings[id_] or 'unbound'))
        self.module_panel.run_button.setText('Run analysis')
        self.module_panel.run_button.setToolTip('Run the selected analysis ('+(self._shortcut_bindings['tool.run'] or 'no shortcut')+')')
        self.prev_channel_button.setToolTip('Scroll left: '+self._shortcut_bindings['nav.channel_left'])
        self.next_channel_button.setToolTip('Scroll right: '+self._shortcut_bindings['nav.channel_right'])
        self.statusBar().showMessage(f'Keyboard shortcut profile: {ui_label(name)}',5000)
        self._watch_shortcut_files()

    def _setup_shortcut_watch(self):
        self._shortcut_watcher=QFileSystemWatcher(self)
        self._shortcut_reload_timer=QTimer(self)
        self._shortcut_reload_timer.setSingleShot(True)
        self._shortcut_reload_timer.setInterval(200)
        self._shortcut_reload_timer.timeout.connect(self._reload_shortcuts_from_disk)
        self._shortcut_watcher.directoryChanged.connect(lambda _:self._shortcut_reload_timer.start())
        self._shortcut_watcher.fileChanged.connect(lambda _:self._shortcut_reload_timer.start())
        self._watch_shortcut_files()

    def _watch_shortcut_files(self):
        if not hasattr(self,'_shortcut_watcher'):return
        paths_to_watch=[str(self._shortcut_directory())]
        active=self._shortcut_directory()/(str(self.settings.value('shortcut_profile','default'))+'.json')
        if active.is_file():paths_to_watch.append(str(active))
        old=set(self._shortcut_watcher.files()+self._shortcut_watcher.directories())
        new=set(paths_to_watch)
        if old-new:self._shortcut_watcher.removePaths(sorted(old-new))
        if new-old:self._shortcut_watcher.addPaths(sorted(new-old))

    def _reload_shortcuts_from_disk(self):
        name=str(self.settings.value('shortcut_profile','default'))
        profiles=read_profiles(self._shortcut_directory(),canonicalize=normalize_key)
        profile=profiles.get(name)
        if profile and profile['bindings']!=self._shortcut_bindings:
            self._apply_shortcuts(name,profile['bindings'])
            self.statusBar().showMessage('Reloaded shortcut file: '+name,4000)
        self._watch_shortcut_files()

    def open_shortcut_options(self):
        dialog=ShortcutOptions(self._shortcut_directory(),
                               str(self.settings.value('shortcut_profile','default')),self)
        self._shortcut_dialog=dialog
        dialog.bindingsChanged.connect(self._apply_shortcuts)
        dialog.exec()
        self._shortcut_dialog=None

    def import_shortcuts(self):
        dialog=ShortcutOptions(self._shortcut_directory(),
                               str(self.settings.value('shortcut_profile','default')),self)
        dialog.bindingsChanged.connect(self._apply_shortcuts)
        QTimer.singleShot(0,dialog.import_file)
        dialog.exec()

    def export_shortcuts(self):
        dialog=ShortcutOptions(self._shortcut_directory(),
                               str(self.settings.value('shortcut_profile','default')),self)
        dialog.bindingsChanged.connect(self._apply_shortcuts)
        QTimer.singleShot(0,dialog.export_file)
        dialog.exec()

    @staticmethod
    def _open_directory(path):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _theme_files(self):
        folder=paths.customization_dir()/'themes'
        folder.mkdir(parents=True,exist_ok=True)
        return sorted(folder.glob('*.json'))

    def _populate_theme_menu(self):
        menu=getattr(self,'_theme_menu',None)
        if menu is None:return
        menu.clear()
        current=str(self.settings.value('theme','graphite'))
        from PySide6.QtGui import QActionGroup
        group=QActionGroup(menu);group.setExclusive(True)
        for theme_path in self._theme_files():
            action=menu.addAction(ui_label(theme_path.stem))
            action.setCheckable(True);action.setChecked(theme_path.stem==current)
            group.addAction(action)
            action.triggered.connect(lambda checked=False,name=theme_path.stem:self._apply_theme(name))
        menu.addSeparator()
        menu.addAction('Import theme…',self.import_theme)
        menu.addAction('Open themes folder',lambda:self._open_directory(paths.customization_dir()/'themes'))

    def _apply_theme(self,name):
        """v0.8: every theme file goes through the one design system (shared.appearance)."""
        from ..core.presets import validate_theme
        from spm_studio.shared.appearance import apply_theme, is_dark, complete_tokens
        custom=paths.customization_dir()/'themes'
        legacy={'dark':'graphite','light':'porcelain','default_dark':'graphite','default_light':'porcelain'}
        if not (custom/f'{name}.json').is_file() and name in legacy:
            name=legacy[name]
        try:
            theme=read_json(custom/f'{name}.json',validate_theme)
        except Exception as exc:
            theme=THEMES.get(name,THEMES['graphite'])
            if (custom/f'{name}.json').exists():
                self._log(f'Theme {name} could not be read, using the default: {exc}',important=True)
        tokens=complete_tokens(theme)
        if os.environ.get('RS_EMBEDDED_QT')!='1':
            apply_theme(tokens)
            self.setStyleSheet('')
        else:
            from spm_studio.shared.appearance import stylesheet
            self.setStyleSheet(stylesheet(tokens))
        mark='spm-studio-mark-dark.png' if is_dark(tokens) else 'spm-studio-mark-light.png'
        icon_path=Path(__file__).resolve().parents[1]/'resources'/mark
        self.brand_mark.setPixmap(QPixmap(str(icon_path)))
        self.settings.setValue('theme',name)
        self._populate_theme_menu()
        self.viewer.update()
        self.interactive_palette.update()

    def _load_profiles(self):
        presets={'STM':dict(DEFAULT_PROFILE),
                 'KPFM':{**DEFAULT_PROFILE,'name':'KPFM','channel_contains':'Bias','visible_channels':['Z','Bias']},
                 'Multipass':{**DEFAULT_PROFILE,'name':'Multipass','channel_contains':'Z','multipass':True,
                              'visible_channels':['Z','Current','OC M1 Freq']}}
        # v0.0.5: a built-in profile removed in Settings › Library stays out of the list.
        removed=paths.removed_factory_items()
        presets={k:v for k,v in presets.items() if f'profiles/{k}.json' not in removed}
        profiles=paths.customization_dir()/'profiles'
        profiles.mkdir(parents=True,exist_ok=True)
        for p in sorted(profiles.glob('*.json')):
            try:presets[p.stem]=read_json(p,validate_profile)
            except Exception as exc:self._log(f'Invalid profile {p.name}: {exc}')
        self.profiles=presets
        self.profile_combo.clear()
        add_key_items(self.profile_combo,presets)
        self._fit_combo(self.profile_combo)

    def _load_colormaps(self):
        from ..core.display import PALETTES, read_colormap_csv
        from ..core.gwyddion_palettes import import_installed_gwyddion_gradients
        try:
            imported=import_installed_gwyddion_gradients(paths.customization_dir()/'colormaps')
            if imported:self._log(f'Imported {len(imported)} Gwyddion gradients for reuse in SPM Studio')
        except (OSError,ValueError) as exc:
            self._log('Gwyddion palette import skipped: '+str(exc))
        self.inspector.palette.clear()
        add_key_items(self.inspector.palette,list(PALETTES))
        folder=paths.customization_dir()/'colormaps'
        folder.mkdir(parents=True,exist_ok=True)
        for f in sorted(folder.iterdir()):
            if f.suffix.lower() not in ('.csv','.txt'):continue
            try:
                read_colormap_csv(f)
                self.inspector.palette.addItem(ui_label(f.stem),f.name)
                self.inspector.palette.setItemData(self.inspector.palette.count()-1,str(f),Qt.ItemDataRole.ToolTipRole)
            except Exception as exc:self._log(f'Ignored invalid palette {f.name}: {exc}')

    def _load_export_presets(self):
        from ..core.presets import validate_export
        presets={'single_column': dict(DEFAULT_EXPORT),
                 'double_column': {**DEFAULT_EXPORT,'name':'double_column','width_mm':178.,'height_mm':115.},
                 'square': {**DEFAULT_EXPORT,'name':'square','width_mm':100.,'height_mm':100.},
                 'triple': {**DEFAULT_EXPORT,'name':'triple','width_mm':178.,'height_mm':168.},
                 'custom': {**DEFAULT_EXPORT,'name':'custom','width_mm':140.,'height_mm':110.,'dpi':600}}
        folder=paths.customization_dir()/'export_presets'
        folder.mkdir(parents=True,exist_ok=True)
        for p in sorted(folder.glob('*.json')):
            try:presets[p.stem]=read_json(p,validate_export)
            except Exception as exc:self._log(f'Invalid export preset {p.name}: {exc}')
        self.export_presets=presets
        self.export_preset_combo.clear()
        add_key_items(self.export_preset_combo,presets)
        self._fit_combo(self.export_preset_combo)

    def import_export_preset(self):
        from ..core.presets import validate_export
        selected,_=QFileDialog.getOpenFileName(self,'Import export preset','','JSON (*.json)')
        if not selected:return
        try:
            data=read_json(selected,validate_export)
            target=paths.customization_dir()/'export_presets'/Path(selected).name
            if target.exists():raise FileExistsError('Export preset already exists')
            write_json(target,data,validate_export)
            self._load_export_presets()
            self._log(f'Imported {target}')
        except Exception as exc:self._log(str(exc),important=True)

    def import_theme(self):
        from ..core.presets import validate_theme
        selected,_=QFileDialog.getOpenFileName(self,'Import GUI theme','','JSON (*.json)')
        if not selected:return
        try:
            data=read_json(selected,validate_theme)
            target=paths.customization_dir()/'themes'/Path(selected).name
            if target.exists():raise FileExistsError('Theme already exists')
            write_json(target,{'schema_version':1,**data},lambda d:{'schema_version':1,**validate_theme(d)})
            self._apply_theme(target.stem)
            self._log(f'Theme imported and applied: {target.name}')
        except Exception as exc:self._log(str(exc),important=True)

    def _log(self,text,*,important=False,error=False):
        """Add a line to the Logs panel.

        v0.0.18: the panel only opens by itself for an ``error`` (a script that fails, a crash); an ``important``
        message marks the Logs button instead (dot + tooltip) so the user can open it when they want.
        """
        self.logs.add_log(str(text))
        if error:
            self.log_dock.show()
        elif important and not self.log_dock.isVisible():
            self._set_logs_attention(True,str(text))

    def _set_logs_attention(self,on,text=''):
        button=getattr(self,'logs_toolbar_button',None)
        if button is None:return
        if bool(button.property('attention'))!=bool(on):
            button.setProperty('attention',bool(on))
            button.style().unpolish(button);button.style().polish(button)
        base='Show / hide the Logs panel (run output and result files)'
        button.setToolTip(base+('\nNew message: '+text[:160] if on and text else ''))

    def _logs_open_on_run(self):
        return str(self.settings.value('logs/open_on_run',False)).lower() in ('true','1')

    @Slot(str)
    def _add_file(self,path):
        path=str(Path(path).resolve())
        if path in self._source_paths or path in self._removed_paths:return
        self._source_paths.append(path)
        item=QListWidgetItem(f'{Path(path).stem}   [{Path(path).suffix[1:].upper()}]')
        item.setToolTip(path)
        item.setData(Qt.ItemDataRole.UserRole,path)
        self.browser.files.addItem(item)
        self.browser.update_selection_actions()
        if self.browser.files.count()==1:self.browser.files.setCurrentItem(item)

    def _clear_active_scan(self):
        """Release displayed data and invalidate any pending asynchronous results."""
        self._load_token+=1
        self._process_token+=1
        self._multi_token+=1
        self._pending_proc_key=None
        self._pending_load_path=None
        self._process_timer.stop()
        self._live_timer.stop()
        self.scan=None
        self.processed=None
        self._update_scan_profile_indicator()
        self._crop_region=None
        self._crop_sources={}
        self._crop_applied.clear()
        self.interactive_palette.set_crop_active(False)
        self._update_crop_buttons()
        self._current_channel=None
        self._last_roi=None
        self._live_preview_roi=None
        self._preserve_view=False
        self._clear_secondary_views()
        self.viewer.clear_scan()
        self._interactive_preview_roi=None
        self._interactive_cursor=None
        self._interactive_points=[]
        self._interactive_timer.stop()
        self.interactive_palette.show_results({'lines':['Open a scan to use the tools.']})
        self.inspector.clear_scan()
        self.browser.metadata_panel.clear()
        self.module_panel.set_selections([])
        self.statusBar().showMessage('No scan selected • Open an SXM or GWY scan')

    def _view_request(self):
        if self.scan is None:
            return None
        return {
            'channel':self.inspector.channel.currentText(),
            'trace':self.inspector.selected_trace(),
            'visible':self.inspector.visible_channel_names(),
        }

    def remove_scan(self,path=None):
        """Remove one source from the session, never from the filesystem."""
        if isinstance(path,bool) or not path:
            item=self.browser.files.currentItem()
            path=item.data(Qt.ItemDataRole.UserRole) if item else None
        if not path:return
        path=str(Path(path).resolve())
        index=next((i for i in range(self.browser.files.count())
                    if self.browser.files.item(i).data(Qt.ItemDataRole.UserRole)==path),-1)
        if index<0:return
        was_active=(self.scan is not None and str(self.scan.path.resolve())==path)
        was_pending=(self.browser.files.currentRow()==index)
        if was_active:
            self._followup_view=self._view_request()
        self.cache.evict_scan(path)
        self._scan_view_states.pop(path,None)
        self._scan_profile_keys.pop(path,None)
        self._pending_bulk_profiles.discard(path)
        self.styles={key:value for key,value in self.styles.items() if key[0]!=path}
        self.pipelines={key:value for key,value in self.pipelines.items() if key[0]!=path}
        self._session_masks={key:value for key,value in self._session_masks.items() if key[0]!=path}
        self._removed_paths.add(path)  # prevent an active folder crawl from readding it
        self._source_paths=[p for p in self._source_paths if p!=path]
        if was_active or was_pending:
            self._clear_active_scan()
        file_list=self.browser.files
        # Removal must not briefly select/load a different, possibly hidden,
        # scan through QListWidget.currentItemChanged while the item is deleted.
        previous_block=file_list.blockSignals(True)
        try:
            item=file_list.takeItem(index)
            del item
        finally:
            file_list.blockSignals(previous_block)
        if was_pending:
            visible=[(i,file_list.item(i)) for i in range(file_list.count())
                     if not file_list.item(i).isHidden()]
            if visible:
                _,next_item=min(visible,key=lambda pair:(abs(pair[0]-index),pair[0]))
                file_list.setCurrentItem(next_item)
                # QListWidget may internally choose the next item during
                # takeItem even with signals blocked: load explicitly if needed.
                if self.scan is None and self._load_token and self._source_paths:
                    current_path=next_item.data(Qt.ItemDataRole.UserRole)
                    # If setCurrentItem emitted its signal, this would have
                    # started a load already; avoid duplicating the work.
                    if self._pending_load_path!=current_path:
                        self._load_file(current_path)
            else:
                file_list.setCurrentRow(-1)
        elif was_active and file_list.currentItem():
            self._load_file(file_list.currentItem().data(Qt.ItemDataRole.UserRole))
        if file_list.count()==0:
            self._followup_view=None
            self._clear_active_scan()
        self.browser.remove_file_button.setEnabled(file_list.currentItem() is not None)
        self._log(f'Removed {Path(path).name} from the session (source file untouched)')

    @Slot(str)
    def _crawler_failed(self,message):
        self._log(f'Dataset indexing failed: {message}',important=True)

    @Slot()
    def _crawler_finished(self):
        crawler=self.sender()
        if crawler in self._crawlers:
            self._crawlers.remove(crawler)
        self._log(f'Indexed dataset ({self.browser.files.count()} scans)')

    def open_file(self):
        selection,_=QFileDialog.getOpenFileNames(self,'Open SPM scans',str(self._dialog_folder),
                                                 'SPM files (*.sxm *.gwy)')
        for path in selection:
            self._removed_paths.discard(str(Path(path).resolve()))
            self._add_file(path)
        if selection:
            self._dialog_folder=Path(selection[0]).parent
            if self._session_folder is None:self._session_folder=self._dialog_folder
        self.browser.update_selection_actions()

    def open_folder(self):
        folder=QFileDialog.getExistingDirectory(self,'Open SPM dataset',str(self._dialog_folder))
        if not folder:return
        self._open_dataset_folder(folder)

    def _open_dataset_folder(self,folder):
        """Index every scan below ``folder`` (no image data loaded yet)."""
        self._dialog_folder=Path(folder)
        self._session_folder=Path(folder)
        self._removed_paths.clear()
        crawler=FileCrawler(folder)
        crawler.found.connect(self._add_file,Qt.ConnectionType.QueuedConnection)
        crawler.failed.connect(self._crawler_failed,Qt.ConnectionType.QueuedConnection)
        self._crawlers.append(crawler)
        crawler.finished.connect(self._crawler_finished,Qt.ConnectionType.QueuedConnection)
        crawler.start()
        self._log(f'Indexing {folder} (no image data loaded yet)…')

    def export_scan_selection(self,destination=None):
        """Copy the scans still listed (after 'Remove selected scan') into a folder and continue the
        session there, so later figure exports and script results land next to the selected scans.
        Original files are never touched.

        v0.0.5: the folder is chosen by the user (any location, any name, new or existing). The
        proposal is still the sibling ``<dataset>_scan_recap``. ``destination`` skips the dialog."""
        import shutil
        files=[Path(p) for p in dict.fromkeys(self._source_paths) if Path(p).is_file()]
        if not files:
            self._log('Open a dataset and keep the scans you want before exporting the selection',important=True)
            return
        source=Path(self._session_folder) if self._session_folder else files[0].parent
        if destination is None:
            from .recap_dialog import RecapFolderDialog
            proposal=paths.scan_recap_folder(source)
            if proposal==source:proposal=source.parent/(source.name+'_copy')
            remembered=str(self.settings.value('recap_location',''))
            if remembered and Path(remembered).is_dir():proposal=Path(remembered)/proposal.name
            dialog=RecapFolderDialog(proposal,len(files),self)
            try:
                if dialog.exec()!=dialog.DialogCode.Accepted:return
                recap=dialog.folder()
            finally:
                dialog.deleteLater()
            if recap is None:return
            self.settings.setValue('recap_location',str(recap.parent))
        else:
            recap=Path(destination)
        try:same=recap.resolve()==source.resolve()
        except OSError:same=recap==source
        if same:
            self._log(f'Already working in {recap}; nothing to copy',important=True)
            return
        try:
            recap.mkdir(parents=True,exist_ok=True)
            copied=[]
            for file in files:
                target=recap/file.name
                if file.resolve()==target.resolve():continue
                shutil.copy2(file,target)
                copied.append(target)
            manifest={'format':'spm-studio-scan-recap-v1','source_folder':str(source),
                      'exported':datetime.now().isoformat(timespec='seconds'),
                      'scans':[f.name for f in files]}
            (recap/'scan_recap.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
        except OSError as exc:
            self._log(f'Could not copy the scans to {recap}: {exc}',important=True)
            QMessageBox.warning(self,'Copy failed',f'Could not copy the scans to\n{recap}\n\n{exc}')
            return
        self._log(f'Exported {len(copied)} selected scan(s) to {recap}; the session now works in that folder',important=True)
        self._remember_scan_view()
        self._clear_active_scan()
        self.browser.files.clear()
        self._source_paths=[]
        self._open_dataset_folder(recap)

    def _remember_scan_view(self):
        """Snapshot navigation/UI state belonging to the currently active scan.

        Only in-memory views are saved; raw data and custom profiles are never
        written or overwritten. Called BEFORE switching the list selection.
        """
        if self.scan is None:
            return
        path=str(self.scan.path.resolve())
        view=self._view_request() or {}
        view['crop_region']=self._crop_region
        view['crop_applied']=set(self._crop_applied)
        view['channel_titles']=dict(self._channel_titles)
        view['profile_key']=self._scan_profile_keys.get(path)
        self._scan_view_states[path]=view

    def _load_file(self,path):
        if not path:return
        path=str(Path(path).resolve())
        active=str(self.scan.path.resolve()) if self.scan is not None else None
        if active:
            self._remember_scan_view()
        self._pending_load_path=path
        # A first-time scan opens independently; it MUST NOT inherit the
        # visible channels/profile of the scan that happened to be selected.
        self._pending_view_request=(dict(self._scan_view_states[path])
                                   if path in self._scan_view_states else {})
        self._followup_view=None
        self._load_token+=1
        token=self._load_token
        self._process_token+=1
        self._preserve_view=False
        try:
            st=Path(path).stat()
            key=(path,st.st_size,st.st_mtime_ns)
        except OSError as exc:
            self._log(str(exc),important=True)
            return
        self.browser.metadata_panel.set_loading(path)
        cached=self.cache.get(('scan',key))
        if cached is not None:
            self._last_loaded_at=0.0
            self._loaded(token,cached)
        else:
            self.statusBar().showMessage(f'Loading {Path(path).name}…')
            self._last_loaded_at=time.perf_counter()
            self._start_task(Task(token,read_scan,path),
                             lambda t,scan,key=key:self._loaded_cache(t,scan,key),
                             self._load_failed)

    def _start_task(self,task,on_done,on_error):
        """Dispatch background results to Qt's GUI thread via real QObject slots.

        Using a lambda as the direct receiver of a worker signal can execute
        QWidget updates in the worker thread under some PySide6 versions.
        Explicit queued QObject slots prevent that class of native GUI crashes.
        """
        task_id=id(task)
        task.signals.setProperty('task_id',task_id)
        self._active_tasks[task_id]=(task,on_done,on_error)
        task.signals.done.connect(self._task_done,Qt.ConnectionType.QueuedConnection)
        task.signals.failed.connect(self._task_failed,Qt.ConnectionType.QueuedConnection)
        self.pool.start(task)

    @Slot(int,object)
    def _task_done(self,token,result):
        sender=self.sender()
        task_id=sender.property('task_id') if sender else None
        item=self._active_tasks.get(task_id)
        if item is None:return
        try:
            item[1](token,result)
        except Exception:
            import traceback
            self._log('Unhandled result error:\n'+traceback.format_exc(),important=True)
        finally:
            self._active_tasks.pop(task_id,None)

    @Slot(int,str)
    def _task_failed(self,token,message):
        sender=self.sender()
        task_id=sender.property('task_id') if sender else None
        item=self._active_tasks.get(task_id)
        if item is None:return
        try:
            item[2](token,message)
        except Exception:
            import traceback
            self._log('Unhandled error handler:\n'+traceback.format_exc(),important=True)
        finally:
            self._active_tasks.pop(task_id,None)

    def _loaded_cache(self,token,scan,key):
        if token != self._load_token:
            return
        try:
            self.cache.put(('scan',key),scan)
            self._loaded(token,scan)
        except Exception:
            import traceback
            self._load_failed(token,traceback.format_exc())

    def _load_failed(self,token,message):
        if token==self._load_token:
            self._log(f'Failed to read scan:\n{message}',important=True)
            self.statusBar().showMessage('Scan loading failed')
            self.browser.metadata_panel.set_error(message)

    def _loaded(self,token,scan):
        if token!=self._load_token:return
        # A cached scan is immutable input. Session cropping must never mutate
        # that object or leak into another visit to the same file.
        self.scan=Scan(scan.path,dict(scan.channels),dict(scan.metadata),list(scan.warnings))
        self.browser.metadata_panel.set_scan(self.scan)
        self._crop_sources=dict(scan.channels)
        self._crop_region=None
        self._crop_applied.clear()
        self.interactive_palette.set_crop_active(False)
        self._update_crop_buttons()
        request=self._pending_view_request or {}
        # Restore the crop in coordinates of THIS scan's original raster.
        # Fresh scans have no crop; profiles never copy crops between scans.
        region=request.get('crop_region')
        if region is not None:
            self._crop_region=region
            for name in request.get('crop_applied',set()):
                if name in self.scan.channels:
                    self._ensure_session_crop(name)
            self.scan.metadata['session_crop']=region.to_dict()
            self.browser.metadata_panel.set_scan(self.scan)
        self.interactive_palette.set_crop_active(self._crop_region is not None)
        self._update_crop_buttons()
        self._channel_titles=dict(request.get('channel_titles',{}))
        scan_path=str(scan.path.resolve())
        profile_key=(self._scan_profile_keys.get(scan_path) if scan_path in self._pending_bulk_profiles
                     else request.get('profile_key') or self._scan_profile_keys.get(scan_path))
        old=self.profile_combo.blockSignals(True)
        try:
            # Show an independently selected profile for every scan. A fresh
            # file does not pretend to have the previous scan's preset applied.
            set_combo_key(self.profile_combo,profile_key if profile_key in self.profiles else 'STM')
        finally:self.profile_combo.blockSignals(old)
        self._displayed_run_id=None
        self._active_result_module_id=None
        self._pending_load_path=None
        self.processed=None
        elapsed=time.perf_counter()-self._last_loaded_at if self._last_loaded_at else 0
        if elapsed:
            self._log(f'Reader opened {scan.path.name} in {elapsed:.2f}s; preparing lightweight preview…')
        self.statusBar().showMessage(f'Preparing preview for {scan.path.name}…')
        self.viewer.fit()
        self.viewer.roi=None
        self.viewer.extra_rois.clear()
        self.viewer.mask_overlay=None
        self.viewer.overlays=[]
        self.viewer.tool_mask_overlay=None
        self.viewer.tool_points=[]
        self.viewer.tool_preview_image=None
        self.viewer.tool_preview_roi=None
        self._interactive_preview_roi=None
        self._interactive_points=[]
        self._interactive_cursor=None
        self._clear_secondary_views()
        self._last_roi=None
        self._pending_view_request=None
        self._current_channel=(request.get('channel') if request.get('channel') in scan.channels
                               else scan.preferred_channel())
        self.channel_scroll.horizontalScrollBar().setValue(0)
        self._syncing=True
        self.inspector.set_channels(self.scan,self._current_channel,request.get('trace'))
        requested=[name for name in request.get('visible',[]) if name in self.scan.channels]
        if self._current_channel not in requested:
            requested.insert(0,self._current_channel)
        self.inspector.set_visible_channels(requested,notify=False)
        self._syncing=False
        self._change_selection()
        self._preserve_view=False
        if str(self.scan.path.resolve()) in self._pending_bulk_profiles:
            # Apply after Inspector channels are populated, preserving the
            # existing scan-specific crop and unmodified raster data.
            self.apply_profile()
            self._pending_bulk_profiles.discard(str(self.scan.path.resolve()))
        self._update_scan_profile_indicator()
        self._log(f'Opened {scan.path.name} • {len(scan.channels)} channels')
        for msg in scan.warnings:self._log('⚠ '+msg)
        self.statusBar().showMessage(f'{scan.path.name} · {len(scan.channels)} channels')
        self.inspector.metadata.setText(f'{scan.path.name}\n{len(scan.channels)} channels\n'
                                        f'{scan.path.suffix.upper()[1:]} · {scan.channels[self._current_channel].geometry.shape}')
        current=self.browser.tools.currentItem()
        if current:self._show_module(current.data(Qt.ItemDataRole.UserRole))
        self._refresh_saved_runs()
        self._refresh_result_channels()

    def fit_all_views(self):
        """Reset zoom *and* translation of every displayed scan channel."""
        self.viewer.fit()
        for holder, view in self._secondary_views.values():
            view.fit()
        if self._result_view is not None and self._result_view.isVisible():
            preview=getattr(self._result_view,'preview',None)
            if preview is not None and hasattr(preview,'setZoomMode'):
                from .result_view import QPdfView
                if QPdfView is not None:
                    preview.setZoomMode(QPdfView.ZoomMode.FitInView)
        self.channel_scroll.viewport().update()

    def _clear_secondary_views(self):
        self._multi_token+=1
        for holder,_ in self._secondary_views.values():
            self.channel_layout.removeWidget(holder)
            holder.setParent(None)
            holder.deleteLater()
        self._secondary_views.clear()
        if self._result_view is not None:
            self.channel_layout.removeWidget(self._result_view)
            self._result_view.setParent(None)
            self._result_view.deleteLater()
            self._result_view=None
        self._result_records.clear()
        self._secondary_prepared.clear()
        self._secondary_pending.clear()

    def _sync_multiview(self,*args):
        if not hasattr(self,'channel_scroll') or self.scan is None:return
        selected=self.inspector.visible_channel_names()
        active=self.inspector.channel.currentText()
        if active not in selected:selected.insert(0,active)
        wanted=[x for x in selected if x!=active and x != self._current_channel and x in self.scan.channels]
        self._multi_token+=1
        self._secondary_prepared.clear()
        self._secondary_pending.clear()
        for channel in list(self._secondary_views):
            if channel not in wanted:
                holder,_=self._secondary_views.pop(channel)
                self.channel_layout.removeWidget(holder)
                holder.setParent(None);holder.deleteLater()
        for channel in wanted:
            # All displayed channels MUST use the same original-grid ROI.
            # This includes previews newly opened by Apply profile.
            self._ensure_session_crop(channel)
            if channel not in self._secondary_views:
                holder=QWidget()
                block=QVBoxLayout(holder);block.setContentsMargins(1,1,1,1)
                head=QLabel(channel)
                head.setObjectName('sectionTitle')
                head.setContentsMargins(4,2,4,2)
                view=ImageView(holder)
                holder.setMinimumWidth(460)
                view.setMinimumSize(420,260)
                view.set_roi_tool('pan')
                # Secondary previews activate the corresponding channel; the
                # full-resolution raster then opens in the editable primary view.
                view.activated.connect(lambda c=channel:self.inspector.channel.setCurrentText(c))
                view.plot_profile=self._plot_profile_for_run()
                view.cursorChanged.connect(self.statusBar().showMessage)
                block.addWidget(head);block.addWidget(view,1)
                self._secondary_views[channel]=(holder,view)
                self.channel_layout.addWidget(holder,1)
        # Keep script/live results LAST, after every ordinary scan channel.
        if self._result_view is not None:
            self.channel_layout.removeWidget(self._result_view)
            self.channel_layout.addWidget(self._result_view,1)
        # A script run adds its result as the final preview without replacing
        # the active original raster. Live molecule rendering uses this slot too.
        active_result=active if active in self.inspector.result_channels else None
        selected_result=next((x for x in selected if x in self.inspector.result_channels),None)
        chosen_result=active_result or selected_result
        module_id=(self.inspector.result_channels[chosen_result] if chosen_result
                   else self._active_result_module_id)
        if (self._result_view is not None and self._result_view.live and
                self._active_module_id()=='molecule_placement'):
            self._result_view.show()
        elif module_id in self._result_records:
            self._activate_result_channel(module_id)
        elif self._result_view is not None:
            self._result_view.hide()
        self._update_channel_navigation()
        # Widgets are cheap; images are prepared lazily only for the currently
        # visible strip and one neighbouring screen, not for every data channel.
        QTimer.singleShot(0,self._load_visible_channels)

    def _load_visible_channels(self):
        if self.scan is None or not self._secondary_views:
            return
        bar=self.channel_scroll.horizontalScrollBar()
        left=bar.value()
        span=max(1,self.channel_scroll.viewport().width())
        right=left+span
        padding=span // 2
        generation=self._multi_token
        for channel,(holder,view) in list(self._secondary_views.items()):
            x=holder.x()
            if x+holder.width()<left-padding or x>right+padding:
                continue
            if channel in self._secondary_prepared or channel in self._secondary_pending:
                continue
            trace=self.inspector.selected_trace()
            available=self.scan.channels[channel].traces
            if trace not in available:
                trace='forward' if 'forward' in available else next(iter(available))
            key=(str(self.scan.path),channel,trace)
            from ..core.display import PALETTES
            from ..core.plot_settings import default_viewer_palette
            palette=default_viewer_palette(channel,self._plot_profile_for_run())
            style=self.styles.get(key,replace(ImageStyle(),colormap=palette))
            try:
                raw=self.scan.channels[channel].get(trace)
            except (KeyError,ValueError) as exc:
                self._secondary_prepared.add(channel)
                self._log(f'Preview {channel}: {exc}')
                continue
            self._secondary_pending.add(channel)
            self._start_task(Task(generation,self._prepare_secondary,raw,self.pipelines.get(key,[]),style),
                lambda token,result,c=channel,tr=trace,st=style:self._secondary_ready(token,c,tr,st,result),
                lambda token,message,c=channel:self._secondary_failed(token,c,message))

    def _secondary_failed(self,token,channel,message):
        if token!=self._multi_token:return
        self._secondary_pending.discard(channel)
        self._secondary_prepared.add(channel)
        self._log(f'Preview {channel}: {message}')



    @staticmethod
    def _prepare_secondary(raw,steps,style):
        enabled=[step for step in steps if step.enabled and step.operation!='none']
        processed=apply(raw,enabled) if enabled else raw
        bound=preview_bounds(processed,style)
        rgb=render_rgb(processed,style,bound,max_dimension=850)
        return bound,rgb

    def _secondary_ready(self,token,channel,trace,style,result):
        if token!=self._multi_token or self.scan is None:return
        if channel not in self._secondary_views:return
        self._secondary_pending.discard(channel)
        self._secondary_prepared.add(channel)
        bounds,rgb=result
        view=self._secondary_views[channel][1]
        # The display is a thumbnail; no full data materialization is retained.
        key=(str(self.scan.path),channel,trace)
        view.set_scan(qimage_rgb(rgb),None,self.scan.channels[channel].geometry,
                      style,bounds,self.channel_title(channel),self.scan.channels[channel].unit,
                      preserve_view=True,display_zero=display_zero_enabled(self.pipelines.get(key,[])))

    def _update_channel_navigation(self):
        bar=self.channel_scroll.horizontalScrollBar()
        self.prev_channel_button.setEnabled(bar.value()>bar.minimum())
        self.next_channel_button.setEnabled(bar.value()<bar.maximum())

    def _scroll_channels(self,direction):
        bar=self.channel_scroll.horizontalScrollBar()
        step=max(280,int(self.channel_scroll.viewport().width()*0.75))
        bar.setValue(bar.value()+int(direction)*step)
        self._update_channel_navigation()

    def eventFilter(self,obj,event):
        """Global scan/channel navigation independent of which Studio pane owns focus.

        Qt popups and edit fields keep their native arrow-key behavior. Unlike
        the previous focus-based logic, changing the active scan does not
        require clicking the viewer before scrolling through channels again.
        """
        if (event.type()==QEvent.Type.Resize and hasattr(self,'channel_scroll')
                and obj is self.channel_scroll.viewport()):
            QTimer.singleShot(0,self._load_visible_channels)
        if event.type()!=QEvent.Type.KeyPress:
            return super().eventFilter(obj,event)
        if (obj is self.browser.files and event.key()==Qt.Key.Key_Delete
                and event.modifiers()==Qt.KeyboardModifier.NoModifier):
            self.remove_scan()
            return True
        app=QApplication.instance()
        if app.activeModalWidget() is not None or app.activePopupWidget() is not None:
            return super().eventFilter(obj,event)
        # Only intercept events targeting this MainWindow and its descendants.
        # This also prevents interfering with other windows/dialogs.
        if not isinstance(obj,QWidget) or not (obj is self or self.isAncestorOf(obj)):
            return super().eventFilter(obj,event)
        # Keep text editing, spin boxes and combo drop-downs usable. All other
        # panels, tabs, file and tool lists respond to navigation immediately.
        focus=app.focusWidget()
        if isinstance(focus,(QLineEdit,QTextEdit,QPlainTextEdit,QAbstractSpinBox)) or (
            isinstance(focus,QComboBox) and focus.view().isVisible()):
            return super().eventFilter(obj,event)
        from PySide6.QtGui import QKeySequence
        combo=QKeySequence(event.keyCombination()).toString(QKeySequence.SequenceFormat.PortableText)
        dispatch={
            self._shortcut_bindings['nav.scan_previous']:'nav.scan_previous',
            self._shortcut_bindings['nav.scan_next']:'nav.scan_next',
            self._shortcut_bindings['nav.channel_left']:'nav.channel_left',
            self._shortcut_bindings['nav.channel_right']:'nav.channel_right',
        }
        action=dispatch.get(combo) if combo else None
        if action=='nav.scan_previous':
            self.browser.select_relative_file(-1);return True
        if action=='nav.scan_next':
            self.browser.select_relative_file(1);return True
        if action=='nav.channel_left':
            self._scroll_channels(-1);return True
        if action=='nav.channel_right':
            self._scroll_channels(1);return True
        return super().eventFilter(obj,event)

    def _selection_key(self):
        if self.scan is None:return None
        channel=self.inspector.channel.currentText()
        if channel not in self.scan.channels:channel=self._current_channel
        return (str(self.scan.path),channel,self.inspector.selected_trace())

    def _change_selection(self):
        if self._syncing or self.scan is None:return
        channel=self.inspector.channel.currentText()
        if channel in self.inspector.result_channels:
            # Selecting the result channel immediately makes its PDFs visible.
            self.inspector.ensure_visible(channel)
            self._activate_result_channel(self.inspector.result_channels[channel])
            return
        if channel not in self.scan.channels:return
        # A channel newly selected after cropping inherits the exact same ROI.
        newly_cropped=self._ensure_session_crop(channel)
        if channel!=self._current_channel:
            old=self.scan.channels.get(self._current_channel)
            new=self.scan.channels[channel]
            if old and old.geometry.to_dict()!=new.geometry.to_dict():
                self.viewer.roi=None
                self.viewer.extra_rois.clear()
                self.viewer.mask_overlay=None
            self.inspector.update_traces(self.scan)
            self._current_channel=channel
            self.inspector.ensure_visible(channel)
        key=self._selection_key()
        self._syncing=True
        selected_style=self.styles.get(key)
        if selected_style is None:
            from ..core.display import PALETTES
            from ..core.plot_settings import default_viewer_palette
            selected_style=replace(ImageStyle(),colormap=default_viewer_palette(channel,self._plot_profile_for_run()))
        self.inspector.set_style(selected_style)
        try:self.module_panel.set_channel_title(self.channel_title(channel))
        except Exception:pass
        self.styles.setdefault(key,selected_style)
        self.inspector.set_steps(self.pipelines.get(key,[]))
        self._syncing=False
        self._preserve_view=not newly_cropped
        self._schedule_process()
        self._sync_multiview()
        self._interactive_preview_roi=None
        self._interactive_cursor=None
        self._interactive_timer.start()
        if self._active_interaction()=='histogram_masks':
            try:
                saved=self._session_masks.get(self._mask_settings_key(),[])
                self.module_panel.set_masks(saved)
            except (TypeError,ValueError):pass

    def _update_style(self):
        if self._syncing or self.scan is None:return
        try:
            style=self.inspector.get_style()
            # Check invalid ranges before storage.
            if style.gamma<=0 or style.range_mode in ('manual','percentile') and style.high<=style.low:
                raise ValueError('High must exceed low')
        except ValueError as exc:
            self.statusBar().showMessage(f'Invalid style values: {exc}')
            return
        self.styles[self._selection_key()]=style
        if self.processed is not None:
            self._render_current()

    def _update_steps(self):
        if self._syncing or self.scan is None:return
        self.pipelines[self._selection_key()]=self.inspector.steps()
        self._schedule_process()
        self._indicate_staleness()
        # Keep all simultaneously visible previews in sync with new legends.
        self._sync_multiview()

    def _apply_fix_zero_display(self):
        """Update only the legend; do not modify image pixels or contrast mode."""
        if self._syncing or self.scan is None:
            return
        self._schedule_process()
        self.statusBar().showMessage('Fix Zero: colourbar reference set to 0; original data and contrast unchanged')

    def _apply_all(self):
        if self.scan is None:return
        style=self.inspector.get_style()
        steps=self.inspector.steps()
        for name,ch in self.scan.channels.items():
            for tr in ch.traces:
                key=(str(self.scan.path),name,tr)
                self.styles[key]=style
                self.pipelines[key]=list(steps)
        self._log(f'Explicitly applied settings to {len(self.scan.channels)} channels of {self.scan.path.name}')

    def _schedule_process(self):
        self._process_token+=1
        self._process_timer.start()

    @staticmethod
    def _prepare_preview(raw, steps, style):
        """Run NumPy work off the Qt GUI thread, and only on selected raster.

        A fresh scan starts without any processing steps: no plane subtraction,
        fitting or copying. Full-resolution source data remain available for
        measurements/exports, but the preview is reduced to at most 1100 pixels.
        """
        active_steps=[s for s in steps if s.enabled and s.operation!='none']
        processed=apply(raw,active_steps) if active_steps else raw
        bnd=preview_bounds(processed,style)
        rgb=render_rgb(processed,style,bnd,max_dimension=1400)
        return processed, bnd, rgb

    def _process_selection(self):
        key=self._selection_key()
        if key is None:return
        _,name,direction=key
        scan=self.scan
        if name not in scan.channels:return
        try:
            raw=scan.channels[name].get(direction)
        except KeyError as exc:
            self._log(str(exc),important=True)
            return
        steps=self.pipelines.get(key,[])
        style=self.styles.get(key,ImageStyle())
        self._pending_proc_key=(scan.key(),name,direction,
                                json.dumps([asdict(s) for s in steps],sort_keys=True,default=str))
        token=self._process_token
        self.statusBar().showMessage(f'Preparing {name} ({direction}) preview…')
        started=time.perf_counter()
        self._start_task(Task(token,self._prepare_preview,raw,steps,style),
                         lambda t,result:self._preview_ready(t,result,started),
                         self._preview_failed)

    def _preview_failed(self,token,error):
        if token != self._process_token:return
        self._log('Preview failed:\n'+error,important=True)
        self.statusBar().showMessage('Could not render preview. See Logs for details.')

    def _preview_ready(self,token,result,started):
        if token!=self._process_token or self.scan is None:return
        processed,bnd,rgb=result
        self.processed=processed
        key=self._selection_key()
        if key is None:return
        _,channel,trace=key
        if channel not in self.scan.channels:return
        style=self.styles.get(key,ImageStyle())
        try:
            self.viewer.set_scan(qimage_rgb(rgb),processed,
                                 self.scan.channels[channel].geometry,style,bnd,self.channel_title(channel),
                                 self.scan.channels[channel].unit,
                                 preserve_view=self._preserve_view,
                                 display_zero=display_zero_enabled(self.pipelines.get(key,[])))
        except Exception as exc:
            self._log(f'Could not display preview: {exc}',important=True)
            return
        self._preserve_view=True
        self._queue_live_preview()
        self._interactive_refresh_mask_overlay()
        self._interactive_timer.start()
        self.statusBar().showMessage(
            f'{self.scan.path.name} · {channel} · {trace.upper()} · '
            f'{processed.shape[1]} × {processed.shape[0]} · preview {time.perf_counter()-started:.2f}s')

    def _render_current(self):
        # Styles also use worker-thread previews. Do not do full-image NumPy
        # allocations or percentiles in a Qt change handler / paint event.
        self._schedule_process()

    def open_line_profiles(self):
        if self.scan is None:
            QMessageBox.information(self,'Line profiles','Open a scan and draw at least one line first.');return
        from .multi_profile_dialog import MultiProfileDialog
        dlg=getattr(self,'_line_profile_dialog',None)
        if dlg is None or not dlg.isVisible():
            dlg=MultiProfileDialog(self);self._line_profile_dialog=dlg
        else:
            dlg._fill_channels();dlg.import_from_scan()
        dlg.show();dlg.raise_();dlg.activateWindow()

    def open_manual_molecules(self):
        if self.scan is None:
            QMessageBox.information(self,'Place molecules','Open a scan first.');return
        from .manual_molecule_dialog import ManualMoleculeDialog
        dlg=getattr(self,'_manual_molecule_dialog',None)
        if dlg is None:
            dlg=ManualMoleculeDialog(self);self._manual_molecule_dialog=dlg
        dlg.show();dlg.raise_();dlg.activateWindow();dlg.update_overlay()

    def _on_roi(self,roi):
        dlg=getattr(self,'_manual_molecule_dialog',None)
        if roi.kind=='point' and dlg is not None and dlg.isVisible() and dlg.place.isChecked():
            # v32: a click places a molecule; it is not a module selection.
            self.viewer.roi=None
            dlg.add_at_px(*roi.points_px[0])
            self.viewer.update()
            return
        self._last_roi=roi
        if roi.kind=='line' and getattr(self,'keep_lines',None) is not None and self.keep_lines.isChecked() \
           and not self._selection_config().get('multiple',False):
            # v32 multi-line mode: keep every line (distinct colours), all reach the tools.
            # roi is already assigned to viewer.roi by ImageView before this
            # signal. Append that new line exactly once, then keep the main slot
            # empty so future lines do not duplicate the previous one.
            self.viewer.extra_rois.append(roi)
            self.viewer.roi=None
            dlg=getattr(self,'_line_profile_dialog',None)
            if dlg is not None and dlg.isVisible():
                try:dlg.import_from_scan()
                except Exception:pass
        elif self._selection_config().get('multiple',False):
            self.viewer.extra_rois.append(roi)
            self.viewer.roi=None
        self._sync_selection_list()
        self.viewer.update()
        self._log(f'{roi.kind.title()} selection: {roi.points_px}')
        self._live_preview_roi=None
        self._queue_live_preview()
        self._interactive_capture(roi)
        self._indicate_staleness()

    def _preview_roi(self,roi):
        self._live_preview_roi=roi
        self._interactive_preview_roi=roi
        if not self._interactive_timer.isActive():self._interactive_timer.start()
        self._queue_live_preview()

    def _active_module_id(self):
        item=self.browser.tools.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else ''

    def _active_interaction(self):
        mod=self.modules.get(self._active_module_id())
        return mod.interaction if mod else 'none'

    def _on_roi_edited(self):
        selected=self.module_panel.selection_list.currentRow()
        self._sync_selection_list(selected)
        dlg=getattr(self,'_line_profile_dialog',None)
        if dlg is not None and dlg.isVisible():
            try:dlg.import_from_scan()
            except Exception:pass
        self._queue_live_preview()
        self._interactive_timer.start()
        self._indicate_staleness()

    def _selection_config(self):
        mod=self.modules.get(self._active_module_id())
        return mod.selection or {} if mod else {}

    def _sync_selection_list(self,selected=-1):
        rois=list(self.viewer.extra_rois)
        if self.viewer.roi is not None:rois.append(self.viewer.roi)
        self.module_panel.set_selections(rois,selected)
        self.viewer.selected_roi_index=self.module_panel.selection_list.currentRow()
        self.viewer.update()

    def _select_roi(self,index):
        self.viewer.selected_roi_index=index
        self.viewer.update()

    def _roi_clicked(self,index):
        """A click on a line / region in the scan selects it in the Selections list too."""
        lst=self.module_panel.selection_list
        lst.blockSignals(True)
        if 0<=index<lst.count():lst.setCurrentRow(index)
        lst.blockSignals(False)
        self.viewer.selected_roi_index=index
        names={i:name for i,_c,name in self.viewer.line_appearance()}
        label=names.get(index,f'selection {index+1}')
        self.statusBar().showMessage(f'{label} selected — press Delete (Suppr) to remove it',5000)
        self.viewer.update()

    def _choose_roi_tool(self,name):
        if name!='pan' and name not in self._selection_config().get('tools',[]):
            self._log(f'Selection tool {name} was not requested by this module',important=True)
            return
        self.viewer.set_roi_tool(name)
        self._queue_live_preview()

    def _delete_selection(self,index,fallback_last=False):
        """Delete exactly the selected line / region (v0.0.11: never another one).

        The remaining lines keep their colours; their default names are renumbered
        (L1, L2 …) in drawing order. Nothing is deleted when nothing is selected, unless
        ``fallback_last`` (Undo last) asks for the most recent selection.
        """
        all_rois=list(self.viewer.extra_rois)+([self.viewer.roi] if self.viewer.roi else [])
        if not all_rois:return
        if not 0<=index<len(all_rois):
            if not fallback_last:
                self.statusBar().showMessage('Click a line or a region on the scan to select it, then press Delete',
                                             5000)
                return
            index=len(all_rois)-1
        removed=all_rois[index]
        self.viewer.forget_roi(removed)
        if index<len(self.viewer.extra_rois):self.viewer.extra_rois.pop(index)
        else:self.viewer.roi=None
        self.viewer.renumber_lines()
        self._live_preview_roi=None
        dlg=getattr(self,'_line_profile_dialog',None)
        if dlg is not None:
            try:dlg.remove_points(self.viewer.line_key(removed))
            except Exception:pass
        self._sync_selection_list()
        # nothing stays selected, so a second Delete never removes a line by surprise
        self.module_panel.selection_list.blockSignals(True)
        self.module_panel.selection_list.setCurrentRow(-1)
        self.module_panel.selection_list.blockSignals(False)
        self.viewer.selected_roi_index=-1
        self.viewer.update()
        self._queue_live_preview()
        self._indicate_staleness()

    def _undo_line(self):
        self._delete_selection(len(self.viewer.extra_rois) if self.viewer.roi else len(self.viewer.extra_rois)-1,
                               fallback_last=True)

    def _clear_lines(self):
        self._live_preview_roi=None
        self.viewer.extra_rois.clear()
        self.viewer.roi=None
        self._sync_selection_list()
        self._queue_live_preview()
        self._indicate_staleness()

    def _queue_live_preview(self,*args):
        self._live_timer.start()

    def _mask_settings_key(self):
        if not self.scan:return ''
        channel=self.inspector.channel.currentText()
        return (str(self.scan.path),channel if channel in self.scan.channels else self._current_channel)

    def _on_masks_changed(self,*args):
        if self._active_interaction()=='histogram_masks' and self.scan:
            self._session_masks[self._mask_settings_key()]=[
                dict(mask) for mask in self.module_panel.masks]
        self._queue_live_preview()

    def _overlay_layers_for_current(self,skipped=None):
        """Same layers, order and geometry checks as the live overlay preview."""
        from ..core.channel_overlay import make_layers
        if skipped is None:skipped=[]
        params=self.module_panel.values()
        channel=self._selection_key()[1]
        direction=self._selection_key()[2]
        layers=make_layers(channel,self.processed,self.scan.channels[channel].unit,
                           [],lambda name:self.scan.channels[name].get(direction),
                           {name:c.unit for name,c in self.scan.channels.items()},params,
                           skip_duplicates=True,skipped=skipped)
        original_geo=self.scan.channels[channel].geometry
        for layer in layers[1:]:
            geo=self.scan.channels[layer.name].geometry
            if (geo.shape!=original_geo.shape or geo.size_m!=original_geo.size_m or
                geo.center_m!=original_geo.center_m or geo.angle_deg!=original_geo.angle_deg):
                raise ValueError(f'{layer.name}: scan geometry differs; alignment not assumed')
        return layers,original_geo,channel

    def _export_overlay_gif(self,options):
        """v29: layer-by-layer transparency sweep exported as a presentation GIF."""
        from PySide6.QtWidgets import QProgressDialog,QApplication
        from ..core.channel_overlay import save_overlay_animation
        if self.scan is None or self.processed is None:
            QMessageBox.information(self,'Overlay GIF','Open a scan first.');return
        skipped=[]
        try:
            layers,geo,channel=self._overlay_layers_for_current(skipped)
        except Exception as exc:
            QMessageBox.warning(self,'Overlay GIF',f'Cannot build the layers:\n{exc}');return
        base=Path(getattr(self,'last_export_dir',None) or Path(self.scan.path).parent)
        names='_'.join(l.name for l in layers).replace('/','-').replace(' ','')[:60]
        suggested=base/f'{Path(self.scan.path).stem}_overlay_{names}.gif'
        filename,_=QFileDialog.getSaveFileName(self,'Export animated overlay (GIF)',str(suggested),'GIF (*.gif)')
        if not filename:return
        dlg=QProgressDialog('Rendering frames…','',0,100,self)
        dlg.setWindowTitle('Overlay GIF');dlg.setCancelButton(None)
        dlg.setWindowModality(Qt.WindowModality.WindowModal);dlg.setMinimumDuration(0);dlg.show()
        def progress(v):
            dlg.setValue(int(v));QApplication.processEvents()
        try:
            files=save_overlay_animation(layers,geo,filename,progress=progress,**options)
        except Exception as exc:
            dlg.close();QMessageBox.critical(self,'Overlay GIF failed',f'{type(exc).__name__}: {exc}');return
        dlg.close()
        try:self.last_export_dir=Path(filename).parent
        except Exception:pass
        extra='' if (not options.get('also_mp4') or any(str(f).endswith('.mp4') for f in files)) \
            else '\n(MP4 skipped: ffmpeg not found — sudo apt install ffmpeg)'
        if skipped:
            extra+=('\n\nIgnored (chosen twice): '+', '.join(dict.fromkeys(skipped)))
        extra+='\n\nOrder bottom → top: '+' → '.join(l.name for l in layers)
        self._log('Overlay animation saved: '+', '.join(map(str,files)))
        QMessageBox.information(self,'Overlay GIF saved','Saved:\n'+'\n'.join(map(str,files))+extra)

    def _refresh_live_preview(self):
        if self.viewer.data is None or self.scan is None:return
        preview=self._selection_config().get('preview','none')
        mod=self.module_panel.module
        if mod is not None and mod.id=='channel_overlay':
            from ..core.channel_overlay import make_layers,composite
            from ..core.painting import qimage_rgb
            try:
                params=self.module_panel.values()
                channel=self._selection_key()[1]
                direction=self._selection_key()[2]
                layers=make_layers(channel,self.processed,self.scan.channels[channel].unit,
                                   [],lambda name:self.scan.channels[name].get(direction),
                                   {name:c.unit for name,c in self.scan.channels.items()},params,
                                   skip_duplicates=True)
                original_geo=self.scan.channels[channel].geometry
                for layer in layers[1:]:
                    geo=self.scan.channels[layer.name].geometry
                    if (geo.shape!=original_geo.shape or geo.size_m!=original_geo.size_m or
                        geo.center_m!=original_geo.center_m or geo.angle_deg!=original_geo.angle_deg):
                        raise ValueError(f'{layer.name}: scan geometry differs; alignment not assumed')
                rgb,_=composite(layers,max_dimension=900)
                full=qimage_rgb(rgb)
                self.viewer.mask_overlay=full
                self.viewer.update()
                size=self.module_panel.molecule_preview.size()
                pix=QPixmap.fromImage(full).scaled(max(80,size.width()-10),
                    max(100,size.height()-10),Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
                self.module_panel.molecule_preview.setPixmap(pix)
            except (ValueError,KeyError,IndexError,TypeError) as exc:
                self.viewer.mask_overlay=None
                self.viewer.update()
                self.module_panel.molecule_preview.setPixmap(QPixmap())
                self.module_panel.molecule_preview.setText('Preview: '+str(exc))
            return
        if preview=='molecule_placement':
            self.viewer.mask_overlay=None
            self.viewer.update()
            self._preview_molecule_placement()
            return
        if preview not in ('profiles','histogram'):
            self.viewer.mask_overlay=None
            self.viewer.update()
            return
        if preview=='profiles':
            from ..core.analysis_utils import profile_between
            rois=list(self.viewer.extra_rois)+([self.viewer.roi] if self.viewer.roi and self.viewer.roi.kind=='line' else [])
            if self._live_preview_roi and self._live_preview_roi.kind=='line':
                rois.append(self._live_preview_roi)
            lines=[]
            looks={id(self.viewer.all_rois()[i]):(c,n) for i,c,n in self.viewer.line_appearance()}
            for i,roi in enumerate(rois):
                if roi.kind!='line':continue
                _,yy=profile_between(self.viewer.data,*roi.points_px)
                xx=np.arange(len(yy))
                # Physical positions match the full-resolution image, not the preview.
                active_channel=self.inspector.channel.currentText()
                if active_channel not in self.scan.channels:active_channel=self._current_channel
                if self.scan.channels[active_channel].geometry.size_m:
                    from ..core.analysis_utils import profile_along,geometry_spacing
                    geom=self.scan.channels[active_channel].geometry
                    xx,yy=profile_along(self.viewer.data,roi.points_px,spacing=geometry_spacing(geom,1e9))
                colour,name=looks.get(id(roi),('#ffda55',f'Line {i+1}'))
                lines.append((name,xx,yy,colour))
            self.module_panel.preview.profiles(lines)
            self.viewer.mask_overlay=None
            self.viewer.update()
            return
        a=np.asarray(self.viewer.data)
        # Bounded preview computation: at most roughly 600 × 600 samples.
        stride=max(1,int(np.ceil(max(a.shape)/600)))
        sub=a[::stride,::stride]
        spatial_roi=(self._live_preview_roi if self._live_preview_roi is not None
                     and self._live_preview_roi.kind=='rectangle' else self.viewer.roi)
        if spatial_roi is not None and spatial_roi.kind=='rectangle':
            (x0,y0),(x1,y1)=spatial_roi.points_px
            ys=slice(max(0,int(min(y0,y1)/stride)), min(sub.shape[0],int(max(y0,y1)/stride)+1))
            xs=slice(max(0,int(min(x0,x1)/stride)), min(sub.shape[1],int(max(x0,x1)/stride)+1))
            values=sub[ys,xs]
        else:values=sub
        try:bins=int(self.module_panel.widgets['bins'].value())
        except (KeyError,AttributeError):bins=130
        masks=self.module_panel.masks
        self.module_panel.preview.histogram(values,bins,masks,self.module_panel.mask_list.currentRow())
        # Transparent, displayed-only overlay: raw numbers remain unchanged.
        rgba=np.zeros((*sub.shape,4),dtype=np.uint8)
        from PySide6.QtGui import QColor
        for index,m in enumerate(masks):
            try:
                interval=(self.module_panel.preview._temporary
                          if index==self.module_panel.mask_list.currentRow()
                          else None)
                low,high=interval if interval is not None else (m['low'],m['high'])
                mask=np.isfinite(sub)&(sub>=low)&(sub<=high)
                c=QColor(m.get('color','#f0bb6e'))
                rgba[mask,0]=c.red()
                rgba[mask,1]=c.green()
                rgba[mask,2]=c.blue()
                rgba[mask,3]=115
            except (KeyError,TypeError,ValueError):pass
        if masks:
            if spatial_roi is not None and spatial_roi.kind=='rectangle':
                spatial=np.zeros(sub.shape,dtype=bool)
                spatial[ys,xs]=True
                rgba[~spatial,3]=0
            rgba=np.ascontiguousarray(rgba)
            self.viewer.mask_overlay=QImage(rgba.data,sub.shape[1],sub.shape[0],
                    4*sub.shape[1],QImage.Format.Format_RGBA8888).copy()
        else:self.viewer.mask_overlay=None
        self.viewer.update()

    def _ensure_result_preview(self):
        if self._result_view is None:
            self._result_view=ResultPreview(self.channel_content)
            self.channel_layout.addWidget(self._result_view,1)
        elif self.channel_layout.indexOf(self._result_view)>=0:
            self.channel_layout.removeWidget(self._result_view)
            self.channel_layout.addWidget(self._result_view,1)
        self._result_view.show()
        self._update_channel_navigation()
        return self._result_view

    def _show_live_molecule_preview(self,message=None,image=None):
        preview=self._ensure_result_preview()
        if image is not None:preview.set_live_image(image,message or 'Calibrated SVG overlay')
        else:preview.set_live_message(message or 'Select artwork to start preview')

    def _stop_molecule_preview(self):
        self._molecule_preview_pending=None
        process=getattr(self,'_molecule_preview_process',None)
        if process is not None:
            process.kill()
            process.waitForFinished(1000)
            self._molecule_preview_process=None

    def _preview_worker_output(self):
        import base64
        proc=getattr(self,'_molecule_preview_process',None)
        if proc is None:return
        self._molecule_preview_buffer+=bytes(proc.readAllStandardOutput())
        while b'\n' in self._molecule_preview_buffer:
            line,_,self._molecule_preview_buffer=self._molecule_preview_buffer.partition(b'\n')
            try:response=json.loads(line)
            except (TypeError,ValueError):continue
            if response.get('sequence')!=getattr(self,'_molecule_preview_seq',-1):continue
            if not response.get('ok'):
                self._show_live_molecule_preview('Molecule preview: '+str(response.get('message','Unknown error')))
                continue
            try:
                raw=base64.b64decode(response['image_png_base64'])
                image=QImage.fromData(raw,'PNG')
                if image.isNull():raise ValueError('Worker returned unreadable PNG')
                description=(f"{response['count']} calibrated molecule sites · rotation "
                             f"{response['rotation_deg']:.2f}°" +
                    (' · positions sampled for live responsiveness' if response.get('site_sampling') else ''))
                art=response.get('artwork_scale') or {}
                if art:
                    try:
                        pitch=response.get('nm_per_pixel') or [0,0]
                        description+=(f" · artwork {art['visible_molecule_px'][0]}×{art['visible_molecule_px'][1]} px"
                                      f"{' (margins trimmed)' if art.get('trimmed') else ''}"
                                      f" · scan {float(pitch[0])*1000:.1f} pm/px")
                    except (KeyError,IndexError,TypeError,ValueError):pass
                self._show_live_molecule_preview(description,image)
            except (ValueError,KeyError,TypeError) as exc:
                self._show_live_molecule_preview('Preview display error: '+str(exc))

    def _preview_molecule_placement(self):
        """Nonblocking calibrated preview from the selected module's worker process."""
        active=self.modules.get(self._active_module_id())
        if active is None or active.id!='molecule_placement':return
        values=self.module_panel.values()
        if not values.get('molecule_image','').strip():
            self._show_live_molecule_preview('Run Lattice measurements and select SVG/PNG artwork to see a live overlay.')
            return
        if not active.builtin and str(self.settings.value('trusted_module_'+active.id,''))!='yes':
            self._show_live_molecule_preview('Approve execution of the selected script for live previews.')
            return
        process=getattr(self,'_molecule_preview_process',None)
        if process is None or process.state()==QProcess.ProcessState.NotRunning:
            executable=active.path/'preview_worker.py'
            if not executable.is_file():
                self._show_live_molecule_preview('Preview worker is missing from the module folder.')
                return
            process=QProcess(self)
            process.setWorkingDirectory(str(active.path))
            process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
            process.readyReadStandardOutput.connect(self._preview_worker_output)
            process.started.connect(self._flush_molecule_preview_request)
            self._molecule_preview_process=process
            self._molecule_preview_buffer=b''
            process.start(sys.executable,[str(executable)])
        self._molecule_preview_seq=getattr(self,'_molecule_preview_seq',0)+1
        command={'sequence':self._molecule_preview_seq,
                 'scan_path':str(self.scan.path), 'parameters':values,
                 'session_crop':self.scan.metadata.get('session_crop'),
                 # v0.8: live preview in the colormap / contrast set on the scan
                 'plot_config':{'schema_version':1,'viewer_config':self.viewer_config_for_run()}}
        self._molecule_preview_pending=(json.dumps(command,ensure_ascii=False)+'\n').encode('utf8')
        self._flush_molecule_preview_request()

    def _flush_molecule_preview_request(self):
        process=getattr(self,'_molecule_preview_process',None)
        pending=getattr(self,'_molecule_preview_pending',None)
        if process is not None and pending is not None and process.state()==QProcess.ProcessState.Running:
            process.write(pending)
            self._molecule_preview_pending=None

    def open_plot_options(self):
        dialog=PlotOptions(self,self.settings)
        if dialog.exec():
            self.viewer.plot_profile=self._plot_profile_for_run()
            self.viewer.update()
            for _,view in self._secondary_views.values():
                view.plot_profile=self._plot_profile_for_run()
                view.update()
            self._sync_multiview()
            self._log('Scientific plot style: '+str(self.settings.value('plot_style'))+
                      '; format: '+str(self.settings.value('plot_format')))

    def _plot_profile_for_run(self):
        profiles,errors=available_styles(paths.customization_dir()/'plot_styles')
        for issue in errors:self._log('Plot style warning: '+issue)
        name=str(self.settings.value('plot_style','Clean publication'))
        profile=dict(profiles.get(name,DEFAULT_PLOT))
        # v30: one global switch for transparent figure backgrounds (Options).
        profile['transparent_background']=self.export_transparent()
        # v32: Options › Figure customization applies to every script figure
        from .plot_options import load_figure_customization
        profile.update(load_figure_customization(self.settings))
        return profile

    def channel_title(self,channel):
        """Colourbar title of a channel: the user's title, else the default ($V_{exc}$ for excitation)."""
        from ..core.plot_settings import default_channel_title, clean_title
        return clean_title(self._channel_titles.get(channel) or default_channel_title(channel))

    def all_channel_titles(self):
        return {name:self.channel_title(name) for name in (self.scan.channels if self.scan else {})}

    def _tool_title_edited(self,text):
        if self.scan is None:return
        channel=self._selection_key()[1]
        if text:self._channel_titles[channel]=text
        else:self._channel_titles.pop(channel,None)
        self.module_panel.set_channel_title(self.channel_title(channel))
        self._schedule_process()

    def _export_preset_for_run(self):
        """v0.8: the export preset selected in the main window, used by script figures."""
        try:
            preset=dict(self.export_presets[combo_key(self.export_preset_combo)])
        except Exception:
            preset=dict(DEFAULT_EXPORT)
        # Same rule as the Export dialog: never below 1200 DPI.
        preset['dpi']=max(1200,int(preset.get('dpi',1200)))
        return preset

    def viewer_config_for_run(self):
        """v34: what the user set on each channel (colormap, range, title) for the tools.

        v0.8: always passed (script figures must look like the scan); the
        'use scan display' switch only decides whether contrast/title follow the viewer.
        """
        if self.scan is None:return {}
        from ..core.display import lut
        from ..core.plot_settings import default_viewer_palette
        key=self._selection_key();channels={}
        for name,obj in self.scan.channels.items():
            trace=key[2] if key[2] in obj.traces else next(iter(obj.traces))
            style=self.styles.get((str(self.scan.path),name,trace))
            if name==key[1]:
                try:style=self.inspector.get_style()
                except Exception:pass
            if style is None:
                style=replace(ImageStyle(),colormap=default_viewer_palette(name,self._plot_profile_for_run()))
            try:table=lut(style.colormap).tolist()
            except Exception:continue
            channels[name]={'colormap':style.colormap,'lut':table,'title':self.channel_title(name),
                            'range_mode':style.range_mode,'low':float(style.low),'high':float(style.high),
                            'gamma':float(style.gamma),'scale_bar':bool(style.scale_bar),'colorbar':bool(style.colorbar)}
        return {'enabled':True,'channels':channels,'export_preset':self._export_preset_for_run()}

    def export_transparent(self)->bool:
        return str(self.settings.value('export_transparent','false')).lower()=='true'

    def set_export_transparent(self,value:bool):
        self.settings.setValue('export_transparent','true' if value else 'false')

    def _plot_formats_for_run(self):
        # v0.8: SVG only by default; PDF / PNG are opt-in in Options › Results.
        from .plot_options import script_formats
        return script_formats(self.settings)

    def _clear_roi(self):
        self.viewer.roi=None
        self.viewer.extra_rois.clear()
        self._live_preview_roi=None
        self._sync_selection_list()
        self._queue_live_preview()
        self.viewer.set_roi_tool('pan')
        self._last_roi=None

    # ----------------------------------------------------------------------
    # Native, Gwyddion-inspired interactive image tools.  These do not change
    # the original SXM/GWY arrays, and operate on the active processed channel.
    # ----------------------------------------------------------------------
    def _interactive_current_roi(self):
        return self.viewer.roi or (self.viewer.extra_rois[-1] if self.viewer.extra_rois else None)

    def _interactive_mask(self, create=False):
        if self.scan is None or self.viewer.data is None:return None
        key=self._selection_key()
        mask=self._interactive_masks.get(key)
        if mask is not None and mask.shape!=self.viewer.data.shape:
            self._interactive_masks.pop(key,None);mask=None
        if mask is None and create:
            mask=np.zeros(self.viewer.data.shape,dtype=bool)
            self._interactive_masks[key]=mask
        return mask

    def _interactive_refresh_mask_overlay(self):
        mask=self._interactive_mask()
        if mask is None or not mask.any():
            self.viewer.tool_mask_overlay=None
            self.viewer.update()
            return
        # Reuse the same physical area when preview images are downsampled.
        # At most 1400 pixels on the long dimension for responsive painting.
        stride=max(1,int(np.ceil(max(mask.shape)/1400)))
        sub=mask[::stride,::stride]
        rgba=np.zeros((*sub.shape,4),dtype=np.uint8)
        rgba[sub]=[75,218,135,105]
        rgba=np.ascontiguousarray(rgba)
        self.viewer.tool_mask_overlay=QImage(rgba.data,sub.shape[1],sub.shape[0],
                sub.shape[1]*4,QImage.Format.Format_RGBA8888).copy()
        self.viewer.update()

    def _interactive_select(self,tool_id):
        self._interactive_preview_roi=None
        self._interactive_cursor=None
        self._interactive_points=[]
        self.viewer.tool_points=[]
        self.viewer.tool_preview_image=None
        self.viewer.tool_preview_roi=None
        mode=TOOL_BY_ID[tool_id].selection
        self.viewer.set_roi_tool(mode)
        self._interactive_timer.start()

    def _interactive_cursor_move(self,point):
        if self.interactive_palette.current not in ('read_value','channel_values'):
            return
        self._interactive_cursor=point
        if not self._interactive_timer.isActive():self._interactive_timer.start()

    def _interactive_capture(self,roi):
        if roi is None:return
        tool=self.interactive_palette.current
        self._interactive_preview_roi=None
        if tool=='three_point' and roi.kind=='point':
            self._interactive_points=(self._interactive_points+[roi.points_px[0]])[-3:]
            self.viewer.tool_points=list(self._interactive_points)
            self.viewer.update()
        elif tool=='mask' and roi.kind=='rectangle':
            self._interactive_mask_rectangle(roi,include=True)
        elif tool=='grain_remove' and roi.kind=='point':
            self._interactive_remove_grain(roi)
        elif tool=='spot_remove' and roi.kind=='point':
            self._interactive_action('apply')
        if not self._interactive_timer.isActive():self._interactive_timer.start()

    def _interactive_mask_rectangle(self,roi,include=True):
        if roi is None or roi.kind!='rectangle' or self.viewer.data is None:return
        mask=self._interactive_mask(create=True)
        ys,xs=roi_slice(mask.shape,roi)
        mask[ys,xs]=bool(include)
        self._interactive_refresh_mask_overlay()

    def _interactive_remove_grain(self,roi):
        mask=self._interactive_mask()
        if mask is None or not mask.any():return
        point=point_pixel(roi,mask.shape)
        if point is None or not mask[point[1],point[0]]:return
        from scipy.ndimage import label
        components,_=label(mask)
        selected=components[point[1],point[0]]
        if selected:mask[components==selected]=False
        self._interactive_refresh_mask_overlay()

    def _interactive_update(self):
        if self.viewer.data is None or self.scan is None:
            self.interactive_palette.show_results({'lines':['Open a scan to use the image tools.']})
            return
        tool=self.interactive_palette.current
        roi=self._interactive_preview_roi or self._interactive_current_roi()
        if self.viewer.tool_preview_image is not None and tool not in ('filter','color_range'):
            self.viewer.tool_preview_image=None
            self.viewer.tool_preview_roi=None
            self.viewer.update()
        if tool in ('read_value','channel_values') and self._interactive_cursor:
            roi=ROI('point',(self._interactive_cursor,))
        channels=None
        if tool=='channel_values':
            # Channel data may have different physical fields; only arrays with
            # matching raster geometry can be compared at a common pixel.
            channels={name:c.get('forward' if 'forward' in c.traces else next(iter(c.traces)))
                      for name,c in self.scan.channels.items()
                      if (c.geometry.shape==self.viewer.geometry.shape and
                          c.geometry.size_m==self.viewer.geometry.size_m and
                          c.geometry.center_m==self.viewer.geometry.center_m and
                          c.geometry.angle_deg==self.viewer.geometry.angle_deg)}
        try:
            result=measure(tool,self.viewer.data,self.viewer.geometry,roi,
                           points=self._interactive_points,mask=self._interactive_mask(),channels=channels)
        except (ValueError,IndexError,TypeError,RuntimeError) as exc:
            result={'lines':[str(exc)]}
        ready=(tool=='three_point' and len(self._interactive_points)==3) or (
            tool in ('path_level','radial') and roi is not None and roi.kind=='line') or (
            tool in ('crop','mask','color_range','filter') and roi is not None and roi.kind=='rectangle') or (
            tool in ('grain_remove','spot_remove') and roi is not None and roi.kind=='point')
        self.interactive_palette.show_results(result,ready=ready)
        if tool in ('filter','color_range') and roi is not None and roi.kind=='rectangle':
            try:
                ys,xs=roi_slice(self.viewer.data.shape,roi)
                source_roi=np.asarray(self.viewer.data[ys,xs])
                # The overlay is only a display preview; cap its dimensions
                # while keeping full-resolution data for the final Apply.
                stride=max(1,int(np.ceil(max(source_roi.shape)/950)))
                a=np.asarray(source_roi[::stride,::stride],dtype=float)
                image_data=a
                if tool=='filter':
                    from scipy.ndimage import gaussian_filter
                    finite=np.isfinite(a)
                    if finite.any():
                        fill=float(np.nanmedian(a))
                        filtered=gaussian_filter(np.where(finite,a,fill),
                            max(.08,self.interactive_palette.filter_sigma.value()/stride))
                        filtered[~finite]=np.nan
                        image_data=filtered
                else:
                    finite=a[np.isfinite(a)]
                    image_data=a
                if tool=='filter' and np.isfinite(a).any() or (tool=='color_range' and finite.size>=2 and finite.max()>finite.min()):
                    style=self.viewer.style
                    color_bounds=self.viewer.bounds
                    if tool=='color_range':
                        color_bounds=(float(finite.min()),float(finite.max()))
                    self.viewer.tool_preview_image=qimage_rgb(render_rgb(image_data,style,
                        fixed_bounds=color_bounds,max_dimension=850))
                    self.viewer.tool_preview_roi=roi
                    self.viewer.update()
            except (ValueError,TypeError,OverflowError):
                self.viewer.tool_preview_image=None
                self.viewer.tool_preview_roi=None
        elif self.viewer.tool_preview_image is not None:
            self.viewer.tool_preview_image=None
            self.viewer.tool_preview_roi=None
            self.viewer.update()

    def _interactive_append_step(self,operation,params):
        if self.scan is None:return
        # Use public processing-list API, preserving the user's other steps.
        self.inspector.set_steps(self.inspector.steps()+[ProcessingStep(operation,dict(params))])
        self._log(f'Interactive tool added non-destructive step: {operation}')

    def _ensure_session_crop(self, channel: str) -> bool:
        """Lazily crop an opened channel using the reference ROI.

        False means already prepared, no crop active, or incompatible geometry.
        """
        if self.scan is None or self._crop_region is None or channel in self._crop_applied:
            return False
        source=self._crop_sources.get(channel)
        if source is None:
            return False
        try:
            self.scan.channels[channel]=crop_channel(source,self._crop_region)
        except CropAlignmentError as exc:
            self._log('Crop alignment: '+str(exc),important=True)
            return False
        self._crop_applied.add(channel)
        return True

    def _refresh_crop_views(self):
        if self.scan is None:return
        self._process_token+=1
        self._multi_token+=1
        self._secondary_prepared.clear()
        self._secondary_pending.clear()
        self.viewer.fit()
        for _,view in self._secondary_views.values():
            view.fit()
        self._preserve_view=False
        self.viewer.roi=None
        self.viewer.extra_rois.clear()
        self.viewer.mask_overlay=None
        self.viewer.tool_preview_image=None
        self.viewer.tool_preview_roi=None
        self.viewer.tool_mask_overlay=None
        self._last_roi=None
        self._interactive_preview_roi=None
        self._interactive_points=[]
        self.viewer.tool_points=[]
        self._sync_selection_list()
        self.interactive_palette.set_crop_active(self._crop_region is not None)
        self._update_crop_buttons()
        self._interactive_timer.start()
        self._schedule_process()
        self._sync_multiview()
        self._queue_live_preview()  # Re-render placement at the updated physical ROI.
        active=self.inspector.channel.currentText()
        if active in self.scan.channels:
            g=self.scan.channels[active].geometry
            self.inspector.metadata.setText(f'{self.scan.path.name}\n'
                f'{len(self.scan.channels)} channels\n{g.shape[1]} × {g.shape[0]} px'
                + (' · cropped' if self._crop_region else ''))

    def _crop_selected_region(self,roi):
        if self.scan is None or self.viewer.geometry is None or roi is None or roi.kind!='rectangle':
            raise ValueError('Draw a rectangle on the scan first')
        channel=self.inspector.channel.currentText()
        if channel not in self.scan.channels:return
        # A second crop further restricts the same physical region.
        previous=self._crop_region
        if previous is not None and channel not in self._crop_applied:
            self._ensure_session_crop(channel)
        region=CropRegion.from_roi(roi,self.scan.channels[channel].geometry,previous)
        if region.right-region.left<1e-9 or region.bottom-region.top<1e-9:
            raise ValueError('Crop region is empty')
        self._crop_region=region
        # Recompute the displayed channels from ORIGINAL arrays, not already
        # cropped/levelled previews. Unopened channels inherit this ROI lazily.
        # Existing profiles remain keyed to original scan + channel + trace.
        previously=set(self._crop_applied)
        visible={n for n in self.inspector.visible_channel_names() if n in self.scan.channels}
        self._crop_applied.clear()
        for name in previously|visible|{channel}:
            self._ensure_session_crop(name)
        self.scan.metadata['session_crop']=region.to_dict()
        self.browser.metadata_panel.set_scan(self.scan)
        self._refresh_crop_views()
        crop_size=self.scan.channels[channel].geometry.shape
        self._log(f'Shared crop applied: {crop_size[1]} × {crop_size[0]} pixels on {channel}; '
                  'visible channels synchronized and newly opened channels inherit the same ROI. '
                  'Existing profiles remain unchanged.',important=True)

    def auto_crop_incomplete(self,interactive=False)->bool:
        """v32: crop all channels to the measured block of a partial scan.

        Returns True when a crop was applied, False when the scan is complete
        (dimensions untouched).  Uses forward and backward traces together.
        """
        from ..core.cropping import detect_incomplete_scan
        from ..core.models import ROI
        if self.scan is None:return False
        channel=self.inspector.channel.currentText()
        if channel not in self.scan.channels:return False
        if self._crop_region is not None and channel not in self._crop_applied:
            self._ensure_session_crop(channel)
        obj=self.scan.channels[channel]
        arrays=[obj.get(t) for t in obj.traces]
        try:
            box=detect_incomplete_scan(*arrays)
        except ValueError as exc:
            self._log(f'Auto-crop: {exc}',important=True)
            if interactive:QMessageBox.warning(self,'Auto-crop incomplete scan',str(exc))
            return False
        if box is None:
            msg='Scan is complete: no unmeasured area found, original dimensions kept.'
            self._log('Auto-crop: '+msg)
            if interactive:self.statusBar().showMessage(msg,6000)
            return False
        top,bottom,left,right=box
        ny,nx=obj.geometry.shape
        roi=ROI('rectangle',((float(left),float(top)),(float(right-1),float(bottom-1))))
        self._crop_selected_region(roi)
        self._log(f'Auto-crop: incomplete scan → kept rows {top}–{bottom-1} and columns {left}–{right-1} '
                  f'of {ny}×{nx} px ({(bottom-top)*(right-left)/(ny*nx)*100:.0f} % of the frame). '
                  'Use Reset crop to undo.',important=True)
        return True

    def _crop_other_channels(self):
        if self.scan is None or self._crop_region is None:return
        completed=[]
        for name in self._crop_sources:
            if self._ensure_session_crop(name):completed.append(name)
        self._refresh_crop_views()
        self._log(f'Applied the same physical crop to {len(completed)} additional channels; '
                  f'{len(self._crop_applied)} channel(s) now cropped.',important=True)

    def _reset_session_crop(self):
        if self.scan is None or self._crop_region is None:return
        self.scan.channels.update(self._crop_sources)
        self._crop_region=None
        self._crop_applied.clear()
        self.scan.metadata.pop('session_crop',None)
        self.browser.metadata_panel.set_scan(self.scan)
        self._refresh_crop_views()
        self._log('Original scan extents restored. Processing profiles and source data preserved.',important=True)

    def _interactive_action(self,action):
        if action=='preview':
            self._interactive_timer.start();return
        tool=self.interactive_palette.current
        if action=='crop_all':
            self._crop_other_channels()
            return
        if action=='crop_reset':
            self._reset_session_crop()
            return
        if action=='clear_selection':
            self._interactive_points=[];self._interactive_preview_roi=None
            self.viewer.tool_points=[]
            self.viewer.tool_preview_image=None;self.viewer.tool_preview_roi=None
            self.viewer.roi=None;self.viewer.extra_rois.clear()
            self._sync_selection_list();self.viewer.update()
            self._interactive_timer.start();return
        if self.scan is None or self.viewer.data is None:return
        if action in ('subtract_mask','clear_mask','invert_mask'):
            mask=self._interactive_mask(create=(action!='clear_mask'))
            if mask is not None:
                if action=='clear_mask':mask.fill(False)
                elif action=='invert_mask':np.logical_not(mask,out=mask)
                elif action=='subtract_mask' and self._interactive_current_roi() is not None:
                    self._interactive_mask_rectangle(self._interactive_current_roi(),include=False)
                self._interactive_refresh_mask_overlay()
            self._interactive_timer.start();return
        if action!='apply':return
        roi=self._interactive_current_roi()
        try:
            if tool=='mask':
                self._interactive_mask_rectangle(roi,True)
            elif tool=='grain_remove':
                self._interactive_remove_grain(roi)
            elif tool=='three_point':
                if len(self._interactive_points)!=3:raise ValueError('Choose three points first')
                three_point_plane_coefficients(self.viewer.data,self._interactive_points)
                self._interactive_append_step('three_point_plane',{
                    f'{axis}{i}':float(point[j]) for i,point in enumerate(self._interactive_points,1)
                    for j,axis in enumerate(('x','y'))})
            elif tool=='path_level':
                if roi is None or roi.kind!='line':raise ValueError('Select a line')
                (x0,y0),(x1,y1)=roi.points_px[0],roi.points_px[-1]
                self._interactive_append_step('path_plane',dict(x0=x0,y0=y0,x1=x1,y1=y1))
            elif tool=='spot_remove':
                point=point_pixel(roi,self.viewer.data.shape)
                if point is None:raise ValueError('Select a pixel')
                self._interactive_append_step('spot_replace',dict(x=point[0],y=point[1],radius=2))
            elif tool=='filter':
                self._interactive_append_step('gaussian',dict(sigma=self.interactive_palette.filter_sigma.value()))
            elif tool=='color_range':
                if roi is None or roi.kind!='rectangle':raise ValueError('Select a rectangle')
                ys,xs=roi_slice(self.viewer.data.shape,roi)
                subset=self.viewer.data[ys,xs]
                good=subset[np.isfinite(subset)]
                if good.size<2 or good.max()<=good.min():raise ValueError('Area has no usable contrast')
                style=replace(self.inspector.get_style(),range_mode='manual',low=float(good.min()),high=float(good.max()))
                self.inspector.set_style(style)
                self.styles[self._selection_key()]=style
                self._schedule_process()
            elif tool=='crop':
                self._crop_selected_region(roi)
            else:return
        except (ValueError,TypeError,KeyError,IndexError) as exc:
            self._log('Interactive tool: '+str(exc),important=True)
        self._interactive_timer.start()

    def _open_in_gwyddion(self):
        """Open Gwyddion and re-import the edited GWY result when possible."""
        if self.scan is None:
            self._log('Load a scan before opening Gwyddion',important=True)
            return
        executable=shutil.which('gwyddion')
        if not executable:
            QMessageBox.information(self,'Gwyddion not installed',
                'Install Gwyddion to access its full processing catalogue. '
                'Studio will then try to re-import a saved .gwy file when Gwyddion closes.')
            return
        source=Path(self.scan.path)
        start_ts=time.time()
        candidates_before={str(p):p.stat().st_mtime for p in source.parent.glob('*.gwy') if p.is_file()}
        self._gwyddion_process=QProcess(self)
        self._gwyddion_process.setProgram(executable)
        self._gwyddion_process.setArguments([str(source)])
        def _finished(*_):
            try:
                candidates=[p for p in source.parent.glob('*.gwy') if p.is_file()]
                target=None
                if source.suffix.lower()=='.gwy' and source.is_file() and source.stat().st_mtime >= start_ts-1:
                    target=source
                else:
                    changed=[p for p in candidates if p.stat().st_mtime >= start_ts-1 or str(p) not in candidates_before]
                    same_stem=[p for p in changed if p.stem.startswith(source.stem)]
                    target=max((same_stem or changed), key=lambda x:x.stat().st_mtime, default=None)
                if target is not None:
                    self._log('Re-importing Gwyddion result: '+str(target))
                    self._add_files([str(target)])
                    self.browser.select_file(str(target))
                else:
                    self._log('Gwyddion closed. No updated .gwy file was found to import.')
            except Exception as exc:
                self._log('Gwyddion re-import failed: '+str(exc),important=True)
        self._gwyddion_process.finished.connect(_finished)
        self._gwyddion_process.errorOccurred.connect(lambda *_:self._log('Cannot start Gwyddion',important=True))
        self._gwyddion_process.start()
        if not self._gwyddion_process.waitForStarted(3000):
            self._log('Cannot start Gwyddion',important=True)
            return
        self._log('Opened scan in Gwyddion. Save your processing as a .gwy file; Studio will try to import it when Gwyddion closes.')

    def _clear_cache(self):
        self.cache.clear()
        self._log('In-memory cache cleared')

    @staticmethod
    def _match_profile_channel(fragment, channel):
        """Match Nanonis channel spellings plus known older controller names.

        Exact aliases avoid confusing torsional Excitation_2 with M1 Excitation.
        """
        import re
        clean=lambda x:re.sub(r'[^a-z0-9]', '', str(x).lower())
        key=clean(fragment)
        candidate=clean(channel)
        aliases={
            'z':{'z','zm','topography'},
            'ocm1freq':{'frequencyshift','frequencyshift1','ocm1freqshift'},
            'ocm1excitation':{'excitation','excitation1','ocm1excitation'},
            'ocm2freq':{'frequencyshift2','ocm2freqshift'},
            'ocm2excitation':{'excitation2','ocm2excitation'},
        }
        if key in aliases and candidate in aliases[key]:return True
        return bool(key) and key in candidate

    def _update_scan_profile_indicator(self):
        path=str(self.scan.path.resolve()) if self.scan is not None else None
        key=self._scan_profile_keys.get(path) if path else None
        profile=self.profiles.get(key) if key else None
        if hasattr(self,'scan_profile_label'):
            self.scan_profile_label.setText('Scan profile: '+str(profile.get('name',key)) if profile else 'Scan profile: none')
            self.scan_profile_label.setVisible(bool(profile))   # v0.8: chip only when a profile is applied

    def apply_profile(self):
        if self.scan is None:return
        selected_key=combo_key(self.profile_combo)
        profile=self.profiles.get(selected_key)
        if not profile:return
        self.tutorial_event('profile_applied')
        self._scan_profile_keys[str(self.scan.path.resolve())]=selected_key
        self._update_scan_profile_indicator()
        needle=profile.get('channel_contains','').strip()
        candidate=(next((name for name in self.scan.channels
                        if self._match_profile_channel(needle,name)),None) if needle else None)
        if candidate and candidate!=self.inspector.channel.currentText():
            self.inspector.channel.setCurrentText(candidate)
        # Apply the profile to each matched channel and available trace.  The
        # other channels and their existing independent settings are untouched.
        channel_styles=profile.get('channel_styles') or {}
        channel_steps=profile.get('channel_processing') or {}
        channel_titles=profile.get('channel_titles') or {}
        self._syncing=True
        if channel_styles or channel_steps:
            for channel, obj in self.scan.channels.items():
                matched_style=next((v for fragment,v in channel_styles.items()
                    if self._match_profile_channel(fragment,channel)),None)
                matched_steps=next((v for fragment,v in channel_steps.items()
                    if self._match_profile_channel(fragment,channel)),None)
                if matched_style is None and matched_steps is None:continue
                for trace in obj.traces:
                    key=(str(self.scan.path),channel,trace)
                    if matched_style is not None:self.styles[key]=ImageStyle(**matched_style)
                    if matched_steps is not None:
                        self.pipelines[key]=[ProcessingStep(**x) for x in matched_steps]
            for channel in self.scan.channels:
                title=next((v for fragment,v in channel_titles.items()
                     if self._match_profile_channel(fragment,channel)),None)
                if title is not None:self._channel_titles[channel]=title
        else:
            key=self._selection_key()
            self.styles[key]=ImageStyle(**profile['style'])
            self.pipelines[key]=[ProcessingStep(**s) for s in profile.get('processing',[])]
        key=self._selection_key()
        self.inspector.set_style(self.styles.get(key,ImageStyle(**profile['style'])))
        self.inspector.set_steps(self.pipelines.get(key,[]))
        self._syncing=False
        requested=profile.get('visible_channels',[])
        resolved=[]
        multipass=bool(profile.get('multipass'))
        from ..core import scan_parameters as scan_params
        passes=scan_params.passes_in_scan(self.scan) if multipass else []
        for requested_name in requested:
            exact=next((n for n in self.scan.channels if n.lower()==requested_name.lower()),None)
            if multipass and passes:
                # Every pass of the requested channel ([P1] Z, [P2] Z …), in pass order.
                matches=[n for n in self.scan.channels
                         if self._match_profile_channel(requested_name,scan_params.channel_base(n))]
                matches.sort(key=lambda n:(scan_params.pass_of_channel(n) or 0))
                for match in matches:
                    if match not in resolved:resolved.append(match)
                continue
            match=exact or next((n for n in self.scan.channels
                                 if self._match_profile_channel(requested_name,n)),None)
            if match and match not in resolved:resolved.append(match)
        if multipass:
            self._apply_multipass_titles(passes)
        current=self.inspector.channel.currentText()
        if current not in resolved:resolved.insert(0,current)
        # Applying a profile never reloads the original raster. Ensure every
        # channel selected by that profile has the same session crop first.
        if self._crop_region is not None:
            for name in resolved:
                self._ensure_session_crop(name)
        self.inspector.set_visible_channels(resolved)
        # Existing secondary previews may have been prepared with old settings.
        self._secondary_prepared.clear()
        self._secondary_pending.clear()
        self._multi_token+=1
        if profile.get('auto_crop_incomplete') and self.profile_autocrop.isChecked():
            try:self.auto_crop_incomplete(interactive=False)
            except Exception as exc:self._log(f'Auto-crop skipped: {exc}')
        self._schedule_process()
        self._sync_multiview()

    def _apply_multipass_titles(self,passes):
        """Multipass profile: titles say which pass a channel belongs to, and the log lists
        what was changed in each pass (bias, setpoint, Δz … read from the header)."""
        from ..core import scan_parameters as scan_params
        for channel in self.scan.channels:
            n=scan_params.pass_of_channel(channel)
            if n is None:continue
            base=self._channel_titles.get(channel)
            if base is None:
                from ..core.plot_settings import default_channel_title
                base=default_channel_title(scan_params.channel_base(channel))
            if not str(base).startswith(f'P{n} · '):
                self._channel_titles[channel]=f'P{n} · {base}'
        params=scan_params.parameters(self.scan)
        if not passes:
            self._log('Multipass profile: this scan has no [P1]/[P2] channels or Multipass configuration.')
            return
        for n in passes:
            items=[p for p in params if p.group==f'P{n}' and p.key.split('.',1)[1] in
                   ('bias','setpoint','z_offset','playback','time_per_line')]
            text=', '.join(p.line() for p in items) or 'no configuration in the header'
            self._log(f'Multipass P{n}: {text}')

    def apply_profile_to_all_files(self):
        """Assign selected profile across the current file list, without loading files.

        Unlike automatic propagation, this is a deliberate, confirmed operation.
        Per-scan crops, ROIs, source images and user-saved presets are untouched.
        """
        selected=combo_key(self.profile_combo)
        profile=self.profiles.get(selected)
        files=list(dict.fromkeys(self._source_paths))
        if not profile:
            QMessageBox.warning(self,'No profile','Select a valid profile first.')
            return
        if not files:
            QMessageBox.information(self,'No files','Open scans or a dataset folder first.')
            return
        answer=QMessageBox.question(
            self,'Apply profile to all files?',
            f'Apply "{profile.get("name",selected)}" to all {len(files)} scans currently '
            'listed in the Files panel?\n\n'
            'Changes are limited to this session. Original SXM/GWY files and '
            'saved profile JSON files will not be modified. Scans not yet opened '
            'will receive the selected profile when visited.',
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer!=QMessageBox.StandardButton.Yes:
            return
        current=str(self.scan.path.resolve()) if self.scan is not None else None
        for path in files:
            self._scan_profile_keys[path]=selected
            saved=self._scan_view_states.get(path)
            if saved is not None:
                saved['profile_key']=selected
            if path!=current:
                self._pending_bulk_profiles.add(path)
        if current in files:
            self.apply_profile()
            self._pending_bulk_profiles.discard(current)
        self._log(f'Profile "{selected}" assigned to {len(files)} listed scans (lazy for unopened files).')
        self.statusBar().showMessage(f'Applied profile "{profile.get("name",selected)}" to {len(files)} listed scans',7000)

    def open_print3d(self):
        """v0.0.12: printable relief (STL / STEP) with a 3D colour bar and a live 3D preview."""
        try:
            old=getattr(self,'_print3d_dialog',None)
            if old is not None and old.isVisible():
                old.raise_();old.activateWindow();return
            from .print3d_dialog import create_tool
            dialog=create_tool(self)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose,True)
            dialog.destroyed.connect(lambda *_:setattr(self,'_print3d_dialog',None))
            self._print3d_dialog=dialog
            dialog.show()
            dialog.raise_()
        except Exception as exc:
            import traceback
            self._log('3D print tool could not start:\n'+traceback.format_exc(),important=True)
            QMessageBox.warning(self,'3D print unavailable',str(exc))

    def open_bias_figure_composer(self):
        """Open the native read-only bias/scan publication composer."""
        try:
            from .bias_figure_composer import create_tool
            root=(self.scan.path.parent if self.scan is not None else self._dialog_folder)
            context={'root':str(root),'output_dir':str(self.last_export_dir)}
            old=self._bias_figure_dialog
            if old is not None and old.isVisible():
                old.raise_();old.activateWindow();return
            dialog=create_tool(self,context)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose,True)
            dialog.destroyed.connect(lambda *_:setattr(self,'_bias_figure_dialog',None))
            self._bias_figure_dialog=dialog
            dialog.show()
            dialog.raise_()
        except Exception as exc:
            import traceback
            self._log('Bias composer could not start:\n'+traceback.format_exc(),important=True)
            QMessageBox.warning(self,'Spectroscopy figure composer unavailable',str(exc))

    def save_profile(self):
        """Persist exactly the visible channels with their separate processing and display.

        Data are never copied into profiles. Channel fragments are used again when
        selecting a different scan with the same acquisition channel names.
        """
        if self.scan is None:
            QMessageBox.information(self, 'Save profile', 'Open a scan first.')
            return
        name,ok=QInputDialog.getText(self,'Save multi-channel profile','Profile name')
        if not ok or not name.strip():return
        safe=''.join(c if c.isalnum() or c in '-_' else '_' for c in name.strip()).strip('_')
        if not safe:
            QMessageBox.warning(self,'Invalid profile','Please choose a name containing letters or numbers.')
            return
        active=self.inspector.channel.currentText()
        visible=[name for name in self.inspector.visible_channel_names() if name in self.scan.channels]
        if active in self.scan.channels and active not in visible:visible.insert(0,active)
        channel_styles={}
        channel_processing={}
        channel_titles={}
        for channel_name in visible:
            obj=self.scan.channels[channel_name]
            direction=self.inspector.selected_trace()
            if direction not in obj.traces:
                direction='forward' if 'forward' in obj.traces else next(iter(obj.traces))
            key=(str(self.scan.path),channel_name,direction)
            # Always read Inspector values for the selected channel, including
            # changes made moments before Save profile was clicked.
            style=self.inspector.get_style() if channel_name==active else self.styles.get(key,ImageStyle())
            steps=self.inspector.steps() if channel_name==active else self.pipelines.get(key,[])
            channel_styles[channel_name]=asdict(style)
            channel_processing[channel_name]=[asdict(step) for step in steps]
            channel_titles[channel_name]=self.channel_title(channel_name)
        style=self.inspector.get_style()
        data={'schema_version':1,'name':name.strip(),'style':asdict(style),
              'processing':[asdict(step) for step in self.inspector.steps()],
              'channel_contains':active if active in self.scan.channels else '',
              'visible_channels':visible,'channel_styles':channel_styles,
              'channel_processing':channel_processing,'channel_titles':channel_titles}
        try:
            dest=paths.customization_dir()/'profiles'/f'{safe}.json'
            if dest.exists() and QMessageBox.question(self,'Overwrite profile?',
                f'{dest.name} exists. Replace it?')!=QMessageBox.StandardButton.Yes:
                return
            write_json(dest,data,validate_profile)
            self._load_profiles()
            set_combo_key(self.profile_combo,safe)
            self._log(f'Saved profile with {len(visible)} channel settings: {dest}',important=True)
            self.statusBar().showMessage(f'Profile saved: {name.strip()}',6000)
        except Exception as exc:
            self._log(f'Cannot save profile: {exc}',important=True)
            QMessageBox.warning(self,'Save failed',str(exc))

    def import_profile(self):
        path,_=QFileDialog.getOpenFileName(self,'Import profile','','JSON files (*.json)')
        if not path:return
        try:
            data=read_json(path,validate_profile)
            dest=paths.customization_dir()/'profiles'/Path(path).name
            if dest.exists():raise FileExistsError(f'{dest} already exists; rename first')
            write_json(dest,data,validate_profile)
            self._load_profiles()
            self._log(f'Imported profile {dest}')
        except Exception as exc:self._log(str(exc),important=True)

    def import_gwyddion_gradients(self):
        """Optional import of all installed gradients from a user-picked Gwyddion folder."""
        from ..core.gwyddion_palettes import import_gwyddion_directory
        folder=QFileDialog.getExistingDirectory(self,'Select Gwyddion gradients folder (e.g. /usr/share/gwyddion/gradients)')
        if not folder:return
        try:
            imported=import_gwyddion_directory(Path(folder),paths.customization_dir()/'colormaps')
            self._load_colormaps()
            self._log(f'Imported {len(imported)} color gradients from {folder}',important=True)
            QMessageBox.information(self,'Gwyddion colors',f'Imported {len(imported)} color gradients. They are now available in the Colormap list.')
        except (OSError,ValueError) as exc:
            QMessageBox.warning(self,'Could not import Gwyddion gradients',str(exc))

    def import_colormap(self):
        from ..core.display import read_colormap_csv
        path,_=QFileDialog.getOpenFileName(self,'Import RGB(A) colormap','','Text/CSV (*.csv *.txt)')
        if not path:return
        try:
            read_colormap_csv(path)
            out=paths.customization_dir()/'colormaps'/Path(path).name
            out.parent.mkdir(parents=True,exist_ok=True)
            if out.exists():raise FileExistsError('Colormap filename exists; rename source')
            shutil.copy2(path,out)
            self._load_colormaps()
            set_combo_key(self.inspector.palette,out.name)
            self._log(f'Imported and activated colormap {out}')
        except Exception as exc:self._log(f'Invalid colormap: {exc}',important=True)

    def export_current(self,targets=None):
        if self.scan is None:
            self._log('Open a scan before exporting',important=True)
            return
        key=self._selection_key()
        preset=self.export_presets[combo_key(self.export_preset_combo)]
        two_columns=combo_key(self.export_preset_combo)=='double_column'
        # Both original raster results and PDF reports are valid independent
        # publication panels; never restrict double-column export to PDFs.
        exportable={'.pdf','.svg','.png','.jpg','.jpeg'}
        reports=[]
        for record, files in self._result_records.values():
            reports.extend(str(f) for f in files if Path(f).is_file() and Path(f).suffix.lower() in exportable)
        if self._result_view is not None:
            reports.extend(str(f) for f in self._result_view.files
                           if Path(f).is_file() and Path(f).suffix.lower() in exportable)
        visible_root=self.scan.path.parent/'SPM_Studio_Results'/self.scan.path.stem
        for section in ('Images','Plots'):
            folder=visible_root/section
            if folder.is_dir():
                for suffix in exportable:reports.extend(str(f) for f in folder.glob('*'+suffix))
        # v0.0.5: other scans of the Files list can be placed in the same figure.
        current_path=str(Path(self.scan.path).resolve())
        others=[]
        for other in dict.fromkeys(self._source_paths):
            try:
                if Path(other).is_file() and str(Path(other).resolve())!=current_path:
                    others.append((f'Other scan · {Path(other).name}',str(other)))
            except OSError:
                continue
        dialog=PublicationDialog(self.scan,dict.fromkeys(reports),two_columns=two_columns,
                                  selected_channel=key[1],selected_trace=key[2],
                                  channel_titles=self.all_channel_titles(),preset=preset,
                                  layout_name=combo_key(self.export_preset_combo),parent=self,
                                  transparent=self.export_transparent(),
                                  arrangement=str(self.settings.value('export_triple_arrangement','triangle')),
                                  formats=[f for f in str(self.settings.value('export_formats_v34','svg')).split(',') if f],
                                  other_scans=others,scan_loader=read_scan)
        # A profile saved from the dialog is listed and selected at once (no restart).
        dialog.profileSaved.connect(self._export_profile_saved)
        if dialog.exec()!=dialog.DialogCode.Accepted:return
        formats=dialog.formats() or ['svg']
        self.settings.setValue('export_formats_v34',','.join(formats))
        self.set_export_transparent(dialog.transparent_background())
        if dialog._n_panels()==3:self.settings.setValue('export_triple_arrangement',dialog.arrangement())
        selected=dialog.selection()
        if not selected:return
        self.tutorial_event('export')
        preset=dialog.resolved_preset()
        for spec in selected:
            if spec['kind']=='report' and spec.get('colorbar_source'):
                reference_name=spec['colorbar_source']
                reference=self.scan.channels[reference_name]
                direction=self.inspector.selected_trace()
                if direction not in reference.traces:direction=next(iter(reference.traces))
                ref_key=(str(self.scan.path),reference_name,direction)
                spec['trace']=direction
                spec['colorbar_steps']=self.pipelines.get(ref_key,[])
                spec['colorbar_style']=self.styles.get(ref_key,ImageStyle(colormap='gray'))
            if spec['kind']!='channel':continue
            channel=spec['channel']
            direction=spec['trace']
            from ..core.plot_settings import default_viewer_palette
            if spec.get('scan_path'):
                # Panel of another listed scan: use the display already set on that scan, if any.
                other=spec['scan_path']
                candidates=[(other,channel,direction)]
                try:candidates.append((str(Path(other).resolve()),channel,direction))
                except OSError:pass
                found=next((c for c in candidates if c in self.styles or c in self.pipelines),candidates[0])
                spec['steps']=self.pipelines.get(found,[])
                spec['style']=self.styles.get(found) or replace(ImageStyle(),colormap=default_viewer_palette(channel,self._plot_profile_for_run()))
                continue
            if direction not in self.scan.channels[channel].traces:
                self._log(f'{channel} does not have a {direction} trace',important=True)
                return
            selection=(str(self.scan.path),channel,direction)
            spec['steps']=self.pipelines.get(selection,[])
            spec['style']=self.styles.get(selection) or replace(ImageStyle(),colormap=default_viewer_palette(channel,self._plot_profile_for_run()))
            # Respect active preview annotations without adding any axis labels.
            if channel==key[1] and direction==key[2]:
                overlays=list(self.viewer.overlays)
                rois=list(self.viewer.extra_rois)+([self.viewer.roi] if self.viewer.roi is not None else [])
                for roi in rois:
                    if (roi.kind=='rectangle' and len(roi.points_px)==2) or \
                       (roi.kind=='line' and len(roi.points_px)>=2):
                        line_style=self.viewer.line_styles.get(tuple(map(tuple,roi.points_px)))
                        color=(self.viewer.line_color_of(roi) if roi.kind=='line' else '#ffda55')
                        width=(line_style[2] if roi.kind=='line' and line_style and len(line_style)>2 else 2)
                        overlay={'type':'rectangle' if roi.kind=='rectangle' else 'line',
                                 'points_px':[list(p) for p in roi.points_px],
                                 'color':color,'width':width}
                        if roi.kind=='line' and line_style and len(line_style)>2:
                            overlay['width_mode']='scan'
                        overlays.append(overlay)
                spec['overlays']=overlays
        folder=self.scan.path.parent/'selection'
        folder.mkdir(exist_ok=True)
        name='_'.join(spec['channel'].replace('/','_') if spec['kind']=='channel'
                      else 'lattice_result' if spec['kind']=='lattice' else 'analysis_result'
                      for spec in selected)
        # v33: the formats ticked in the dialog (PDF / PNG / SVG) are all written with this name.
        suggested=folder/f'{self.scan.path.stem}_{name}.{formats[0]}'
        chosen=' + '.join(f.upper() for f in formats)
        figure_filter=f"Figure: {chosen} ({' '.join('*.'+f for f in formats)})"
        filters=(figure_filter
                 + (';;Numerical NumPy (*.npy);;Numerical CSV (*.csv)' if len(selected)==1 and selected[0]['kind']=='channel' else ''))
        # v0.0.8: the figure can also (or only) go to the LaTeX editor, a presentation and/or Overleaf.
        from spm_studio.documents import settings as doc_settings
        send_to=None
        if targets or doc_settings.any_enabled():
            from spm_studio.documents.ui.send_dialog import SendDialog
            preset=dict(targets or {})
            if targets:preset.setdefault('folder',False)
            send=SendDialog(self.documents,self,preset=preset,title='Export the figure to…')
            if send.exec()!=send.DialogCode.Accepted:return
            send_to=send.targets()
            if not send_to.get('folder'):
                import tempfile as _tempfile
                staging=Path(_tempfile.mkdtemp(prefix='export_',dir=str(paths.cache_dir())))
                suggested=staging/suggested.name
        if send_to is not None and not send_to.get('folder'):
            destination=str(suggested)
            _=figure_filter
        else:
            destination,_=QFileDialog.getSaveFileName(self,f'Export publication figure as {chosen}',str(suggested),filters)
        if not destination:return
        for word,ext in (('NumPy','.npy'),('CSV','.csv')):
            if word in _ and Path(destination).suffix.lower()!=ext:
                stem=destination[:-len(Path(destination).suffix)] if Path(destination).suffix.lower() in ('.pdf','.png','.svg','.jpg','.jpeg') else destination
                destination=stem+ext
        if Path(destination).suffix.lower() in ('.jpg','.jpeg') and 'jpg' not in formats:
            formats=formats+['jpg']   # a typed .jpg name is honoured as an extra format
        if Path(destination).suffix.lower() in ('.npy','.csv'):
            if len(selected)!=1 or selected[0]['kind']!='channel':
                self._log('Numerical export requires a single scan channel',important=True)
                return
            task=Task(self._job_token+1,export_numerical_panel,self.scan,selected[0],
                      Path(destination),preset)
        else:
            task=Task(self._job_token+1,export_publication_formats,self.scan,selected,
                      Path(destination),preset,formats,plot_config=self._plot_profile_for_run(),
                      transparent=dialog.transparent_background(),
                      arrangement=dialog.arrangement() if len(selected)>=2 else 'row',
                      panel_letters=dialog.letters_enabled(),columns=dialog.columns())
        def finished(_,path,send_to=send_to,caption=self.scan.path.stem):
            produced=list(path) if isinstance(path,(list,tuple)) else [path]
            for p in produced:self._export_done(p)
            if send_to and any(send_to.get(k) for k in ('latex','slides','overleaf')):
                self.documents.deliver(produced,send_to,caption=send_to.get('latex_caption') or '')
        self._start_task(task,finished,
                         lambda _,exc:self._log(f'Export failed:\n{exc}',important=True))
        self._log(f'Publication export requested: {destination}')

    def _export_profile_saved(self,name):
        self._load_export_presets()
        set_combo_key(self.export_preset_combo,name)
        self._log(f'Export profile saved: {name} (figure list of the top bar; share it from Settings › Library)',important=True)

    def _export_done(self,dest):
        note=''
        try:
            info=json.loads(Path(str(dest)+'.provenance.json').read_text(encoding='utf-8'))
            crop=info.get('tight_crop') or {}
            if crop:
                w,h=crop.get('size_px',[0,0]);mw,mh=crop.get('size_mm',[0,0])
                note=f' · cropped to content: {w}×{h} px ({mw:.1f}×{mh:.1f} mm)'
            if info.get('transparent_background'):
                check=(crop.get('png_check') or {})
                if Path(str(dest)).suffix.lower() in ('.jpg','.jpeg'):
                    note+=' · JPEG cannot be transparent (use PNG, SVG or PDF)'
                elif check:
                    note+=' · transparent background verified' if check.get('transparent_ok') else ' · WARNING: background not transparent'
                else:
                    note+=' · transparent page (PDF viewers still draw a white page; it is transparent when placed in slides)'
        except Exception:
            pass
        self._log(f'Exported {dest} + provenance{note}',important=True)
        self._add_result(str(dest),'Exported figure/data')

    def _scripts_signature(self):
        folder=paths.scripts_dir()
        sig=[]
        try:
            for entry in sorted(folder.iterdir()):
                if entry.name.startswith('.'):continue
                if entry.is_dir():
                    for name in ('module.json','module.py'):
                        f=entry/name
                        try:sig.append((entry.name,name,f.stat().st_mtime_ns,f.stat().st_size))
                        except OSError:pass
                elif entry.suffix.lower()=='.py':
                    sig.append((entry.name,'',entry.stat().st_mtime_ns,entry.stat().st_size))
        except OSError:
            return None
        return tuple(sig)

    def _start_scripts_watch(self):
        """v0.8.1: new or edited tools (e.g. written by the Assistant) appear without restart."""
        self._scripts_sig=self._scripts_signature()
        self._scripts_timer=QTimer(self)
        self._scripts_timer.setInterval(2000)
        self._scripts_timer.timeout.connect(self._check_scripts_folder)
        self._scripts_timer.start()

    def _check_scripts_folder(self):
        sig=self._scripts_signature()
        if sig is None or sig==getattr(self,'_scripts_sig',None):return
        # Wait one more tick if a file is still being written (size/mtime changing).
        pending=getattr(self,'_scripts_pending',None)
        self._scripts_pending=sig
        if pending!=sig:return
        self._scripts_sig=sig;self._scripts_pending=None
        self._live_refresh_modules()

    def _live_refresh_modules(self):
        tools=self.browser.tools
        current=tools.currentItem()
        current_id=current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        before={k:(m.name,m.version) for k,m in self.modules.items()}
        tools.blockSignals(True)
        try:
            self.refresh_modules(quiet=True)
            if current_id:
                for i in range(tools.count()):
                    if tools.item(i).data(Qt.ItemDataRole.UserRole)==current_id:
                        tools.setCurrentRow(i);break
            self.browser._filter(tools,self.browser.tool_search.text())
        finally:
            tools.blockSignals(False)
        added=[m for k,m in self.modules.items() if k not in before]
        changed=[m for k,m in self.modules.items() if k in before and before[k]!=(m.name,m.version)]
        removed=[name for k,(name,_) in before.items() if k not in self.modules]
        for m in added:self._log(f'New tool available in Tools: {m.name}')
        for m in changed:self._log(f'Tool updated: {m.name} {m.version}')
        for name in removed:self._log(f'Tool removed: {name}')
        if added or changed or removed:
            names=', '.join(m.name for m in added+changed) or ', '.join(removed)
            self.statusBar().showMessage(('New tool: ' if added else 'Tools updated: ')+names,8000)
            if added:self.browser.tabs.setCurrentIndex(1)

    def refresh_modules(self,quiet=False):
        user=paths.scripts_dir()
        roots=[user]
        self.modules,issues=discover_modules(roots)
        self.browser.tools.clear()
        for mod in sorted(self.modules.values(),key=lambda m:(m.category,m.name.lower())):
            # Old user-owned script folders can outlive package upgrades.
            if mod.id=='batch_scan_report' or 'physically informed' in mod.name.casefold():
                continue
            item=QListWidgetItem(mod.name)   # v0.0.5: no status glyph beside the name (it is in the tooltip)
            item.setData(Qt.ItemDataRole.UserRole,mod.id)
            item.setToolTip(f'{mod.category} · {mod.description} · {mod.status}')
            self.browser.tools.addItem(item)
        # Figure composer is a full interactive workspace, not a batch analysis.
        # Expose it beside ordinary scripts in the left Tools browser as requested.
        composer_item=QListWidgetItem('Spectroscopy figure composer (Δf(V), dI/dV, I(V), I(z) …)')
        composer_item.setData(Qt.ItemDataRole.UserRole,'__bias_figure_composer__')
        composer_item.setToolTip('Scan images + spectra of any method (choose the measurement type at the top) · '
                                 'measurement positions on the scan · PDF/SVG/PNG · no scan needed')
        self.browser.tools.addItem(composer_item)
        print_item=QListWidgetItem('3D print (STL / STEP) with 3D colour bar')
        print_item.setData(Qt.ItemDataRole.UserRole,'__print3d__')
        print_item.setToolTip('Any channel, a lattice or a molecule-placement result as a printable relief · '
                              '3D colour bar · range cut · live 3D preview · STL / STEP')
        self.browser.tools.addItem(print_item)
        for msg in issues:self._log('Module discovery: '+msg)
        if quiet:return
        self._log(f'{len(self.modules)} modules detected (manifest-only; no tool code imported)')
        for note in getattr(self,'_module_upgrade_messages',[]):self._log('Factory module migration: '+note)

    def import_module(self):
        path,_=QFileDialog.getOpenFileName(self,'Select script or module.json','','Python / manifest (*.py *.json)')
        if not path:return
        path=Path(path)
        folder=paths.scripts_dir()
        source=path.parent if path.name=='module.json' else path
        destination=folder/source.name
        if destination.exists():
            self._log(f'Already installed: {destination} (remove or rename before importing)',important=True)
            return
        try:
            if source.is_dir():shutil.copytree(source,destination)
            else:shutil.copy2(source,destination)
            self.refresh_modules()
            self._log(f'Imported {destination}; no script executed during import')
        except Exception as exc:self._log(f'Import failed: {exc}',important=True)

    def _show_module(self,module_id):
        if module_id=='__print3d__':
            self.open_print3d()
            QTimer.singleShot(0,lambda:self.browser.tools.setCurrentRow(-1))
            return
        if module_id=='__bias_figure_composer__':
            # Selecting a workspace launcher must not clear active ROIs or tools.
            self.open_bias_figure_composer()
            # Allow another single click to reopen the composer after closing.
            QTimer.singleShot(0,lambda:self.browser.tools.setCurrentRow(-1))
            return
        module=self.modules.get(module_id)
        if module_id!='molecule_placement':
            self._stop_molecule_preview()
            if self._result_view is not None and self._result_view.live:
                self._result_view.hide()
                self._result_view.live=False
        elif module is not None and not module.builtin and str(self.settings.value('trusted_module_'+module.id,''))!='yes':
            approve=QMessageBox.warning(self,'Enable molecule live preview?',
                'The selected molecule module runs Python code in a separate process to create previews. '
                'Only allow scripts you trust. Allow this module to run?',
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
            if approve==QMessageBox.StandardButton.Yes:
                self.settings.setValue('trusted_module_'+module.id,'yes')
        self.module_panel.set_module(module,list(self.scan.channels) if self.scan else [],
                                     selected_channel=self._selection_key()[1] if self.scan else '')
        if self.scan:self.module_panel.set_channel_title(self.channel_title(self._selection_key()[1]))
        self._live_preview_roi=None
        self.viewer.roi=None
        self.viewer.extra_rois.clear()
        self.viewer.mask_overlay=None
        self._sync_selection_list()
        interaction=module.interaction if module else 'none'
        tools=(module.selection or {}).get('tools',[]) if module else []
        self.line_button.setVisible(not tools)
        self.rect_button.setVisible(not tools)
        self.viewer.set_roi_tool(tools[0] if tools else 'pan')
        if interaction=='histogram_masks' and self.scan:
            try:
                saved=self._session_masks.get(self._mask_settings_key(),[])
                self.module_panel.set_masks(saved)
            except (TypeError,ValueError):pass
        if self.viewer.mask_overlay is not None and interaction!='histogram_masks':
            self.viewer.mask_overlay=None
            self.viewer.update()
        self.right_tabs.setCurrentWidget(self.module_tools_scroll)
        # A previously selected tool can leave the scrolling panel at the
        # bottom, hiding the molecule SVG file chooser at the top.
        self.module_tools_scroll.verticalScrollBar().setValue(0)
        self._refresh_saved_runs(restore_settings=True)
        if module_id=='molecule_placement' and self.scan is not None:
            self._show_live_molecule_preview('Load SVG/PNG artwork to update this channel live.')
        self._queue_live_preview()

    def _refresh_result_channels(self, select_id=None):
        """Index current scan's PDFs from all analyses, including v0.7 runs."""
        if self.scan is None:return
        source=self.research_store.scan_by_path(self.scan.path)
        runs=self.research_store.runs(source['id']) if source else []
        by_module={}
        for run in runs:
            if run.get('status')!='completed':continue
            module_id=run.get('module_id')
            if module_id and module_id not in by_module:
                folder=Path(run.get('run_folder') or '')
                files=public_files(folder) if folder.is_dir() else []
                if not files:
                    files=[Path(p) for p in run.get('artifacts',[]) if Path(p).is_file() and Path(p).suffix.lower() in ('.svg','.pdf')]
                    files.sort(key=lambda p:(0 if '07_reference_scan_lattice_overlay' in p.name else 1, p.name))
                if files:by_module[module_id]=(run,files)
        # Recover reports after moving a scan project between computers, even
        # when the local ResearchStore index was not transferred with it.
        result_root=self.scan.path.parent/'SPM_Studio_Results'/self.scan.path.stem
        if result_root.is_dir():
            for candidate in sorted(result_root.iterdir(),reverse=True):
                if not candidate.is_dir() or candidate.name in ('Images','Plots'):
                    continue
                if candidate.name=='Data':
                    folders=sorted((x for x in candidate.iterdir() if x.is_dir()),reverse=True)
                else:
                    folders=[candidate]
                for folder in folders:
                    name=folder.name.lower()
                    # New: `<module>_YYYYMMDD_HHMMSS_<token>`.
                    # v0.7: `YYYYMMDD_HHMMSS_<module>_<token>`.
                    import re
                    current=re.fullmatch(r'(.+?)_\d{8}_\d{6}_[a-z0-9]+',name)
                    older=re.fullmatch(r'\d{8}_\d{6}_(.+)_[a-z0-9]{6,}',name)
                    module_id=(current.group(1) if current else
                               older.group(1) if older else name.split('_20',1)[0]).strip('_')
                    if not module_id or module_id in by_module:continue
                    # Avoid mixing two source files with the same stem but
                    # different extensions that share the same directory.
                    context=folder/'context.json'
                    if context.is_file():
                        try:
                            origin=json.loads(context.read_text(encoding='utf-8')).get('scan_path')
                            if origin and Path(origin).resolve()!=self.scan.path.resolve():continue
                        except (OSError,ValueError,TypeError):pass
                    files=public_files(folder)
                    if not files:continue
                    local_record={'module_id':module_id,'run_folder':str(folder),
                                  'artifacts':[str(f) for f in files]}
                    by_module[module_id]=(local_record,files)
        self._result_records=by_module
        labels={('Lattice measurement results' if key=='lattice_measurements' else
                 key.replace('_',' ').title()+' results'):key for key in sorted(by_module)}
        self.inspector.set_result_channels(labels)
        if select_id and select_id in by_module:
            # Do not set the active scan channel to a PDF. Original raster
            # channels remain visible and their analysis is non-destructive.
            self._active_result_module_id=select_id
            self._activate_result_channel(select_id)
        elif self.inspector.channel.currentText() in labels:
            self._active_result_module_id=labels[self.inspector.channel.currentText()]
            self._activate_result_channel(self._active_result_module_id)
        self._sync_multiview()

    def _activate_result_channel(self,module_id,record=None):
        if self.scan is None or module_id not in self._result_records:return
        selected,files=self._result_records[module_id]
        if record is not None:
            selected=record
            folder=Path(record.get('run_folder') or '')
            files=public_files(folder) if folder.is_dir() else []
            if not files:files=[Path(p) for p in record.get('artifacts',[]) if Path(p).is_file() and Path(p).suffix.lower() in ('.svg','.pdf')]
        preview=self._ensure_result_preview()
        folder=Path(selected.get('run_folder') or '')
        images=preview_files(folder,files)
        preview.set_reports(images,module_id.replace('_',' ').title()+' results')
        QTimer.singleShot(0,lambda:self.channel_scroll.horizontalScrollBar().setValue(
            self.channel_scroll.horizontalScrollBar().maximum()))

    def _refresh_saved_runs(self,restore_settings=False):
        if self.scan is None or self.module_panel.module is None:
            self.module_panel.show_runs([])
            return
        previous=self._displayed_run_id
        current=self.module_panel.module
        scan=self.research_store.scan_by_path(self.scan.path)
        runs=self.research_store.runs(scan['id'],current.id) if scan else []
        selected=next((r for r in runs if r['result_id']==previous),None)
        if selected is None:selected=next((r for r in runs if r.get('preferred')),None)
        if selected is None:selected=runs[0] if runs else None
        self._displayed_run_id=selected['result_id'] if selected else None
        msg=format_record(selected)
        if selected:
            # A source changed on disk? Preserve history and clearly mark stale.
            try:
                st=self.scan.path.stat()
                if st.st_mtime_ns!=selected.get('source_mtime_ns') or st.st_size!=selected.get('source_bytes'):
                    msg='STALE: source file metadata changed. This run was not recomputed.\n'+msg
            except OSError:msg='SOURCE MISSING\n'+msg
            notes=self.research_store.annotations(selected['result_id'])
            if notes:msg+='\n\nNotes:\n'+'\n'.join(f"[{ui_label(n['epistemic_status'])}] {n['text']}" for n in notes)
            # Restore settings from the run only when opening a new scan/tool;
            # do not silently overwrite user edits each time a note is saved.
        self.module_panel.show_runs(runs,self._displayed_run_id,msg)
        if restore_settings and selected is not None:
            self.module_panel.restore_values(selected.get('parameters',{}))
        self._indicate_staleness()

    def _indicate_staleness(self):
        if self.scan is None or self.module_panel.module is None or not self._displayed_run_id:return
        record=self.research_store.run(self._displayed_run_id)
        if not record:return
        differences=[]
        try:
            params=validate_params(self.module_panel.module,self.module_panel.values())
            if params!=record.get('parameters'):differences.append('tool parameters')
            from ..core.research_records import module_code_hash
            if record.get('algorithm_sha256')!=module_code_hash(self.module_panel.module):
                differences.append('algorithm source')
            if record.get('module_version')!=self.module_panel.module.version:
                differences.append('module version')
            roi=self.viewer.roi or (self.viewer.extra_rois[-1] if self.viewer.extra_rois else None)
            if (roi.to_dict() if roi else None)!=record.get('roi'):
                differences.append('ROI')
            if [r.to_dict() for r in self.viewer.extra_rois]!=record.get('rois',[]):
                differences.append('additional ROIs')
            if [asdict(step) for step in self.pipelines.get(self._selection_key(),[])]!=record.get('preprocessing',[]):
                differences.append('preprocessing')
        except (ValueError,TypeError):differences.append('invalid tool parameters')
        try:
            current_channel=self.inspector.channel.currentText()
            if current_channel not in self.scan.channels:current_channel=self._current_channel
            if current_channel!=record.get('channel') or self.inspector.selected_trace()!=record.get('direction'):
                differences.append('channel or trace')
            if self.scan.channels[current_channel].geometry.to_dict()!=record.get('scan_geometry'):
                differences.append('scan geometry/calibration')
            st=self.scan.path.stat()
            if st.st_mtime_ns!=record.get('source_mtime_ns') or st.st_size!=record.get('source_bytes'):
                differences.append('source fingerprint needs revalidation')
        except (OSError,KeyError):differences.append('source missing')
        if differences:
            msg=self.module_panel.result_text.toPlainText()
            msg='STALE FOR CURRENT INPUTS: '+', '.join(differences)+'\nHistoric result remains available.\n\n'+msg
            if 'STALE FOR CURRENT INPUTS:' not in self.module_panel.result_text.toPlainText():
                self.module_panel.result_text.setPlainText(msg)

    def _select_saved_run(self,run_id):
        record=self.research_store.run(run_id) if run_id else None
        if not record:return
        self._displayed_run_id=run_id
        message=format_record(record)
        notes=self.research_store.annotations(run_id)
        if notes:message+='\n\nNotes:\n'+'\n'.join(f"[{ui_label(n['epistemic_status'])}] {n['text']}" for n in notes)
        self.module_panel.result_text.setPlainText(message)
        if record.get('parameters'):self.module_panel.restore_values(record['parameters'])
        self.logs.outputs.clear()
        for path in record.get('artifacts',[]):
            if Path(path).suffix.lower() in ('.pdf','.svg','.gwy'):
                self._add_result(path,'Saved output')
        if record.get('module_id') in self._result_records:
            self._activate_result_channel(record['module_id'],record)

    def _save_research_note(self,text,status):
        if not self._displayed_run_id or not text.strip():return
        try:
            self.research_store.annotate(self._displayed_run_id,text,status)
            self._refresh_saved_runs()
        except Exception as exc:self._log(f'Unable to save note: {exc}',important=True)

    def _prefer_run(self,run_id):
        if not run_id:return
        self.research_store.prefer(run_id)
        self._refresh_saved_runs()

    def open_research_comparison(self):
        from .research_compare import CompareDialog
        dialog=CompareDialog(self)
        dialog.exec()

    def run_module(self):
        if self.scan is None or self.processed is None:
            self._log('Select a scan first',important=True)
            return
        item=self.browser.tools.currentItem()
        if item is None:
            self._log('Select an analysis module from Tools',important=True)
            return
        mod=self.modules.get(item.data(Qt.ItemDataRole.UserRole))
        if mod is None or mod.status not in ('operational','experimental') or mod.missing_dependencies():
            self._log('Selected module is unavailable; see Tool settings',important=True)
            return
        if self.job and self.job.state()!=QProcess.ProcessState.NotRunning:
            self._log('A module is already running; cancel/finish before another run',important=True)
            return
        if not mod.builtin:
            trusted=str(self.settings.value('trusted_module_'+mod.id,''))
            if trusted!='yes':
                answer=QMessageBox.warning(self,'Run external Python code?',
                    f'{mod.name} will execute Python with your user privileges. This is NOT a sandbox. Run it?',
                    QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
                if answer!=QMessageBox.StandardButton.Yes:return
                self.settings.setValue('trusted_module_'+mod.id,'yes')
        try:
            params=validate_params(mod,self.module_panel.values())
        except (TypeError,ValueError) as exc:
            self._log(f'Module parameter error: {exc}',important=True)
            return
        key=self._selection_key()
        scan_record=self.research_store.scan_by_path(self.scan.path)
        roi=self.viewer.roi or (self.viewer.extra_rois[-1] if self.viewer.extra_rois else None)
        try:
            if scan_record and self.scan.path.stat().st_size==scan_record['bytes'] and self.scan.path.stat().st_mtime_ns==scan_record['mtime_ns']:
                context={'channel':key[1],'direction':key[2],'parameters':params,
                    'roi':roi.to_dict() if roi else None,
                    'rois':[r.to_dict() for r in self.viewer.extra_rois],
                    'processing':[asdict(step) for step in self.pipelines.get(key,[])],
                    'geometry':self.scan.channels[key[1]].geometry.to_dict()}
                key_fingerprint=execution_key(scan_record['sha256'],context,mod)
                previous=self.research_store.matching(scan_record['id'],mod.id,key_fingerprint)
                if previous:
                    choice=QMessageBox.question(self,'Identical saved analysis',
                        'A completed run with the same scan, channel, ROI, preprocessing, '
                        'geometry, algorithm version and parameters already exists.\n\n'
                        'Yes: reuse and display the saved result.\nNo: recompute a new run.',
                        QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
                    if choice==QMessageBox.StandardButton.Yes:
                        self._displayed_run_id=previous['result_id']
                        self._refresh_saved_runs()
                        self._select_saved_run(previous['result_id'])
                        self.statusBar().showMessage('Reused saved analysis without re-executing module')
                        return
        except (OSError,ValueError,TypeError) as exc:
            self._log(f'Cache lookup skipped: {exc}')
        run_dir=run_path(self.scan.path,mod.id,time.strftime('%Y%m%d_%H%M%S'),uuid.uuid4().hex[:6])
        self._job_token+=1
        token=self._job_token
        self._run_module=mod
        self._cancel_requested=False
        self._run_files=[]
        self._run_started=time.monotonic()
        self.logs.state.setText('Preparing snapshot…')
        self.module_panel.set_run_state('preparing',f'Preparing {mod.name}…')
        self.logs.cancel.setEnabled(True)
        if self._logs_open_on_run():          # v0.0.18: off by default (Settings › General)
            self.log_dock.show()
            self.logs.tabs.setCurrentIndex(0)
        task=Task(token,make_snapshot,run_dir,self.scan,key[1],key[2],self.processed,
                  params,self._source_paths,self.viewer.roi or (self.viewer.extra_rois[-1] if self.viewer.extra_rois else None),self.pipelines.get(key,[]),
                  list(self.viewer.extra_rois),{**self._plot_profile_for_run(),'viewer_config':self.viewer_config_for_run()},
                  self._plot_formats_for_run(),mod.snapshot_channels,
                  tuple(params[k] for k in mod.snapshot_parameter_channels if params.get(k)))
        self._start_task(task,self._snapshot_prepared,self._snapshot_failed)

    def _snapshot_failed(self,token,error):
        if token!=self._job_token:return
        self.logs.cancel.setEnabled(False)
        self.logs.state.setText('Failed to prepare')
        self.module_panel.set_run_state('failed','Could not prepare the run — see Logs')
        self._log(error,error=True)

    def _snapshot_prepared(self,token,context):
        if token!=self._job_token:return
        self._run_context=Path(context)
        mod=self._run_module
        p=QProcess(self)
        p.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        env=QProcessEnvironment.systemEnvironment()
        env.insert('PYTHONUNBUFFERED','1')
        env.insert('SPM_CONTEXT_JSON',str(context))
        env.insert('SPM_OUTPUT_DIR',str(context.parent))
        p.setProcessEnvironment(env)
        p.setWorkingDirectory(str(context.parent))
        if mod.mode=='legacy':
            args=['-u',str(mod.path)]
        else:
            entry,function=mod.entrypoint.split(':')
            args=['-u','-m','spm_studio.core.module_runner','--entry-file',str(mod.path/(entry+'.py')),
                  '--function',function,'--context',str(context)]
        self.job=p
        self._stdout_buffer=self._stderr_buffer=''
        self._run_log=(context.parent/'run.log').open('w',encoding='utf8')
        p.readyReadStandardOutput.connect(self._read_stdout)
        p.readyReadStandardError.connect(self._read_stderr)
        p.errorOccurred.connect(lambda err:self._log(f'Job process error: {p.errorString()}',important=True))
        p.finished.connect(self._run_finished)
        p.start(sys.executable,args)
        if mod.mode=='legacy':
            p.closeWriteChannel()  # input() fails with EOF rather than hanging forever.
        self.logs.state.setText(f'Running {mod.name}…')
        self.module_panel.set_run_state('running',f'Running {mod.name}…')
        self._log(f'▶ {mod.name} in {context.parent}')

    def _read_stdout(self):
        if self.job is None:return
        self._stdout_buffer+=bytes(self.job.readAllStandardOutput()).decode('utf8',errors='replace')
        while '\n' in self._stdout_buffer:
            line,self._stdout_buffer=self._stdout_buffer.split('\n',1)
            self._consume_line(line,False)

    def _read_stderr(self):
        if self.job is None:return
        self._stderr_buffer+=bytes(self.job.readAllStandardError()).decode('utf8',errors='replace')
        while '\n' in self._stderr_buffer:
            line,self._stderr_buffer=self._stderr_buffer.split('\n',1)
            self._consume_line(line,True)

    def _consume_line(self,line,stderr):
        if self._run_log:
            self._run_log.write(('STDERR ' if stderr else '')+line+'\n')
            self._run_log.flush()
        if line.startswith('SPM_EVENT '):
            try:
                obj=json.loads(line[len('SPM_EVENT '):])
                kind=obj.get('type')
                if kind=='log':self._log(obj.get('message',''))
                elif kind=='progress':
                    self.logs.progress.setValue(round(float(obj.get('value',0))))
                    self.logs.state.setText(obj.get('message','Running…'))
                    self.module_panel.set_run_state('progress',str(obj.get('message') or 'Running…'),obj.get('value',0))
                elif kind=='result_file':
                    path=obj.get('path','')
                    self._add_result(path,obj.get('title','Output'))
                    self._run_files.append(path)
                elif kind=='table':
                    path=self._run_context.parent/(str(obj.get('title','table')).replace('/','_')+'.table.json')
                    path.write_text(json.dumps(obj,indent=2,default=str),encoding='utf8')
                    self._add_result(str(path),obj.get('title','Table'))
                elif kind=='overlay':
                    self.viewer.overlays=obj.get('primitives',[])
                    self.viewer.update()
                elif kind=='error':self._log('ERROR: '+obj.get('message',''),important=True)
                elif kind=='finished':self._log('Module reported status: '+obj.get('status',''))
                return
            except Exception as exc:
                self._log(f'Invalid module event ({exc}): {line}',important=True)
                return
        self._log(('! ' if stderr else '')+line,important=stderr and ('Traceback' in line or 'Error' in line),
                  error=stderr and line.startswith('Traceback'))

    def _run_finished(self,exit_code,status):
        self._read_stdout()
        self._read_stderr()
        for remaining,stderr in [(self._stdout_buffer,False),(self._stderr_buffer,True)]:
            if remaining:self._consume_line(remaining,stderr)
        if self._run_log:
            self._run_log.close()
            self._run_log=None
        elapsed=time.monotonic()-self._run_started
        self.logs.cancel.setEnabled(False)
        ok=exit_code==0 and status==QProcess.ExitStatus.NormalExit
        self.logs.state.setText(('Completed' if ok else 'Failed/cancelled')+f' · {elapsed:.1f} s')
        self.logs.progress.setValue(100 if ok else 0)
        self.module_panel.set_run_state('done' if ok else 'failed',
                                        (f'Completed in {elapsed:.1f} s' if ok else 'Failed or cancelled — see Logs'))
        self._log(f'■ Exit code {exit_code} after {elapsed:.1f}s; folder: {self._run_context.parent}',
                  important=not ok,error=not ok and not getattr(self,'_cancel_requested',False))
        # Every tool gets the same Images / Plots / Data layout. Organize *after*
        # execution, to avoid invalidating paths while the script is running.
        try:
            organized=organize_run(self._run_context.parent,self._run_files,success=ok)
            self._run_context=organized['context']
            self._run_files=organized['files']
            self.logs.outputs.clear()
            for path in self._run_files:
                if Path(path).suffix.lower() in ('.pdf','.svg','.gwy'):
                    self._add_result(path,'Analysis result')
        except Exception as exc:
            self._log('Result organization skipped (original files preserved): '+str(exc),important=True)
        try:
            source_hash=json.loads(self._run_context.read_text(encoding='utf8')).get('source_sha256')
            record=make_record(self._run_context,self._run_module,ok,self._run_files,source_sha=source_hash)
            if self.scan is not None and str(self.scan.path)==record['source_path']:
                self._displayed_run_id=record['result_id']
                self._refresh_saved_runs()
                if ok:self._refresh_result_channels(select_id=record.get('module_id'))
            self._log(f"Saved reproducible run {record['result_id']}")
        except Exception as exc:
            import traceback
            self._log('Unable to store analysis provenance: '+str(exc)+'\n'+traceback.format_exc(),important=True)
        self.job=None

    def cancel_job(self):
        if self.job and self.job.state()!=QProcess.ProcessState.NotRunning:
            p=self.job
            self._cancel_requested=True
            p.terminate()
            QTimer.singleShot(2000,lambda: p.kill() if p.state()!=QProcess.ProcessState.NotRunning else None)
            self._log('Requested process termination')
        else:
            self._job_token+=1
            self.logs.cancel.setEnabled(False)
            self.logs.state.setText('Preparation cancelled (pending result ignored)')
            self.module_panel.set_run_state('idle')

    def _add_result(self,path,title):
        if not path:return
        item=QListWidgetItem(f'{title}  ·  {Path(path).name}')
        item.setData(Qt.ItemDataRole.UserRole,path)
        self.logs.outputs.addItem(item)

    def _back_to_scan(self):
        if self.scan is None:return
        self._active_result_module_id=None
        if self._result_view is not None:
            self._result_view.hide()
            self._result_view.live=False
        if self._current_channel in self.scan.channels:
            self.inspector.channel.setCurrentText(self._current_channel)
        self._preserve_view=False
        self._schedule_process()

    def _show_result(self,path):
        file=Path(path)
        if not file.exists():
            self._log(f'Result not found: {file}',important=True)
            return
        if file.suffix.lower() in ('.png','.jpg','.jpeg','.bmp'):
            try:
                self._active_result_module_id=self._active_module_id()
                self._ensure_result_preview().set_reports([file],'Selected image result')
            except Exception as exc:self._log(str(exc),important=True)
        elif file.suffix.lower()=='.json' and file.name.endswith('.table.json'):
            data=json.loads(file.read_text())
            self._log(json.dumps(data,ensure_ascii=False,indent=2),important=True)
            self.logs.tabs.setCurrentIndex(0)
        elif file.suffix.lower() in ('.pdf','.svg'):
            self._active_result_module_id=self._active_module_id()
            self._ensure_result_preview().set_reports([str(file)],'Selected result')
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(file)))

    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls():event.acceptProposedAction()

    def dropEvent(self,event):
        for url in event.mimeData().urls():
            p=Path(url.toLocalFile())
            if p.is_dir():
                crawler=FileCrawler(p)
                crawler.found.connect(self._add_file,Qt.ConnectionType.QueuedConnection)
                self._crawlers.append(crawler)
                crawler.finished.connect(self._crawler_finished,Qt.ConnectionType.QueuedConnection)
                crawler.failed.connect(self._crawler_failed,Qt.ConnectionType.QueuedConnection)
                crawler.start()
            elif p.suffix.lower() in ('.sxm','.gwy'):
                self._add_file(p)
        event.acceptProposedAction()

    def closeEvent(self,event):
        # v0.0.8: editors save their files first; a refused close keeps SPM Studio open.
        try:
            if hasattr(self,'documents') and not self.documents.close_all():
                event.ignore();return
        except RuntimeError:
            pass
        try:
            if self.tutorial is not None:self.tutorial.stop('exited')
            self.extension_api.shutdown()
        except (AttributeError,RuntimeError):
            pass
        self._stop_molecule_preview()
        try:
            self.ai_dock.save_state()
            self.ai_dock.shutdown()
        except (AttributeError,RuntimeError):
            pass
        self.settings.setValue('geometry',self.saveGeometry())
        self.settings.setValue('window_state',self.saveState())
        self.settings.setValue('workspace_splitter_v044',self.workspace_splitter.saveState())
        if self.job:self.job.kill()
        for c in self._crawlers:
            c.requestInterruption()
            c.wait(300)
        if self._run_log:self._run_log.close()
        event.accept()
