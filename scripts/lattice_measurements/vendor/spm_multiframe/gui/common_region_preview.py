from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sys
from typing import Any

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from PySide6.QtCore import QEventLoop, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from spm_multiframe.geometry.overlap import (
    crop_coverage_fraction,
    find_common_crop,
    make_grid_for_bounds,
    recommend_initial_inclusion,
)
from spm_multiframe.models import CropRegion, GridDefinition
from spm_multiframe.plotting.annotations import add_lattice_overlay
from spm_multiframe.plotting.display import prepare_display_image
from spm_multiframe.plotting.scale_bar import add_scale_bar
from spm_multiframe.stacking.resample import resample_to_grid


@dataclass
class PreviewItem:
    scan_id: str
    metadata: dict[str, Any]
    x_nm: np.ndarray
    y_nm: np.ndarray
    channels: dict[str, np.ndarray]
    quality_flags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PreviewSelection:
    accepted: bool
    included_scan_ids: tuple[str, ...]
    crop: CropRegion | None
    output_pixel_size_nm: float
    reference_scan_id: str | None


class ScanCard(QFrame):
    include_changed = Signal(str, bool)
    reference_requested = Signal(str)

    def __init__(
        self,
        item: PreviewItem,
        global_grid: GridDefinition,
        coverage_mask: np.ndarray,
        initial_channel: str,
        lattice_basis_nm: np.ndarray | None,
        gamma_deg: float | None,
    ) -> None:
        super().__init__()
        self.item = item
        # ``global_grid`` is only the common coverage raster. Each image card is rendered
        # on its own absolute physical XY grid so the same crop rectangle can visibly land
        # at a different place in each scan (or be absent altogether).
        self.global_grid = global_grid
        self.coverage_mask = np.asarray(coverage_mask, dtype=bool)
        finite = np.isfinite(item.x_nm) & np.isfinite(item.y_nm)
        if np.any(finite):
            bounds = (
                float(np.nanmin(item.x_nm[finite])),
                float(np.nanmax(item.x_nm[finite])),
                float(np.nanmin(item.y_nm[finite])),
                float(np.nanmax(item.y_nm[finite])),
            )
            pixel = float(np.nanmedian([abs(global_grid.dx_nm), abs(global_grid.dy_nm)]))
            if not np.isfinite(pixel) or pixel <= 0:
                nx = int(item.metadata.get("nx", 2) or 2)
                pixel = max((bounds[1] - bounds[0]) / max(nx, 2), 1e-6)
            self.display_grid = make_grid_for_bounds(bounds, pixel, max_pixels=512)
        else:
            self.display_grid = global_grid
        self.lattice_basis_nm = lattice_basis_nm
        self.gamma_deg = gamma_deg
        self._cache: dict[str, np.ndarray] = {}
        self._crop: CropRegion | None = None
        self._show_lattice = True
        self._show_scale = True
        self._current_channel = initial_channel
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        self.figure = Figure(figsize=(4.4, 3.6), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.ax = self.figure.add_subplot(111)
        layout.addWidget(self.canvas, stretch=3)

        side = QVBoxLayout()
        title = QLabel(f"<b>{item.scan_id}</b>")
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setWordWrap(True)
        side.addWidget(title)
        meta = item.metadata
        lines = [
            f"Acquisition: {meta.get('acquisition_datetime', 'unknown')}",
            f"Pixels: {meta.get('nx')} × {meta.get('ny')}",
            f"Physical size: {meta.get('width_nm', np.nan):.4g} × {meta.get('height_nm', np.nan):.4g} nm",
            f"Centre: ({meta.get('center_x_nm', np.nan):.4g}, {meta.get('center_y_nm', np.nan):.4g}) nm",
            f"Angle: {meta.get('scan_angle_deg', np.nan):.3g}°",
            f"Slow direction: {meta.get('frame_direction', '')}",
            f"Trace: {meta.get('trace_direction', '')}",
            f"Drift correction |Δr|: {meta.get('drift_correction_magnitude_nm', np.nan):.4g} nm",
            f"Residual shift: {meta.get('residual_shift_magnitude_nm', np.nan):.4g} nm",
            f"Registration score: {meta.get('registration_score', np.nan):.3f}",
        ]
        if item.quality_flags:
            lines.append("Warnings: " + ", ".join(item.quality_flags))
        corrected_center = meta.get("corrected_center_nm")
        if isinstance(corrected_center, (list, tuple)) and len(corrected_center) >= 2:
            lines.append(
                f"Drift-corrected centre: ({float(corrected_center[0]):.4g}, {float(corrected_center[1]):.4g}) nm"
            )
        label = QLabel("\n".join(lines))
        label.setWordWrap(True)
        side.addWidget(label)
        self.area_status = QLabel("Physical common area: not computed")
        self.area_status.setWordWrap(True)
        side.addWidget(self.area_status)
        self.include = QCheckBox("Include in final stack")
        self.include.setChecked(True)
        self.include.toggled.connect(lambda checked: self.include_changed.emit(item.scan_id, checked))
        side.addWidget(self.include)
        reference = QPushButton("Set as visual reference")
        reference.clicked.connect(lambda: self.reference_requested.emit(item.scan_id))
        side.addWidget(reference)
        side.addStretch(1)
        layout.addLayout(side, stretch=2)
        self.render(initial_channel)

    def _image(self, channel: str) -> np.ndarray | None:
        if channel not in self.item.channels:
            return None
        if channel not in self._cache:
            self._cache[channel] = resample_to_grid(
                self.item.channels[channel],
                self.item.x_nm,
                self.item.y_nm,
                self.display_grid,
            )
        return self._cache[channel]

    def render(self, channel: str | None = None) -> None:
        if channel is not None:
            self._current_channel = channel
        self.ax.clear()
        image = self._image(self._current_channel)
        extent = [
            self.display_grid.x_nm[0],
            self.display_grid.x_nm[-1],
            self.display_grid.y_nm[0],
            self.display_grid.y_nm[-1],
        ]
        if image is None:
            self.ax.text(0.5, 0.5, f"{self._current_channel}\nnot available", ha="center", va="center", transform=self.ax.transAxes)
            self.ax.set_xlim(extent[:2])
            self.ax.set_ylim(extent[2:])
        else:
            display_image, cmap, vmin, vmax, _levelled = prepare_display_image(
                image, self._current_channel
            )
            self.ax.imshow(
                display_image,
                origin="lower",
                extent=extent,
                aspect="equal",
                cmap=cmap,
                vmin=vmin,
                vmax=vmax,
            )
            valid = np.isfinite(image)
            if np.any(valid):
                rows, cols = np.where(valid)
                self.ax.set_xlim(self.display_grid.x_nm[max(0, cols.min() - 2)], self.display_grid.x_nm[min(len(self.display_grid.x_nm)-1, cols.max() + 2)])
                self.ax.set_ylim(self.display_grid.y_nm[max(0, rows.min() - 2)], self.display_grid.y_nm[min(len(self.display_grid.y_nm)-1, rows.max() + 2)])
        self.ax.set_xlabel("x (nm)")
        self.ax.set_ylabel("y (nm)")
        self.ax.set_title(f"Corrected physical preview — {self._current_channel}")
        if self._crop is not None:
            self.ax.add_patch(
                Rectangle(
                    (self._crop.xmin_nm, self._crop.ymin_nm),
                    self._crop.width_nm,
                    self._crop.height_nm,
                    fill=False,
                    edgecolor="white",
                    linewidth=2.0,
                )
            )
            fraction = crop_coverage_fraction(self.coverage_mask, self.global_grid, self._crop)
            if fraction <= 0.01:
                self.ax.text(
                    0.5,
                    0.08,
                    "Selected physical area is not in this scan",
                    ha="center",
                    va="bottom",
                    transform=self.ax.transAxes,
                    bbox={"facecolor": "black", "alpha": 0.65, "edgecolor": "none"},
                    color="white",
                )
        if (
            self._show_lattice
            and image is not None
            and self.lattice_basis_nm is not None
            and self.gamma_deg is not None
        ):
            add_lattice_overlay(
                self.ax,
                self.lattice_basis_nm,
                self.gamma_deg,
                image=(display_image if image is not None else image),
                grid=self.display_grid,
            )
        if self._show_scale:
            try:
                add_scale_bar(self.ax)
            except ValueError:
                pass
        self.canvas.draw_idle()

    def set_crop(self, crop: CropRegion | None) -> None:
        self._crop = crop
        if crop is None:
            self.area_status.setText("Physical common area: none")
        else:
            fraction = crop_coverage_fraction(self.coverage_mask, self.global_grid, crop)
            if fraction >= 0.999:
                self.area_status.setText("Physical common area: fully present in this scan")
            elif fraction <= 0.01:
                self.area_status.setText("Physical common area: NOT present in this scan")
            else:
                self.area_status.setText(
                    f"Physical common area: only {100.0 * fraction:.1f}% present in this scan"
                )
        self.render()

    def set_overlays(self, lattice: bool, scale: bool) -> None:
        self._show_lattice = lattice
        self._show_scale = scale
        self.render()

    def set_included_visual(self, included: bool) -> None:
        self.include.blockSignals(True)
        self.include.setChecked(included)
        self.include.blockSignals(False)
        self.setStyleSheet("" if included else "QFrame { color: #777; background: #e9e9e9; }")


class CommonRegionPreviewWindow(QMainWindow):
    closed = Signal()

    def __init__(
        self,
        items: list[PreviewItem],
        masks: list[np.ndarray],
        mask_grid: GridDefinition,
        channels: list[str],
        *,
        initial_pixel_size_nm: float,
        lattice_basis_nm: np.ndarray | None = None,
        gamma_deg: float | None = None,
        snapshot_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.items = items
        self.masks = masks
        self.mask_grid = mask_grid
        self.channels = channels
        self.snapshot_path = snapshot_path
        self.included, _initial_crop = recommend_initial_inclusion(
            masks, mask_grid, mode="largest_rectangle"
        )
        self.reference_scan_id: str | None = items[0].scan_id if items else None
        self.selection = PreviewSelection(False, (), None, initial_pixel_size_nm, None)
        self.cards: list[ScanCard] = []
        self.setWindowTitle("SPM MultiFrame — common physical region validation")
        self.resize(1250, 900)

        central = QWidget()
        root = QVBoxLayout(central)
        controls = QGridLayout()
        self.channel_combo = QComboBox()
        self.channel_combo.addItems(channels)
        self.include_all_btn = QPushButton("Include all")
        self.exclude_all_btn = QPushButton("Exclude all")
        self.crop_combo = QComboBox()
        self.crop_combo.addItem("Largest rectangle", "largest_rectangle")
        self.crop_combo.addItem("Largest square", "largest_square")
        self.pixel_spin = QDoubleSpinBox()
        self.pixel_spin.setDecimals(5)
        self.pixel_spin.setRange(1e-5, 1e6)
        self.pixel_spin.setValue(initial_pixel_size_nm)
        self.pixel_spin.setSuffix(" nm")
        self.recompute_btn = QPushButton("Recompute common region")
        self.auto_select_btn = QPushButton("Auto-select common-area subset")
        self.lattice_check = QCheckBox("Show lattice overlay")
        self.lattice_check.setChecked(lattice_basis_nm is not None)
        self.scale_check = QCheckBox("Show scale bar")
        self.scale_check.setChecked(True)
        self.status = QLabel()
        controls.addWidget(QLabel("Preview channel"), 0, 0)
        controls.addWidget(self.channel_combo, 0, 1)
        controls.addWidget(self.include_all_btn, 0, 2)
        controls.addWidget(self.exclude_all_btn, 0, 3)
        controls.addWidget(QLabel("Crop mode"), 1, 0)
        controls.addWidget(self.crop_combo, 1, 1)
        controls.addWidget(QLabel("Output pixel size"), 1, 2)
        controls.addWidget(self.pixel_spin, 1, 3)
        controls.addWidget(self.recompute_btn, 2, 0)
        controls.addWidget(self.auto_select_btn, 2, 1)
        controls.addWidget(self.lattice_check, 2, 2)
        controls.addWidget(self.scale_check, 2, 3)
        controls.addWidget(self.status, 3, 0, 1, 4)
        root.addLayout(controls)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        self.card_layout = QVBoxLayout(scroll_widget)
        initial_channel = channels[0]
        for item, coverage_mask in zip(items, masks, strict=True):
            card = ScanCard(
                item,
                mask_grid,
                coverage_mask,
                initial_channel,
                lattice_basis_nm,
                gamma_deg,
            )
            card.include_changed.connect(self._include_changed)
            card.reference_requested.connect(self._set_reference)
            self.cards.append(card)
            self.card_layout.addWidget(card)
        for card, keep in zip(self.cards, self.included, strict=True):
            card.set_included_visual(keep)
        self.card_layout.addStretch(1)
        scroll.setWidget(scroll_widget)
        root.addWidget(scroll, stretch=1)

        bottom = QHBoxLayout()
        cancel = QPushButton("Cancel")
        snapshot = QPushButton("Save preview snapshot")
        validate = QPushButton("Validate & continue")
        bottom.addWidget(cancel)
        bottom.addStretch(1)
        bottom.addWidget(snapshot)
        bottom.addWidget(validate)
        root.addLayout(bottom)
        self.setCentralWidget(central)

        self.channel_combo.currentTextChanged.connect(self._change_channel)
        self.include_all_btn.clicked.connect(lambda: self._set_all(True))
        self.exclude_all_btn.clicked.connect(lambda: self._set_all(False))
        self.crop_combo.currentIndexChanged.connect(self._recompute)
        self.recompute_btn.clicked.connect(self._recompute)
        self.auto_select_btn.clicked.connect(self._auto_select)
        self.pixel_spin.valueChanged.connect(self._recompute)
        self.lattice_check.toggled.connect(self._overlay_changed)
        self.scale_check.toggled.connect(self._overlay_changed)
        cancel.clicked.connect(self._cancel)
        snapshot.clicked.connect(self._save_snapshot_dialog)
        validate.clicked.connect(self._validate)
        self._recompute()


    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.closed.emit()
        super().closeEvent(event)

    def _index_for_id(self, scan_id: str) -> int:
        return next(i for i, item in enumerate(self.items) if item.scan_id == scan_id)

    def _include_changed(self, scan_id: str, checked: bool) -> None:
        index = self._index_for_id(scan_id)
        self.included[index] = checked
        self.cards[index].set_included_visual(checked)
        self._recompute()

    def _set_all(self, value: bool) -> None:
        self.included = [value] * len(self.items)
        for card in self.cards:
            card.set_included_visual(value)
        self._recompute()

    def _auto_select(self) -> None:
        recommended, _crop = recommend_initial_inclusion(
            self.masks, self.mask_grid, mode=self.crop_combo.currentData()
        )
        self.included = recommended
        for card, keep in zip(self.cards, self.included, strict=True):
            card.set_included_visual(keep)
        self._recompute()

    def _set_reference(self, scan_id: str) -> None:
        self.reference_scan_id = scan_id
        self.status.setText(self.status.text() + f"  Visual reference: {scan_id}")

    def _change_channel(self, channel: str) -> None:
        for card in self.cards:
            card.render(channel)

    def _overlay_changed(self) -> None:
        for card in self.cards:
            card.set_overlays(self.lattice_check.isChecked(), self.scale_check.isChecked())

    def _recompute(self) -> None:
        mode = self.crop_combo.currentData()
        crop = find_common_crop(self.masks, self.mask_grid, included=self.included, mode=mode)
        for card in self.cards:
            card.set_crop(crop)
        count = sum(self.included)
        if crop is None:
            self.status.setText(f"Included scans: {count}/{len(self.items)} — no common all-valid region")
            return
        pixel = self.pixel_spin.value()
        nx = max(1, int(round(crop.width_nm / pixel)))
        ny = max(1, int(round(crop.height_nm / pixel)))
        self.status.setText(
            f"Included scans: {count}/{len(self.items)} — SAME absolute physical region: "
            f"x=[{crop.xmin_nm:.4g},{crop.xmax_nm:.4g}] nm, "
            f"y=[{crop.ymin_nm:.4g},{crop.ymax_nm:.4g}] nm — "
            f"{crop.width_nm:.4g} × {crop.height_nm:.4g} nm — output ≈ {nx} × {ny} px"
        )

    def _current_crop(self) -> CropRegion | None:
        return find_common_crop(
            self.masks,
            self.mask_grid,
            included=self.included,
            mode=self.crop_combo.currentData(),
        )

    def _save_snapshot(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.grab().save(str(path))

    def _save_snapshot_dialog(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(self, "Save preview snapshot", "common_region_preview.png", "PNG (*.png)")
        if filename:
            self._save_snapshot(Path(filename))

    def _cancel(self) -> None:
        self.selection = PreviewSelection(False, (), None, self.pixel_spin.value(), self.reference_scan_id)
        self.close()

    def _validate(self) -> None:
        crop = self._current_crop()
        if not any(self.included):
            QMessageBox.warning(self, "No scans included", "Include at least one scan before validating.")
            return
        if crop is None:
            QMessageBox.warning(self, "No common region", "The selected scans do not have an all-valid common region.")
            return
        if self.snapshot_path is not None:
            self._save_snapshot(self.snapshot_path)
        included_ids = tuple(item.scan_id for item, keep in zip(self.items, self.included, strict=True) if keep)
        self.selection = PreviewSelection(True, included_ids, crop, self.pixel_spin.value(), self.reference_scan_id)
        self.close()


def run_common_region_preview(
    items: list[PreviewItem],
    masks: list[np.ndarray],
    mask_grid: GridDefinition,
    channels: list[str],
    *,
    initial_pixel_size_nm: float,
    lattice_basis_nm: np.ndarray | None = None,
    gamma_deg: float | None = None,
    snapshot_path: Path | None = None,
) -> PreviewSelection:
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(sys.argv[:1])
    window = CommonRegionPreviewWindow(
        items,
        masks,
        mask_grid,
        channels,
        initial_pixel_size_nm=initial_pixel_size_nm,
        lattice_basis_nm=lattice_basis_nm,
        gamma_deg=gamma_deg,
        snapshot_path=snapshot_path,
    )
    loop = QEventLoop()
    window.closed.connect(loop.quit)
    window.show()
    # A local event loop is sufficient even when an existing QApplication is reused.
    loop.exec()
    selection = window.selection
    if owns_app:
        app.quit()
    return selection
