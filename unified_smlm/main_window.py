from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy
from PyQt5 import QtCore, QtGui, QtWidgets

from .config_store import get_default_section
from .focuslock_integration import IntegratedFocusLockController
from .mm_backend import MicroManagerWorker
from .models import (
    MDAAcquisitionRequest,
    MicroManagerSnapshot,
    UnifiedSettings,
    build_default_settings,
)
from .planning import (
    build_round_frames_per_depth,
    compute_z_scan_plan,
    compute_z_step_from_scan_inputs,
    compute_z_step_um,
    depth_count_from_scan_inputs,
)
from .presets import PRESET_ORDER, apply_preset, build_preset_guidance_lines
from .preview import CameraPreviewWidget
from .save_paths import build_acquisition_path_plan
from .teledyne_integration import IntegratedTeledyneCamController


def _compact_path_label(path_value: str, *, keep_parts: int = 2) -> str:
    raw = str(path_value or "").strip()
    if not raw:
        return ""
    path = Path(raw)
    parts = list(path.parts)
    if len(parts) <= keep_parts:
        return raw
    return "...\\" + "\\".join(parts[-keep_parts:])


class CompactPathEdit(QtWidgets.QLineEdit):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_path = ""
        self.setReadOnly(True)

    def set_full_path(self, path_value: str) -> None:
        self._full_path = str(path_value or "").strip()
        self.setToolTip(self._full_path)
        self._refresh_display()

    def full_path(self) -> str:
        return self._full_path

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._refresh_display()

    def _refresh_display(self) -> None:
        compact = _compact_path_label(self._full_path)
        if compact and self.width() > 0:
            compact = self.fontMetrics().elidedText(compact, QtCore.Qt.ElideMiddle, max(40, self.width() - 10))
        self.blockSignals(True)
        self.setText(compact)
        self.blockSignals(False)


class UnifiedSMLMMainWindow(QtWidgets.QMainWindow):
    request_load_config = QtCore.pyqtSignal(str)
    request_start_live = QtCore.pyqtSignal()
    request_stop_live = QtCore.pyqtSignal()
    request_snap = QtCore.pyqtSignal()
    request_run_acquisition = QtCore.pyqtSignal(object)
    request_stop_acquisition = QtCore.pyqtSignal()
    request_clear_roi = QtCore.pyqtSignal()
    request_refresh = QtCore.pyqtSignal()
    request_set_exposure = QtCore.pyqtSignal(float)
    request_apply_roi = QtCore.pyqtSignal(str)
    request_set_property = QtCore.pyqtSignal(str, str)
    request_set_config_group = QtCore.pyqtSignal(str, str)
    request_apply_trigger_mode = QtCore.pyqtSignal(str)
    request_resolve_external_scan = QtCore.pyqtSignal(bool, str)
    request_poll_stage_positions = QtCore.pyqtSignal()
    request_shutdown = QtCore.pyqtSignal()

    def __init__(self, settings: UnifiedSettings | None = None, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings or build_default_settings()
        self.focuslock_controller = IntegratedFocusLockController(self.settings)
        self.teledyne_controller = IntegratedTeledyneCamController(self.settings)
        self.z_scan_plan = compute_z_scan_plan(self.settings)
        self._updating_ui = False
        self._startup_modules_opened = False
        self._last_snapshot = MicroManagerSnapshot()
        self._last_log_message = ""
        self._bleach_remaining_seconds = 0
        self._bleach_restore_power_mw = self.settings.bleach.return_laser_power_mw
        self._bleach_restore_aotf_value = self.settings.illumination.aotf_642_setpoint
        self._bleach_restore_aotf_enabled = self.settings.illumination.aotf_642_enabled
        self._bleach_restore_modulation_mode = self.settings.illumination.modulation_mode
        self._active_acquisition_request: MDAAcquisitionRequest | None = None
        self._pending_external_scan_reply = False
        self._shutdown_started = False
        self._focuslock_stage_z_um: float | None = None

        self._worker_thread = QtCore.QThread(self)
        self._worker = MicroManagerWorker(
            mm_root=self.settings.paths.micromanager_root,
            java_path=self.settings.paths.micromanager_java,
        )
        self._worker.moveToThread(self._worker_thread)
        self.request_load_config.connect(self._worker.load_config)
        self.request_start_live.connect(self._worker.start_live)
        self.request_stop_live.connect(self._worker.stop_live)
        self.request_snap.connect(self._worker.snap)
        self.request_run_acquisition.connect(self._worker.run_acquisition)
        self.request_stop_acquisition.connect(self._worker.stop_acquisition)
        self.request_clear_roi.connect(self._worker.clear_roi)
        self.request_refresh.connect(self._worker.refresh)
        self.request_set_exposure.connect(self._worker.set_exposure)
        self.request_apply_roi.connect(self._worker.apply_roi_file)
        self.request_set_property.connect(self._worker.set_property)
        self.request_set_config_group.connect(self._worker.set_config_group)
        self.request_apply_trigger_mode.connect(self._worker.apply_trigger_mode)
        self.request_resolve_external_scan.connect(self._worker.resolve_external_scan)
        self.request_poll_stage_positions.connect(self._worker.poll_stage_positions)
        self.request_shutdown.connect(self._worker.shutdown)
        self._worker.snapshot_ready.connect(self._handle_snapshot)
        self._worker.frame_ready.connect(self._handle_frame)
        self._worker.external_scan_requested.connect(self._handle_external_scan_requested)
        self._worker.acquisition_finished.connect(self._handle_acquisition_finished)
        self._worker.error_raised.connect(self._append_log)
        self._worker.status_changed.connect(self._handle_status_message)
        self._worker_thread.finished.connect(self._worker.deleteLater)
        self._worker_thread.start()

        self.focuslock_controller.camera_preview_ready.connect(self._handle_focuslock_preview)
        self.focuslock_controller.status_ready.connect(self._handle_focuslock_status)
        self.focuslock_controller.stage_position_ready.connect(self._handle_focuslock_stage_position)
        self.focuslock_controller.scan_finished.connect(self._handle_focuslock_scan_finished)
        self.focuslock_controller.ui_state_changed.connect(self._handle_focuslock_ui_state_changed)

        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._handle_about_to_quit)

        self.setWindowTitle("Unified SMLM Control")
        self.resize(1480, 920)
        self._build_ui()

        self.module_status_timer = QtCore.QTimer(self)
        self.module_status_timer.timeout.connect(self._refresh_module_status_labels)
        self.module_status_timer.start(1000)

        self.stage_position_timer = QtCore.QTimer(self)
        self.stage_position_timer.timeout.connect(self._poll_stage_positions)
        self.stage_position_timer.start(500)

        self.bleach_timer = QtCore.QTimer(self)
        self.bleach_timer.setInterval(1000)
        self.bleach_timer.timeout.connect(self._tick_bleach_timer)

        self.teledyne_controller.sync_from_settings(self.settings)
        self._load_settings_into_widgets()
        self._refresh_all_views(log_message="Unified GUI initialized. Micro-Manager now runs in-process.")
        self._append_log("No legacy Micro-Manager or Teledyne external launcher is used.")

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        if self._startup_modules_opened:
            return
        self._startup_modules_opened = True

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self._shutdown_runtime()
        event.accept()

    def _handle_about_to_quit(self) -> None:
        self._shutdown_runtime()

    def _shutdown_runtime(self) -> None:
        if self._shutdown_started:
            return
        self._shutdown_started = True

        self.module_status_timer.stop()
        self.stage_position_timer.stop()
        self.bleach_timer.stop()
        self._pull_settings_from_widgets()

        coordinated_shutdown = bool(
            (self._active_acquisition_request and self._active_acquisition_request.coordinated_focus_lock_scan)
            or self.focuslock_controller.is_scanning()
            or self._pending_external_scan_reply
        )
        if coordinated_shutdown:
            self._append_log(
                "Shutdown requested during external-trigger operation. Cleanup order: stop acquisition wait state, request focus-lock DAQ stop, safe-shutdown laser/AOTF, then release Micro-Manager."
            )
        self.request_stop_acquisition.emit()
        if self._pending_external_scan_reply:
            self.request_resolve_external_scan.emit(
                False,
                "GUI shutdown requested during coordinated external-trigger acquisition.",
            )
            self._pending_external_scan_reply = False
        if self.focuslock_controller.is_scanning():
            stop_success, stop_message = self.focuslock_controller.stop_active_scan()
            if stop_message:
                self._append_log(stop_message)

        success, message = self._perform_teledyne_safe_shutdown(reason="GUI exit", show_dialog=False, refresh_ui=False)
        if message:
            self._append_log(message)

        self._shutdown_mm_worker()

        for action in self.focuslock_controller.cleanup():
            self._append_log(action)
        for action in self.teledyne_controller.cleanup():
            self._append_log(action)

    def _shutdown_mm_worker(self) -> None:
        if not hasattr(self, "_worker_thread") or not hasattr(self, "_worker"):
            return

        if self._worker_thread.isRunning():
            try:
                QtCore.QMetaObject.invokeMethod(
                    self._worker,
                    "shutdown",
                    QtCore.Qt.BlockingQueuedConnection,
                )
            except Exception as exc:
                self._append_log(f"Worker shutdown invoke failed: {exc}")
                try:
                    self.request_shutdown.emit()
                except Exception:
                    pass

            self._worker_thread.quit()
            if not self._worker_thread.wait(3000):
                self._append_log("Micro-Manager worker thread did not stop within 3000 ms.")

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget(self)
        self.setCentralWidget(central)

        root_layout = QtWidgets.QVBoxLayout(central)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(10)

        title_row = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("Unified SMLM Control")
        title.setStyleSheet("QLabel { font-size: 22px; font-weight: 600; }")
        subtitle = QtWidgets.QLabel("Embedded Micro-Manager preview, direct 642/AOTF Python runtime control, and integrated Focus Lock.")
        subtitle.setStyleSheet("QLabel { color: #5d6b7a; }")
        title_stack = QtWidgets.QVBoxLayout()
        title_stack.addWidget(title)
        title_stack.addWidget(subtitle)
        title_row.addLayout(title_stack)
        title_row.addStretch(1)

        root_layout.addLayout(title_row)

        self.banner_label = QtWidgets.QLabel()
        self.banner_label.setWordWrap(True)
        root_layout.addWidget(self.banner_label)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_center_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([340, 800, 340])
        root_layout.addWidget(splitter, stretch=1)

        self.statusBar().showMessage("Ready")

    @staticmethod
    def _configure_form_layout(form: QtWidgets.QFormLayout) -> None:
        form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)

    def _build_left_panel(self) -> QtWidgets.QWidget:
        container = QtWidgets.QScrollArea()
        container.setWidgetResizable(True)
        container.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        container.setMinimumWidth(320)
        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        preset_group = QtWidgets.QGroupBox("Preset Modes")
        preset_layout = QtWidgets.QVBoxLayout(preset_group)
        self.active_preset_label = QtWidgets.QLabel()
        self.active_preset_label.setStyleSheet("QLabel { color: #0f4c81; font-weight: 600; }")
        preset_layout.addWidget(self.active_preset_label)

        for preset_name in PRESET_ORDER:
            button = QtWidgets.QPushButton(preset_name)
            button.clicked.connect(lambda _checked=False, name=preset_name: self._apply_preset(name))
            preset_layout.addWidget(button)

        preset_note = QtWidgets.QLabel(
            "Whole-Cell Z Scan keeps the same exposure and per-depth total frame target as non-scan STORM."
        )
        preset_note.setWordWrap(True)
        preset_note.setStyleSheet("QLabel { color: #5d6b7a; }")
        preset_layout.addWidget(preset_note)
        layout.addWidget(preset_group)

        acquisition_group = QtWidgets.QGroupBox("Acquisition")
        acquisition_form = QtWidgets.QFormLayout(acquisition_group)
        self._configure_form_layout(acquisition_form)

        self.sample_name_edit = QtWidgets.QLineEdit()
        self.sample_name_edit.setPlaceholderText("Optional")
        self.sample_name_edit.textChanged.connect(self._handle_settings_changed)
        acquisition_form.addRow("Sample Name", self.sample_name_edit)

        self.save_prefix_edit = QtWidgets.QLineEdit()
        self.save_prefix_edit.setPlaceholderText("Optional")
        self.save_prefix_edit.textChanged.connect(self._handle_settings_changed)
        acquisition_form.addRow("Save Prefix", self.save_prefix_edit)

        self.save_root_edit = CompactPathEdit()
        self.save_root_button = QtWidgets.QPushButton("Browse")
        self.save_root_button.clicked.connect(self._browse_save_root)
        acquisition_form.addRow("Save Root", self._wrap_with_button(self.save_root_edit, self.save_root_button))

        self.save_plan_label = QtWidgets.QLabel("-")
        self.save_plan_label.setWordWrap(True)
        self.save_plan_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.save_plan_label.setStyleSheet("QLabel { color: #5d6b7a; }")
        acquisition_form.addRow("Next Save", self.save_plan_label)

        self.roi_name_edit = CompactPathEdit()
        self.roi_browse_button = QtWidgets.QPushButton("Browse")
        self.roi_browse_button.clicked.connect(self._browse_roi_file)
        acquisition_form.addRow("ROI Preset", self._wrap_with_button(self.roi_name_edit, self.roi_browse_button))

        roi_row = QtWidgets.QHBoxLayout()
        self.apply_roi_button = QtWidgets.QPushButton("Apply ROI")
        self.apply_roi_button.clicked.connect(self._apply_roi_file)
        self.clear_roi_button = QtWidgets.QPushButton("Clear ROI")
        self.clear_roi_button.clicked.connect(self._handle_clear_roi)
        roi_row.addWidget(self.apply_roi_button)
        roi_row.addWidget(self.clear_roi_button)
        acquisition_form.addRow("ROI Action", self._wrap_layout(roi_row))

        self.exposure_spin = QtWidgets.QDoubleSpinBox()
        self.exposure_spin.setRange(1.0, 5000.0)
        self.exposure_spin.setDecimals(1)
        self.exposure_spin.setSuffix(" ms")
        self.exposure_spin.valueChanged.connect(self._handle_exposure_changed)
        acquisition_form.addRow("Exposure", self.exposure_spin)

        self.trigger_combo = QtWidgets.QComboBox()
        self.trigger_combo.addItems(["Internal", "External"])
        self.trigger_combo.currentTextChanged.connect(self._handle_settings_changed)
        self.trigger_combo.currentTextChanged.connect(self._handle_trigger_mode_changed)
        acquisition_form.addRow("Trigger", self.trigger_combo)

        self.saving_format_combo = QtWidgets.QComboBox()
        self.saving_format_combo.addItems(["Separate Image Files", "Image Stack File"])
        self.saving_format_combo.currentTextChanged.connect(self._handle_settings_changed)
        acquisition_form.addRow("Saving Format", self.saving_format_combo)

        self.widefield_frames_spin = QtWidgets.QSpinBox()
        self.widefield_frames_spin.setRange(1, 100000)
        self.widefield_frames_spin.valueChanged.connect(self._handle_settings_changed)
        acquisition_form.addRow("Widefield Frames", self.widefield_frames_spin)

        self.storm_frames_spin = QtWidgets.QSpinBox()
        self.storm_frames_spin.setRange(1, 10000000)
        self.storm_frames_spin.valueChanged.connect(self._handle_settings_changed)
        acquisition_form.addRow("STORM Total Frames", self.storm_frames_spin)

        acquisition_action_row = QtWidgets.QHBoxLayout()
        self.acquire_button = QtWidgets.QPushButton("Acquire")
        self.acquire_button.clicked.connect(self._handle_run_acquisition)
        acquisition_action_row.addWidget(self.acquire_button)

        self.stop_acquire_button = QtWidgets.QPushButton("Stop Acquisition")
        self.stop_acquire_button.clicked.connect(self._handle_stop_acquisition)
        acquisition_action_row.addWidget(self.stop_acquire_button)
        acquisition_form.addRow("Run", self._wrap_layout(acquisition_action_row))

        layout.addWidget(acquisition_group)
        layout.addWidget(self._build_illumination_group())
        layout.addStretch(1)

        container.setWidget(content)
        return container

    def _build_micromanager_group(self) -> QtWidgets.QGroupBox:
        mm_group = QtWidgets.QGroupBox("Embedded Micro-Manager")
        mm_form = QtWidgets.QFormLayout(mm_group)
        self._configure_form_layout(mm_form)

        self.cfg_combo = QtWidgets.QComboBox()
        self.cfg_combo.setMinimumContentsLength(12)
        self.cfg_combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cfg_combo.currentIndexChanged.connect(self._handle_settings_changed)
        self.cfg_browse_button = QtWidgets.QPushButton("Browse")
        self.cfg_browse_button.clicked.connect(self._browse_cfg_file)
        mm_form.addRow("Config", self._wrap_with_button(self.cfg_combo, self.cfg_browse_button))

        backend_row = QtWidgets.QHBoxLayout()
        self.load_cfg_button = QtWidgets.QPushButton("Load Config")
        self.load_cfg_button.clicked.connect(self._load_selected_cfg)
        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.clicked.connect(self._handle_refresh_backend)
        backend_row.addWidget(self.load_cfg_button)
        backend_row.addWidget(self.refresh_button)
        mm_form.addRow("Backend", self._wrap_layout(backend_row))

        self.mm_status_label = QtWidgets.QLabel("Backend idle.")
        self.mm_status_label.setWordWrap(True)
        self.mm_status_label.setStyleSheet("QLabel { color: #5d6b7a; }")
        mm_form.addRow("Status", self.mm_status_label)

        self.mm_stage_position_label = QtWidgets.QLabel("XY: - | Z: -")
        self.mm_stage_position_label.setWordWrap(True)
        self.mm_stage_position_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.mm_stage_position_label.setStyleSheet("QLabel { color: #5d6b7a; }")
        mm_form.addRow("Stage", self.mm_stage_position_label)

        mm_note = QtWidgets.QLabel(
            "The GUI uses pycromanager Python backend for live preview and high-level MDA. "
            "Loading a cfg only reads the current hardware state and does not push preset values back automatically."
        )
        mm_note.setWordWrap(True)
        mm_note.setStyleSheet("QLabel { color: #5d6b7a; }")
        mm_form.addRow("Mode", mm_note)

        return mm_group

    def _build_illumination_group(self) -> QtWidgets.QGroupBox:
        illum_group = QtWidgets.QGroupBox("Illumination (642 / AOTF)")
        illum_form = QtWidgets.QFormLayout(illum_group)
        self._configure_form_layout(illum_form)

        self.teledyne_status_label = QtWidgets.QLabel()
        self.teledyne_status_label.setWordWrap(True)
        self.teledyne_status_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        illum_form.addRow("Backend", self.teledyne_status_label)

        self.channel_642_enabled_checkbox = QtWidgets.QCheckBox("Enabled")
        self.channel_642_enabled_checkbox.stateChanged.connect(self._handle_settings_changed)
        illum_form.addRow("642 Laser", self.channel_642_enabled_checkbox)

        self.laser_642_power_spin = QtWidgets.QDoubleSpinBox()
        self.laser_642_power_spin.setRange(0.0, 5000.0)
        self.laser_642_power_spin.setDecimals(1)
        self.laser_642_power_spin.setSuffix(" mW")
        self.laser_642_power_spin.valueChanged.connect(self._handle_settings_changed)
        illum_form.addRow("642 Power", self.laser_642_power_spin)

        self.aotf_642_enabled_checkbox = QtWidgets.QCheckBox("Enabled")
        self.aotf_642_enabled_checkbox.stateChanged.connect(self._handle_settings_changed)
        illum_form.addRow("AOTF 642", self.aotf_642_enabled_checkbox)

        self.aotf_642_spin = QtWidgets.QDoubleSpinBox()
        self.aotf_642_spin.setRange(0.0, 100.0)
        self.aotf_642_spin.setDecimals(1)
        self.aotf_642_spin.setSingleStep(0.1)
        self.aotf_642_spin.valueChanged.connect(self._handle_settings_changed)
        illum_form.addRow("AOTF Value", self.aotf_642_spin)

        self.modulation_mode_combo = QtWidgets.QComboBox()
        self.modulation_mode_combo.addItems(
            [
                "Independent mode",
                "one-chan FSK mode",
                "two-chan FSK mode",
                "three-chan FSK mode",
            ]
        )
        self.modulation_mode_combo.currentTextChanged.connect(self._handle_settings_changed)
        illum_form.addRow("Modulation", self.modulation_mode_combo)

        illum_action_widget = QtWidgets.QWidget()
        illum_action_layout = QtWidgets.QHBoxLayout(illum_action_widget)
        illum_action_layout.setContentsMargins(0, 0, 0, 0)
        illum_action_layout.setSpacing(6)

        self.apply_illumination_button = QtWidgets.QPushButton("Apply To Hardware")
        self.apply_illumination_button.clicked.connect(self._handle_apply_illumination)
        illum_action_layout.addWidget(self.apply_illumination_button)

        self.safe_shutdown_button = QtWidgets.QPushButton("Safe Shutdown")
        self.safe_shutdown_button.clicked.connect(self._handle_safe_shutdown_illumination)
        illum_action_layout.addWidget(self.safe_shutdown_button)
        illum_form.addRow("Actions", illum_action_widget)

        bleach_widget = QtWidgets.QWidget()
        bleach_layout = QtWidgets.QHBoxLayout(bleach_widget)
        bleach_layout.setContentsMargins(0, 0, 0, 0)
        bleach_layout.setSpacing(6)

        self.bleach_duration_spin = QtWidgets.QDoubleSpinBox()
        self.bleach_duration_spin.setRange(0.1, 60.0)
        self.bleach_duration_spin.setDecimals(1)
        self.bleach_duration_spin.setSingleStep(0.5)
        self.bleach_duration_spin.setSuffix(" min")
        self.bleach_duration_spin.valueChanged.connect(self._handle_settings_changed)
        bleach_layout.addWidget(self.bleach_duration_spin)

        self.start_bleach_button = QtWidgets.QPushButton("Start Bleach")
        self.start_bleach_button.clicked.connect(self._handle_start_bleach)
        bleach_layout.addWidget(self.start_bleach_button)

        self.stop_bleach_button = QtWidgets.QPushButton("Stop Bleach")
        self.stop_bleach_button.clicked.connect(self._handle_stop_bleach)
        bleach_layout.addWidget(self.stop_bleach_button)
        illum_form.addRow("Bleach", bleach_widget)

        self.bleach_status_label = QtWidgets.QLabel("Bleach idle")
        self.bleach_status_label.setWordWrap(True)
        self.bleach_status_label.setStyleSheet("QLabel { color: #5d6b7a; }")
        illum_form.addRow("Bleach State", self.bleach_status_label)

        self.teledyne_runtime_hint_label = QtWidgets.QLabel("-")
        self.teledyne_runtime_hint_label.setWordWrap(True)
        self.teledyne_runtime_hint_label.setStyleSheet("QLabel { color: #5d6b7a; }")
        self.teledyne_runtime_hint_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        illum_form.addRow("Current", self.teledyne_runtime_hint_label)

        return illum_group

    def _build_center_panel(self) -> QtWidgets.QWidget:
        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.center_tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.center_tabs, stretch=1)

        preview_tab = QtWidgets.QWidget()
        preview_layout = QtWidgets.QVBoxLayout(preview_tab)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(10)

        preview_toolbar = QtWidgets.QHBoxLayout()
        self.live_button = QtWidgets.QPushButton("Start Live")
        self.live_button.clicked.connect(self._handle_start_live)
        preview_toolbar.addWidget(self.live_button)

        self.stop_button = QtWidgets.QPushButton("Stop Live")
        self.stop_button.clicked.connect(self._handle_stop_live)
        preview_toolbar.addWidget(self.stop_button)

        self.snap_button = QtWidgets.QPushButton("Snap")
        self.snap_button.clicked.connect(self._handle_snap)
        preview_toolbar.addWidget(self.snap_button)

        self.acquire_state_label = QtWidgets.QLabel("Acquisition idle")
        self.acquire_state_label.setStyleSheet("QLabel { color: #5d6b7a; }")
        preview_toolbar.addWidget(self.acquire_state_label)

        self.autoscale_button = QtWidgets.QPushButton("Autoscale")
        self.autoscale_button.clicked.connect(self._handle_autoscale)
        preview_toolbar.addWidget(self.autoscale_button)

        preview_toolbar.addStretch(1)

        self.preview_state_label = QtWidgets.QLabel("Preview idle")
        self.preview_state_label.setStyleSheet("QLabel { color: #5d6b7a; }")
        preview_toolbar.addWidget(self.preview_state_label)

        preview_layout.addLayout(preview_toolbar)

        self.preview_widget = CameraPreviewWidget()
        preview_layout.addWidget(self.preview_widget, stretch=1)

        log_group = QtWidgets.QGroupBox("Event Log")
        log_layout = QtWidgets.QVBoxLayout(log_group)
        self.log_output = QtWidgets.QPlainTextEdit()
        self.log_output.setReadOnly(True)
        log_layout.addWidget(self.log_output)
        preview_layout.addWidget(log_group, stretch=0)

        self.center_tabs.addTab(preview_tab, "Preview")

        return content

    def _build_right_panel(self) -> QtWidgets.QWidget:
        container = QtWidgets.QScrollArea()
        container.setWidgetResizable(True)
        container.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        container.setMinimumWidth(340)
        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(self._build_micromanager_group())

        focus_group = QtWidgets.QGroupBox("Focus Lock and Z Scan")
        focus_form = QtWidgets.QFormLayout(focus_group)
        self._configure_form_layout(focus_form)

        module_widget = QtWidgets.QWidget()
        module_layout = QtWidgets.QHBoxLayout(module_widget)
        module_layout.setContentsMargins(0, 0, 0, 0)
        module_layout.setSpacing(6)

        self.open_focuslock_button = QtWidgets.QPushButton("Initialize")
        self.open_focuslock_button.clicked.connect(self._handle_open_focuslock_module)
        module_layout.addWidget(self.open_focuslock_button)

        self.close_focuslock_button = QtWidgets.QPushButton("Shutdown")
        self.close_focuslock_button.clicked.connect(self._handle_close_focuslock_module)
        module_layout.addWidget(self.close_focuslock_button)

        focus_form.addRow("Module", module_widget)

        self.focuslock_runtime_hint_label = QtWidgets.QLabel(
            "The legacy IX83 focus lock window stays hidden. This unified GUI is the only user-facing control surface."
        )
        self.focuslock_runtime_hint_label.setWordWrap(True)
        self.focuslock_runtime_hint_label.setStyleSheet("QLabel { color: #5d6b7a; }")
        focus_form.addRow("Runtime", self.focuslock_runtime_hint_label)

        action_widget = QtWidgets.QWidget()
        action_layout = QtWidgets.QHBoxLayout(action_widget)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(6)

        self.focuslock_toggle_lock_button = QtWidgets.QPushButton("Lock / Unlock")
        self.focuslock_toggle_lock_button.clicked.connect(self._handle_focuslock_toggle_lock)
        action_layout.addWidget(self.focuslock_toggle_lock_button)

        self.focuslock_jump_plus_button = QtWidgets.QPushButton("Jump +")
        self.focuslock_jump_plus_button.clicked.connect(self._handle_focuslock_jump_positive)
        action_layout.addWidget(self.focuslock_jump_plus_button)

        self.focuslock_jump_minus_button = QtWidgets.QPushButton("Jump -")
        self.focuslock_jump_minus_button.clicked.connect(self._handle_focuslock_jump_negative)
        action_layout.addWidget(self.focuslock_jump_minus_button)

        self.focuslock_scan_button = QtWidgets.QPushButton("Run Z Scan")
        self.focuslock_scan_button.clicked.connect(self._handle_focuslock_toggle_z_scan)
        action_layout.addWidget(self.focuslock_scan_button)

        focus_form.addRow("Actions", action_widget)

        self.focuslock_status_label = QtWidgets.QLabel()
        self.focuslock_status_label.setWordWrap(True)
        self.focuslock_status_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        focus_form.addRow("Module State", self.focuslock_status_label)

        self.focuslock_preview_widget = CameraPreviewWidget()
        self.focuslock_preview_widget.setMinimumHeight(320)
        self.focuslock_preview_widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.focuslock_preview_widget.set_overlay_visible(False)
        self.focuslock_preview_widget.set_info_visible(False)
        self.focuslock_preview_widget.set_chrome_visible(False)
        self.focuslock_preview_widget.set_auto_contrast_enabled(True, low_percentile=1.0, high_percentile=99.7)
        focus_form.addRow(self.focuslock_preview_widget)

        self.focuslock_metrics_label = QtWidgets.QLabel("Offset: - | Sum: -")
        self.focuslock_metrics_label.setWordWrap(True)
        self.focuslock_metrics_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        focus_form.addRow("Signal", self.focuslock_metrics_label)

        self.focus_mode_combo = QtWidgets.QComboBox()
        self.focus_mode_combo.addItems(["Off", "Always On", "Lock + Z Scan Calibration"])
        self.focus_mode_combo.currentTextChanged.connect(self._handle_settings_changed)
        focus_form.addRow("Mode", self.focus_mode_combo)

        self.focus_locked_checkbox = QtWidgets.QCheckBox("Locked")
        self.focus_locked_checkbox.stateChanged.connect(self._handle_settings_changed)
        focus_form.addRow("Lock State", self.focus_locked_checkbox)

        self.jump_offset_spin = QtWidgets.QDoubleSpinBox()
        self.jump_offset_spin.setRange(-1000.0, 1000.0)
        self.jump_offset_spin.setDecimals(2)
        self.jump_offset_spin.setSuffix(" um")
        self.jump_offset_spin.valueChanged.connect(self._handle_settings_changed)
        focus_form.addRow("Jump Offset", self.jump_offset_spin)

        self.z_start_spin = QtWidgets.QDoubleSpinBox()
        self.z_start_spin.setRange(-1000.0, 1000.0)
        self.z_start_spin.setDecimals(3)
        self.z_start_spin.setSuffix(" um")
        self.z_start_spin.valueChanged.connect(self._handle_focuslock_range_changed)
        focus_form.addRow("Z Start", self.z_start_spin)

        self.z_end_spin = QtWidgets.QDoubleSpinBox()
        self.z_end_spin.setRange(-1000.0, 1000.0)
        self.z_end_spin.setDecimals(3)
        self.z_end_spin.setSuffix(" um")
        self.z_end_spin.valueChanged.connect(self._handle_focuslock_range_changed)
        focus_form.addRow("Z End", self.z_end_spin)

        self.z_step_spin = QtWidgets.QDoubleSpinBox()
        self.z_step_spin.setRange(-1000.0, 1000.0)
        self.z_step_spin.setDecimals(4)
        self.z_step_spin.setSuffix(" um")
        self.z_step_spin.valueChanged.connect(self._handle_focuslock_step_changed)
        focus_form.addRow("Z Step", self.z_step_spin)

        self.depth_count_spin = QtWidgets.QSpinBox()
        self.depth_count_spin.setRange(1, 1000)
        self.depth_count_spin.valueChanged.connect(self._handle_focuslock_range_changed)
        focus_form.addRow("Depth Count", self.depth_count_spin)

        self.frames_per_round_spin = QtWidgets.QSpinBox()
        self.frames_per_round_spin.setRange(1, 1000000)
        self.frames_per_round_spin.valueChanged.connect(self._handle_settings_changed)
        focus_form.addRow("Frames / Depth / Round", self.frames_per_round_spin)

        layout.addWidget(focus_group)

        focuslock_advanced_group = QtWidgets.QGroupBox("Advanced Focus Lock Parameters")
        focuslock_advanced_form = QtWidgets.QFormLayout(focuslock_advanced_group)
        self._configure_form_layout(focuslock_advanced_form)

        self.focuslock_prior_com_spin = QtWidgets.QSpinBox()
        self.focuslock_prior_com_spin.setRange(1, 256)
        self.focuslock_prior_com_spin.valueChanged.connect(self._handle_settings_changed)
        focuslock_advanced_form.addRow("Prior COM", self.focuslock_prior_com_spin)

        self.focuslock_qpd_center_spin = QtWidgets.QDoubleSpinBox()
        self.focuslock_qpd_center_spin.setRange(0.0, 1000.0)
        self.focuslock_qpd_center_spin.setDecimals(3)
        self.focuslock_qpd_center_spin.setSuffix(" um")
        self.focuslock_qpd_center_spin.valueChanged.connect(self._handle_settings_changed)
        focuslock_advanced_form.addRow("QPD Z Center", self.focuslock_qpd_center_spin)

        self.focuslock_qpd_scale_spin = QtWidgets.QDoubleSpinBox()
        self.focuslock_qpd_scale_spin.setRange(0.0, 10000.0)
        self.focuslock_qpd_scale_spin.setDecimals(4)
        self.focuslock_qpd_scale_spin.valueChanged.connect(self._handle_settings_changed)
        focuslock_advanced_form.addRow("QPD Scale", self.focuslock_qpd_scale_spin)

        self.focuslock_sum_min_spin = QtWidgets.QDoubleSpinBox()
        self.focuslock_sum_min_spin.setRange(0.0, 10000.0)
        self.focuslock_sum_min_spin.setDecimals(1)
        self.focuslock_sum_min_spin.valueChanged.connect(self._handle_settings_changed)
        focuslock_advanced_form.addRow("Min Sum", self.focuslock_sum_min_spin)

        self.focuslock_sum_max_spin = QtWidgets.QDoubleSpinBox()
        self.focuslock_sum_max_spin.setRange(1.0, 10000.0)
        self.focuslock_sum_max_spin.setDecimals(1)
        self.focuslock_sum_max_spin.valueChanged.connect(self._handle_settings_changed)
        focuslock_advanced_form.addRow("Max Sum", self.focuslock_sum_max_spin)

        self.focuslock_lock_step_spin = QtWidgets.QDoubleSpinBox()
        self.focuslock_lock_step_spin.setRange(0.0, 10.0)
        self.focuslock_lock_step_spin.setDecimals(4)
        self.focuslock_lock_step_spin.setSuffix(" um")
        self.focuslock_lock_step_spin.valueChanged.connect(self._handle_settings_changed)
        focuslock_advanced_form.addRow("Wheel Step", self.focuslock_lock_step_spin)

        self.focuslock_buffer_spin = QtWidgets.QSpinBox()
        self.focuslock_buffer_spin.setRange(1, 1000)
        self.focuslock_buffer_spin.valueChanged.connect(self._handle_settings_changed)
        focuslock_advanced_form.addRow("Lock Buffer", self.focuslock_buffer_spin)

        self.focuslock_offset_thresh_spin = QtWidgets.QDoubleSpinBox()
        self.focuslock_offset_thresh_spin.setRange(0.0, 1000.0)
        self.focuslock_offset_thresh_spin.setDecimals(4)
        self.focuslock_offset_thresh_spin.valueChanged.connect(self._handle_settings_changed)
        focuslock_advanced_form.addRow("Offset Thresh", self.focuslock_offset_thresh_spin)

        focuslock_advanced_note = QtWidgets.QLabel(
            "Changes to Prior COM take effect the next time the focus lock runtime is initialized."
        )
        focuslock_advanced_note.setWordWrap(True)
        focuslock_advanced_note.setStyleSheet("QLabel { color: #5d6b7a; }")
        focuslock_advanced_form.addRow("Note", focuslock_advanced_note)

        layout.addWidget(focuslock_advanced_group)

        zplan_group = QtWidgets.QGroupBox("Z Scan Planner")
        zplan_form = QtWidgets.QFormLayout(zplan_group)
        self._configure_form_layout(zplan_form)
        self.zplan_labels = {}
        for key in [
            "Step Size",
            "Target Frames / Depth",
            "Full Rounds",
            "Total Rounds",
            "Last Round Frames",
            "Total Frames All Depths",
            "Exposure",
            "Trigger",
        ]:
            label = QtWidgets.QLabel("-")
            label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            self.zplan_labels[key] = label
            zplan_form.addRow(key, label)
        layout.addWidget(zplan_group)

        layout.addStretch(1)
        container.setWidget(content)
        return container

    def _wrap_with_button(self, editor: QtWidgets.QWidget, button: QtWidgets.QPushButton) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(editor, stretch=1)
        layout.addWidget(button)
        return widget

    def _wrap_layout(self, child_layout: QtWidgets.QLayout) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(child_layout)
        return widget

    def _set_cfg_choices(self, selected_path: Path) -> None:
        cfg_paths = []
        if self.settings.paths.micromanager_root.exists():
            cfg_paths = sorted(str(path) for path in self.settings.paths.micromanager_root.glob("*.cfg"))

        selected_text = str(selected_path)
        if selected_text and selected_text not in cfg_paths:
            cfg_paths.append(selected_text)

        self.cfg_combo.blockSignals(True)
        self.cfg_combo.clear()
        for cfg_path in cfg_paths:
            self.cfg_combo.addItem(_compact_path_label(cfg_path), cfg_path)
            self.cfg_combo.setItemData(self.cfg_combo.count() - 1, cfg_path, QtCore.Qt.ToolTipRole)

        index = self.cfg_combo.findData(selected_text)
        if index >= 0:
            self.cfg_combo.setCurrentIndex(index)
        self.cfg_combo.blockSignals(False)

    def _current_cfg_path(self) -> str:
        current_data = self.cfg_combo.currentData()
        if current_data:
            return str(current_data)
        return str(self.settings.paths.micromanager_cfg)

    def _load_settings_into_widgets(self) -> None:
        self._updating_ui = True
        try:
            acquisition = self.settings.acquisition
            bleach = self.settings.bleach
            illumination = self.settings.illumination
            focus_lock = self.settings.focus_lock

            self._set_cfg_choices(self.settings.paths.micromanager_cfg)
            self.sample_name_edit.setText(acquisition.sample_name)
            self.save_prefix_edit.setText(acquisition.save_prefix)
            self.save_root_edit.set_full_path(acquisition.save_root)
            self.roi_name_edit.set_full_path(acquisition.roi_name)
            self.exposure_spin.setValue(acquisition.exposure_ms)
            self.trigger_combo.setCurrentText(acquisition.trigger_mode)
            self.saving_format_combo.setCurrentText(acquisition.saving_format)
            self.widefield_frames_spin.setValue(acquisition.widefield_frames)
            self.storm_frames_spin.setValue(acquisition.storm_total_frames)
            self.channel_642_enabled_checkbox.setChecked(illumination.channel_642_enabled)
            self.laser_642_power_spin.setValue(illumination.laser_642_setpoint)
            self.aotf_642_enabled_checkbox.setChecked(illumination.aotf_642_enabled)
            self.aotf_642_spin.setValue(illumination.aotf_642_setpoint)
            self.modulation_mode_combo.setCurrentText(illumination.modulation_mode)
            self.bleach_duration_spin.setValue(bleach.duration_minutes)
            self.focus_mode_combo.setCurrentText(focus_lock.mode)
            self.focus_locked_checkbox.setChecked(focus_lock.locked)
            self.jump_offset_spin.setValue(focus_lock.jump_offset_um)
            self.z_start_spin.setValue(focus_lock.z_start_um)
            self.z_end_spin.setValue(focus_lock.z_end_um)
            self.z_step_spin.setValue(compute_z_step_um(self.settings))
            self.depth_count_spin.setValue(focus_lock.depth_count)
            self.frames_per_round_spin.setValue(focus_lock.frames_per_depth_per_round)
            self.focuslock_prior_com_spin.setValue(focus_lock.prior_com_port)
            self.focuslock_qpd_center_spin.setValue(focus_lock.qpd_zcenter_um)
            self.focuslock_qpd_scale_spin.setValue(focus_lock.qpd_scale)
            self.focuslock_sum_min_spin.setValue(focus_lock.qpd_sum_min)
            self.focuslock_sum_max_spin.setValue(focus_lock.qpd_sum_max)
            self.focuslock_lock_step_spin.setValue(focus_lock.lock_step_um)
            self.focuslock_buffer_spin.setValue(focus_lock.is_locked_buffer_length)
            self.focuslock_offset_thresh_spin.setValue(focus_lock.is_locked_offset_thresh)
        finally:
            self._updating_ui = False

    def _pull_settings_from_widgets(self) -> None:
        acquisition = self.settings.acquisition
        bleach = self.settings.bleach
        illumination = self.settings.illumination
        focus_lock = self.settings.focus_lock
        acquisition_defaults = get_default_section("acquisition")

        acquisition.sample_name = self.sample_name_edit.text().strip()
        acquisition.save_prefix = self.save_prefix_edit.text().strip()
        acquisition.save_root = self.save_root_edit.full_path() or str(acquisition_defaults.get("save_root", ""))
        acquisition.roi_name = self.roi_name_edit.full_path() or str(self.settings.paths.roi_file)
        acquisition.trigger_mode = self.trigger_combo.currentText()
        acquisition.saving_format = self.saving_format_combo.currentText()
        acquisition.widefield_frames = self.widefield_frames_spin.value()
        acquisition.storm_total_frames = self.storm_frames_spin.value()
        self.settings.paths.micromanager_cfg = Path(self._current_cfg_path())

        illumination.channel_642_enabled = self.channel_642_enabled_checkbox.isChecked()
        illumination.laser_642_setpoint = self.laser_642_power_spin.value()
        illumination.aotf_642_enabled = self.aotf_642_enabled_checkbox.isChecked()
        illumination.aotf_642_setpoint = self.aotf_642_spin.value()
        illumination.modulation_mode = self.modulation_mode_combo.currentText()
        bleach.duration_minutes = self.bleach_duration_spin.value()

        focus_lock.mode = self.focus_mode_combo.currentText()
        focus_lock.locked = self.focus_locked_checkbox.isChecked()
        focus_lock.jump_offset_um = self.jump_offset_spin.value()
        focus_lock.z_start_um = self.z_start_spin.value()
        focus_lock.z_end_um = self.z_end_spin.value()
        focus_lock.depth_count = self.depth_count_spin.value()
        focus_lock.frames_per_depth_per_round = self.frames_per_round_spin.value()
        focus_lock.prior_com_port = self.focuslock_prior_com_spin.value()
        focus_lock.qpd_zcenter_um = self.focuslock_qpd_center_spin.value()
        focus_lock.qpd_scale = self.focuslock_qpd_scale_spin.value()
        focus_lock.qpd_sum_min = self.focuslock_sum_min_spin.value()
        focus_lock.qpd_sum_max = self.focuslock_sum_max_spin.value()
        focus_lock.lock_step_um = self.focuslock_lock_step_spin.value()
        focus_lock.is_locked_buffer_length = self.focuslock_buffer_spin.value()
        focus_lock.is_locked_offset_thresh = self.focuslock_offset_thresh_spin.value()

    def _refresh_all_views(self, log_message: str | None = None) -> None:
        self.z_scan_plan = compute_z_scan_plan(self.settings)
        self._apply_theme(self.settings.state.theme)
        self.active_preset_label.setText(f"Active Preset: {self.settings.state.active_preset}")
        self._update_banner()
        self._update_preview_overlay()
        self._update_save_plan_preview()
        self._refresh_illumination_targets()
        self._refresh_module_status_labels()
        self._refresh_z_plan_labels()
        if log_message:
            self._append_log(log_message)

    def _update_banner(self) -> None:
        plan = self.z_scan_plan
        mode_text = "Inspection" if self.settings.state.inspection_mode else "Live"
        backend_text = "Loaded" if self._last_snapshot.running else "Idle"
        stage_text = self._format_stage_summary(self._last_snapshot)
        self.banner_label.setText(
            f"Preset: {self.settings.state.active_preset} | {mode_text} mode | Embedded MM: {backend_text} | "
            f"Exposure: {self.settings.acquisition.exposure_ms:.1f} ms | Trigger: {self.settings.acquisition.trigger_mode} | "
            f"Whole-cell Z: {plan.depth_count} depths, {plan.frames_per_depth_per_round} frames/depth/round | "
            f"Stage: {stage_text}"
        )

    def _update_preview_overlay(self) -> None:
        snapshot = self._last_snapshot
        if snapshot.roi is None:
            roi_text = "full frame"
        else:
            roi_text = f"x={snapshot.roi.x}, y={snapshot.roi.y}, w={snapshot.roi.width}, h={snapshot.roi.height}"
        if snapshot.running:
            cfg_name = Path(snapshot.cfg_path).name if snapshot.cfg_path else Path(self.settings.paths.micromanager_cfg).name
            overlay = [
                "Embedded Micro-Manager backend",
                f"CFG: {cfg_name}",
                f"ROI: {roi_text}",
                f"Exposure: {snapshot.exposure_ms:.1f} ms" if snapshot.exposure_ms else "Exposure: -",
            ]
        else:
            overlay = [
                "Embedded Micro-Manager backend",
                f"CFG: {Path(self.settings.paths.micromanager_cfg).name or '-'}",
                "Select a cfg and click Load Config.",
                f"ROI preset: {Path(self.settings.acquisition.roi_name).name or self.settings.acquisition.roi_name}",
            ]
        if snapshot.last_save_path:
            overlay.append(f"Last Save: {Path(snapshot.last_save_path).name}")
        overlay.append(f"Stage: {self._format_stage_summary(snapshot)}")
        self.preview_widget.set_overlay_text("\n".join(overlay))

    def _update_save_plan_preview(self) -> None:
        if not hasattr(self, "save_plan_label"):
            return
        plan = build_acquisition_path_plan(self.settings, preview_only=True)
        if plan.dataset_path is not None:
            mda_text = f"MDA: {plan.dataset_path}"
        elif self.settings.acquisition.saving_format.strip().lower() == "image stack file":
            mda_text = "MDA: temporary export only (not kept)"
        else:
            mda_text = "MDA: streaming TIFF only"
        self.save_plan_label.setText(
            "\n".join(
                [
                    plan.session_folder_name,
                    f"Primary: {plan.output_path}",
                    mda_text,
                    f"Session timestamp: {self.settings.state.session_timestamp_prefix}",
                    "Folder naming: [optional prefix]_[launch timestamp]_[optional sample]",
                    "No trial suffix is added.",
                ]
            )
        )
        self.save_plan_label.setToolTip(str(plan.output_path))

    def _apply_theme(self, theme_name: str) -> None:
        is_dark = theme_name == "Dark"
        palette = QtGui.QPalette()
        if is_dark:
            palette.setColor(QtGui.QPalette.Window, QtGui.QColor("#19232d"))
            palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor("#e8eef5"))
            palette.setColor(QtGui.QPalette.Base, QtGui.QColor("#111820"))
            palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor("#1d2630"))
            palette.setColor(QtGui.QPalette.Text, QtGui.QColor("#e8eef5"))
            palette.setColor(QtGui.QPalette.Button, QtGui.QColor("#243140"))
            palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor("#eef4fa"))
            palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor("#3d8bfd"))
            palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor("#ffffff"))
            self.setPalette(palette)
            self.setStyleSheet(
                """
                QMainWindow, QWidget { background: #19232d; color: #e8eef5; }
                QGroupBox { border: 1px solid #3a4653; border-radius: 6px; margin-top: 12px; padding-top: 8px; }
                QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #9fc2ff; }
                QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox, QPlainTextEdit, QTableWidget {
                    background: #111820; color: #e8eef5; border: 1px solid #405063; border-radius: 4px;
                }
                QPushButton { background: #243140; color: #eef4fa; border: 1px solid #49617a; border-radius: 4px; padding: 5px 8px; }
                QPushButton:hover { background: #2d3d50; }
                QHeaderView::section { background: #243140; color: #eef4fa; }
                """
            )
            self.banner_label.setStyleSheet(
                "QLabel { background: #233244; color: #d8e7f6; padding: 8px 10px; border: 1px solid #48637c; border-radius: 6px; }"
            )
            self.active_preset_label.setStyleSheet("QLabel { color: #8bb8ff; font-weight: 600; }")
            self.preview_state_label.setStyleSheet("QLabel { color: #b6c6d7; }")
        else:
            self.style().unpolish(self)
            self.style().polish(self)
            self.setPalette(self.style().standardPalette())
            self.setStyleSheet(
                """
                QGroupBox { border: 1px solid #ced6de; border-radius: 6px; margin-top: 12px; padding-top: 8px; }
                QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #244b6b; }
                QPushButton { padding: 5px 8px; }
                """
            )
            self.banner_label.setStyleSheet(
                "QLabel { background: #eef5fb; color: #1f3342; padding: 8px 10px; border: 1px solid #c8d8e8; border-radius: 6px; }"
            )
            self.active_preset_label.setStyleSheet("QLabel { color: #0f4c81; font-weight: 600; }")
            self.preview_state_label.setStyleSheet("QLabel { color: #5d6b7a; }")

    def _refresh_z_plan_labels(self) -> None:
        plan = self.z_scan_plan
        self.zplan_labels["Step Size"].setText(f"{plan.step_um:.3f} um")
        self.zplan_labels["Target Frames / Depth"].setText(str(plan.total_frames_per_depth_target))
        self.zplan_labels["Full Rounds"].setText(str(plan.full_rounds))
        self.zplan_labels["Total Rounds"].setText(str(plan.rounds))
        self.zplan_labels["Last Round Frames"].setText(str(plan.last_round_frames_per_depth))
        self.zplan_labels["Total Frames All Depths"].setText(str(plan.total_frames_all_depths))
        self.zplan_labels["Exposure"].setText(f"{plan.exposure_ms:.1f} ms")
        self.zplan_labels["Trigger"].setText(plan.trigger_mode)

    def _refresh_module_status_labels(self) -> None:
        if hasattr(self, "teledyne_status_label"):
            snapshot = self.teledyne_controller.ui_snapshot()
            if self.teledyne_controller.last_error:
                self.teledyne_status_label.setText(f"Unavailable: {self.teledyne_controller.last_error}")
            else:
                self.teledyne_status_label.setText("Ready for direct 642 / AOTF runtime control.")
            self.teledyne_status_label.setToolTip(snapshot.status)
        if hasattr(self, "focuslock_status_label"):
            self.focuslock_status_label.setText(self.focuslock_controller.status_text())
        if hasattr(self, "open_focuslock_button"):
            self.open_focuslock_button.setText("Initialize" if not self.focuslock_controller.is_open() else "Sync Runtime")
        if hasattr(self, "close_focuslock_button"):
            self.close_focuslock_button.setEnabled(self.focuslock_controller.is_open())
        if hasattr(self, "focuslock_toggle_lock_button"):
            self.focuslock_toggle_lock_button.setText(
                "Unlock" if self.focuslock_controller.is_locked() else "Lock"
            )
        if hasattr(self, "focuslock_scan_button"):
            self.focuslock_scan_button.setText(
                "Stop Z Scan" if self.focuslock_controller.is_scanning() else "Run Z Scan"
            )
        if hasattr(self, "focuslock_preview_widget") and not self.focuslock_controller.has_preview():
            self.focuslock_preview_widget.clear()

    def _refresh_illumination_targets(self) -> None:
        if not hasattr(self, "teledyne_runtime_hint_label"):
            return

        snapshot = self.teledyne_controller.ui_snapshot()
        illumination = self.settings.illumination
        current_text = (
            f"642 {'On' if illumination.channel_642_enabled else 'Off'} at {illumination.laser_642_setpoint:.1f} mW | "
            f"AOTF {'On' if illumination.aotf_642_enabled else 'Off'} at {illumination.aotf_642_setpoint:.1f} | "
            f"{illumination.modulation_mode}"
        )
        self.teledyne_runtime_hint_label.setText(current_text)
        self.teledyne_runtime_hint_label.setToolTip(
            "\n".join(
                [
                    snapshot.laser_summary,
                    snapshot.aotf_summary,
                    f"Camera sync: {snapshot.camera_sync_summary}",
                    f"NI-DAQ: {snapshot.daq_summary}",
                    f"Safe shutdown: {snapshot.safe_shutdown_summary}",
                ]
            )
        )

    def _handle_settings_changed(self) -> None:
        if self._updating_ui:
            return
        self._pull_settings_from_widgets()
        self.teledyne_controller.sync_from_settings(self.settings)
        if self.focuslock_controller.is_open():
            try:
                self.focuslock_controller.sync_from_settings(self.settings)
            except Exception as exc:
                self._append_log(f"Integrated focus lock sync failed: {exc}")
        self._refresh_all_views()

    def _handle_focuslock_range_changed(self, *_args) -> None:
        if self._updating_ui:
            return

        step_um = compute_z_step_from_scan_inputs(
            self.z_start_spin.value(),
            self.z_end_spin.value(),
            self.depth_count_spin.value(),
        )
        self._updating_ui = True
        try:
            self.z_step_spin.setValue(step_um)
        finally:
            self._updating_ui = False
        self._handle_settings_changed()

    def _handle_focuslock_step_changed(self, *_args) -> None:
        if self._updating_ui:
            return

        depth_count = depth_count_from_scan_inputs(
            self.z_start_spin.value(),
            self.z_end_spin.value(),
            self.z_step_spin.value(),
        )
        snapped_step = compute_z_step_from_scan_inputs(
            self.z_start_spin.value(),
            self.z_end_spin.value(),
            depth_count,
        )
        self._updating_ui = True
        try:
            self.depth_count_spin.setValue(depth_count)
            self.z_step_spin.setValue(snapped_step)
        finally:
            self._updating_ui = False
        self._handle_settings_changed()

    def _handle_exposure_changed(self, value: float) -> None:
        if self._updating_ui:
            return
        self.settings.acquisition.exposure_ms = float(value)
        self.teledyne_controller.sync_from_settings(self.settings)
        self.request_set_exposure.emit(float(value))
        self._refresh_all_views()

    def _handle_trigger_mode_changed(self, _value: str) -> None:
        if self._updating_ui:
            return
        self._pull_settings_from_widgets()
        if self._last_snapshot.running:
            self.request_apply_trigger_mode.emit(self.settings.acquisition.trigger_mode)
        self.teledyne_controller.sync_from_settings(self.settings)
        self._refresh_all_views()

    def _validate_focus_lock_for_advanced_preset(self, preset_name: str) -> tuple[bool, str]:
        if preset_name not in {"STORM 2D", "Whole-Cell Z Scan"}:
            return True, ""
        if not self.focuslock_controller.is_open():
            return (
                False,
                f"{preset_name} requires the focus lock runtime to be initialized first. Find focus, then manually lock before switching presets.",
            )
        if not self.focuslock_controller.is_locked():
            return (
                False,
                f"{preset_name} requires a manual focus lock. Find focus and press Lock before switching presets.",
            )
        self.settings.focus_lock.locked = True
        return True, ""

    def _apply_preset(self, preset_name: str) -> None:
        self._pull_settings_from_widgets()
        allowed, message = self._validate_focus_lock_for_advanced_preset(preset_name)
        if not allowed:
            self._append_log(message)
            QtWidgets.QMessageBox.warning(self, "Focus Lock Required", message)
            self.statusBar().showMessage(message, 8000)
            return
        apply_preset(self.settings, preset_name)
        self.teledyne_controller.sync_from_settings(self.settings)
        self._load_settings_into_widgets()
        if self.focuslock_controller.is_open():
            try:
                self.focuslock_controller.sync_from_settings(self.settings)
            except Exception as exc:
                self._append_log(f"Integrated focus lock sync failed: {exc}")
        if self._last_snapshot.running:
            self.request_set_exposure.emit(float(self.settings.acquisition.exposure_ms))
            self.request_apply_trigger_mode.emit(self.settings.acquisition.trigger_mode)
        self._refresh_all_views(log_message=f"Applied preset: {preset_name}")
        self._apply_teledyne_runtime(reason=f"preset {preset_name}", show_dialog=False)
        self._log_preset_guidance(preset_name)

    def _load_selected_cfg(self) -> None:
        self._pull_settings_from_widgets()
        cfg_path = str(self.settings.paths.micromanager_cfg)
        self.preview_widget.clear()
        self.preview_widget.set_overlay_text(f"Loading config...\n{cfg_path}")
        self.request_load_config.emit(cfg_path)
        self.request_set_exposure.emit(float(self.settings.acquisition.exposure_ms))
        roi_path = str(self.settings.acquisition.roi_name or "").strip()
        if roi_path and Path(roi_path).exists():
            self.request_apply_roi.emit(roi_path)

    def _handle_refresh_backend(self) -> None:
        self.request_refresh.emit()
        self._refresh_all_views()

    def _handle_start_live(self) -> None:
        self.settings.state.preview_running = True
        self.request_start_live.emit()

    def _handle_stop_live(self) -> None:
        self.settings.state.preview_running = False
        self.request_stop_live.emit()

    def _handle_snap(self) -> None:
        self.request_snap.emit()

    def _handle_run_acquisition(self) -> None:
        self._pull_settings_from_widgets()
        if not self._last_snapshot.running:
            QtWidgets.QMessageBox.warning(self, "Acquisition", "Load a Micro-Manager cfg before starting acquisition.")
            return

        preset_name = self.settings.state.active_preset
        coordinated_focus_lock_scan = preset_name == "Whole-Cell Z Scan"
        allowed, message = self._validate_focus_lock_for_advanced_preset(preset_name)
        if not allowed:
            self._append_log(message)
            QtWidgets.QMessageBox.warning(self, "Focus Lock Required", message)
            self.statusBar().showMessage(message, 8000)
            return
        if preset_name in {"ROI Preview", "Widefield Test"}:
            frame_count = self.settings.acquisition.widefield_frames
        else:
            frame_count = self.settings.acquisition.storm_total_frames

        if coordinated_focus_lock_scan:
            if self.settings.acquisition.trigger_mode != "External":
                QtWidgets.QMessageBox.warning(
                    self,
                    "Acquisition",
                    "Whole-Cell Z Scan requires External trigger mode so the camera can arm first and wait for DAQ pulses.",
                )
                return
            if self.settings.illumination.modulation_mode != "one-chan FSK mode":
                QtWidgets.QMessageBox.warning(
                    self,
                    "Acquisition",
                    "Whole-Cell Z Scan expects the illumination path to use 'one-chan FSK mode' so the camera exposure output can gate the AOTF.",
                )
                return
            success, message = self._ensure_focuslock_module_ready()
            if not success:
                QtWidgets.QMessageBox.warning(self, "Focus Lock", message)
                return
            illumination_success, _illumination_message = self._apply_teledyne_runtime(
                reason="whole-cell acquisition arm",
                show_dialog=True,
            )
            if not illumination_success:
                return
        elif preset_name == "STORM 2D":
            if self.settings.illumination.modulation_mode != "one-chan FSK mode":
                QtWidgets.QMessageBox.warning(
                    self,
                    "Acquisition",
                    "STORM 2D expects the illumination path to use 'one-chan FSK mode' so the camera exposure output can gate the AOTF.",
                )
                return
            illumination_success, _illumination_message = self._apply_teledyne_runtime(
                reason="storm 2d acquisition arm",
                show_dialog=True,
            )
            if not illumination_success:
                return

        plan = build_acquisition_path_plan(self.settings)
        self._pending_external_scan_reply = False
        self.request_set_exposure.emit(float(self.settings.acquisition.exposure_ms))
        self.request_apply_trigger_mode.emit(self.settings.acquisition.trigger_mode)
        round_frames = build_round_frames_per_depth(self.z_scan_plan) if coordinated_focus_lock_scan else ()

        request = MDAAcquisitionRequest(
            preset_name=preset_name,
            frame_count=int(frame_count),
            expected_image_count=(
                int(frame_count) * max(1, self.settings.focus_lock.depth_count)
                if preset_name == "Whole-Cell Z Scan"
                else int(frame_count)
            ),
            saving_format=self.settings.acquisition.saving_format,
            base_name=plan.base_name,
            save_dir=str(plan.save_dir),
            output_path=str(plan.output_path),
            dataset_name=plan.dataset_name,
            dataset_path=str(plan.dataset_path),
            exposure_ms=float(self.settings.acquisition.exposure_ms),
            trigger_mode=self.settings.acquisition.trigger_mode,
            z_start_um=float(self.settings.focus_lock.z_start_um),
            z_end_um=float(self.settings.focus_lock.z_end_um),
            z_step_um=float(self.z_scan_plan.step_um),
            depth_count=int(self.settings.focus_lock.depth_count),
            coordinated_focus_lock_scan=coordinated_focus_lock_scan,
            z_round_frames_per_depth=round_frames,
        )
        self._active_acquisition_request = request
        self.request_run_acquisition.emit(request)
        self.acquire_state_label.setText("Acquisition running")
        self._append_log(f"Planned primary output: {plan.output_path}")
        if plan.dataset_path is not None:
            self._append_log(f"Planned MDA dataset: {plan.dataset_path}")
        elif self.settings.acquisition.saving_format.strip().lower() == "image stack file":
            self._append_log("Planned MDA dataset: temporary export only (not kept).")
        else:
            self._append_log("Planned MDA dataset: streaming TIFF only")
        if coordinated_focus_lock_scan:
            self._append_whole_cell_round_summary(request, state="planned")
            self._append_log(
                "Whole-cell Z scan acquisition will arm the camera first, then let the integrated focus lock drive Z motion and DAQ trigger pulses."
            )

    def _handle_stop_acquisition(self) -> None:
        self.request_stop_acquisition.emit()
        if self.focuslock_controller.is_scanning():
            stop_success, stop_message = self.focuslock_controller.stop_active_scan()
            if stop_message:
                self._append_log(stop_message)
        self.acquire_state_label.setText("Stopping acquisition...")

    def _handle_autoscale(self) -> None:
        self.preview_widget.autoscale()
        self._append_log("Autoscaled the preview.")

    def _apply_roi_file(self) -> None:
        roi_path = self.roi_name_edit.full_path().strip()
        self.settings.acquisition.roi_name = roi_path
        self.request_apply_roi.emit(roi_path)

    def _handle_clear_roi(self) -> None:
        self.request_clear_roi.emit()

    def _browse_cfg_file(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Micro-Manager cfg",
            str(self.settings.paths.micromanager_root),
            "Micro-Manager cfg (*.cfg);;All files (*.*)",
        )
        if path:
            self.settings.paths.micromanager_cfg = Path(path)
            self._set_cfg_choices(self.settings.paths.micromanager_cfg)
            self._handle_settings_changed()

    def _browse_save_root(self) -> None:
        selected = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Select Save Root",
            self.save_root_edit.full_path().strip() or str(Path.home()),
        )
        if selected:
            self.save_root_edit.set_full_path(selected)
            self._handle_settings_changed()

    def _browse_roi_file(self) -> None:
        start_path = self.roi_name_edit.full_path().strip()
        if not start_path:
            start_path = str(self.settings.paths.roi_file.parent)
        selected, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select ROI Preset",
            start_path,
            "ROI Files (*.roi);;All Files (*.*)",
        )
        if selected:
            self.roi_name_edit.set_full_path(selected)
            self.settings.paths.roi_file = Path(selected)
            self._handle_settings_changed()

    def _handle_snapshot(self, snapshot: MicroManagerSnapshot) -> None:
        self._last_snapshot = snapshot
        self.settings.state.preview_running = snapshot.live_running
        self.mm_status_label.setText(snapshot.status_message)
        self.mm_stage_position_label.setText(self._format_detailed_stage_summary(snapshot))
        if snapshot.acquisition_running:
            self.preview_state_label.setText("Acquiring")
            self.acquire_state_label.setText("Acquisition running")
        elif snapshot.running and snapshot.live_running:
            self.preview_state_label.setText("Live running")
            self.acquire_state_label.setText("Acquisition idle")
        elif snapshot.running:
            self.preview_state_label.setText("Config loaded")
            self.acquire_state_label.setText("Acquisition idle")
        else:
            self.preview_state_label.setText("Preview idle")
            self.acquire_state_label.setText("Acquisition idle")

        self._updating_ui = True
        try:
            if snapshot.exposure_ms > 0:
                self.exposure_spin.setValue(snapshot.exposure_ms)
        finally:
            self._updating_ui = False

        self._update_preview_overlay()
        self._update_banner()
        self._append_log(snapshot.status_message)

    def _handle_frame(self, frame) -> None:
        self.preview_widget.set_frame(frame)

    def _handle_acquisition_finished(self, success: bool, message: str) -> None:
        completed_request = self._active_acquisition_request
        self._active_acquisition_request = None
        self.acquire_state_label.setText("Acquisition idle")
        self._pending_external_scan_reply = False
        if not success and self.focuslock_controller.is_scanning():
            stop_success, stop_message = self.focuslock_controller.stop_active_scan()
            if stop_message:
                self._append_log(stop_message)
        self._append_log(message)
        if completed_request is not None and completed_request.coordinated_focus_lock_scan:
            self._append_whole_cell_round_summary(
                completed_request,
                state="completed" if success else "interrupted",
            )
        if not success:
            self.statusBar().showMessage(message, 8000)

    def _handle_focuslock_preview(self, preview_data: object) -> None:
        if not isinstance(preview_data, dict):
            return
        frame = preview_data.get("frame")
        if not isinstance(frame, numpy.ndarray):
            return
        circles = preview_data.get("circles")
        if not isinstance(circles, list):
            circles = None
        self.focuslock_preview_widget.set_frame(frame, circles=circles, auto_contrast=True)

    def _handle_focuslock_status(self, offset: float, power: float) -> None:
        self.focuslock_metrics_label.setText(f"Offset: {offset:.4f} | Sum: {power:.1f}")

    def _handle_focuslock_stage_position(self, stage_z_um: float) -> None:
        self._focuslock_stage_z_um = float(stage_z_um)
        self.mm_stage_position_label.setText(self._format_detailed_stage_summary(self._last_snapshot))
        self._update_banner()
        self._update_preview_overlay()

    def _handle_focuslock_scan_finished(self, success: bool, message: str) -> None:
        self._append_log(message)
        self._refresh_all_views()
        if self._pending_external_scan_reply:
            self.request_resolve_external_scan.emit(success, message)
            self._pending_external_scan_reply = False

    def _handle_focuslock_ui_state_changed(self) -> None:
        if self._updating_ui:
            return
        try:
            self.focuslock_controller.sync_to_settings(self.settings)
        except Exception as exc:
            self._append_log(f"Integrated focus lock state sync failed: {exc}")
            return
        self._load_settings_into_widgets()
        self._refresh_all_views()

    def _handle_external_scan_requested(self, request: object) -> None:
        if not isinstance(request, MDAAcquisitionRequest):
            self.request_resolve_external_scan.emit(False, f"Unsupported external scan request type: {type(request).__name__}")
            return
        success, message = self._ensure_focuslock_module_ready()
        if not success:
            self.request_resolve_external_scan.emit(False, message)
            return
        self._pending_external_scan_reply = True
        success, message = self.focuslock_controller.run_coordinated_whole_cell_scan(request)
        self._append_log(message)
        self._refresh_all_views()
        if not success:
            self.request_resolve_external_scan.emit(False, message)
            self._pending_external_scan_reply = False

    def _apply_teledyne_runtime(self, *, reason: str, show_dialog: bool) -> tuple[bool, str]:
        self._pull_settings_from_widgets()
        self.teledyne_controller.sync_from_settings(self.settings)
        success, message = self.teledyne_controller.apply_runtime(reason=reason)
        self._append_log(message)
        self._refresh_all_views()
        if not success and show_dialog:
            QtWidgets.QMessageBox.warning(self, "Illumination Runtime", message)
        self.statusBar().showMessage(message, 5000 if success else 8000)
        return success, message

    def _set_safe_illumination_state(self) -> None:
        illumination = self.settings.illumination
        illumination.laser_642_setpoint = illumination.safe_shutdown_setpoint
        illumination.aotf_642_setpoint = 0.0
        illumination.aotf_642_enabled = False
        illumination.channel_642_enabled = False
        illumination.modulation_mode = "Independent mode"
        self.teledyne_controller.sync_from_settings(self.settings)

    def _perform_teledyne_safe_shutdown(
        self,
        *,
        reason: str,
        show_dialog: bool,
        refresh_ui: bool,
    ) -> tuple[bool, str]:
        self._pull_settings_from_widgets()
        success, message = self.teledyne_controller.safe_shutdown_runtime(reason=reason)
        if success:
            self._set_safe_illumination_state()
            if refresh_ui:
                self._load_settings_into_widgets()
        if refresh_ui:
            self._refresh_all_views()
        if message:
            self.statusBar().showMessage(message, 5000 if success else 8000)
        if not success and show_dialog:
            QtWidgets.QMessageBox.warning(self, "Illumination Runtime", message)
        return success, message

    def _append_log(self, message: str) -> None:
        if not message or message == self._last_log_message:
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_output.appendPlainText(f"[{stamp}] {message}")
        self._last_log_message = message

    def _append_whole_cell_round_summary(self, request: MDAAcquisitionRequest, *, state: str) -> None:
        round_plan = tuple(int(value) for value in request.z_round_frames_per_depth)
        depth_count = max(1, int(request.depth_count))
        rounds = max(1, len(round_plan))
        frames_per_depth_total = sum(round_plan) if round_plan else int(request.frame_count)
        total_images = depth_count * frames_per_depth_total
        round_text = ", ".join(str(value) for value in round_plan) if round_plan else str(int(request.frame_count))
        if state == "completed":
            self._append_log(f"Whole-cell acquisition complete: {rounds} rounds finished across {depth_count} z positions.")
        elif state == "interrupted":
            self._append_log(
                f"Whole-cell acquisition stopped before the full round budget completed: planned {rounds} rounds across {depth_count} z positions."
            )
        else:
            self._append_log(f"Whole-cell round plan: {rounds} rounds across {depth_count} z positions.")
        self._append_log(
            f"Whole-cell frames per depth by round: [{round_text}] -> {frames_per_depth_total} frames/depth total."
        )
        self._append_log(
            f"Whole-cell total frame plan: {depth_count} depths x {frames_per_depth_total} frames/depth = {total_images} images."
        )

    def _poll_stage_positions(self) -> None:
        if not self._last_snapshot.running:
            return
        if self._last_snapshot.acquisition_running:
            return
        self.request_poll_stage_positions.emit()

    def _format_stage_summary(self, snapshot: MicroManagerSnapshot) -> str:
        x_text = "-" if snapshot.stage_x_um is None else f"X {snapshot.stage_x_um:.2f}"
        y_text = "-" if snapshot.stage_y_um is None else f"Y {snapshot.stage_y_um:.2f}"
        z_value = self._focuslock_stage_z_um if self._focuslock_stage_z_um is not None else snapshot.stage_z_um
        z_text = "-" if z_value is None else f"Z {z_value:.2f}"
        return f"{x_text} | {y_text} | {z_text}"

    def _format_detailed_stage_summary(self, snapshot: MicroManagerSnapshot) -> str:
        x_text = "-" if snapshot.stage_x_um is None else f"{snapshot.stage_x_um:.3f} um"
        y_text = "-" if snapshot.stage_y_um is None else f"{snapshot.stage_y_um:.3f} um"
        z_value = self._focuslock_stage_z_um if self._focuslock_stage_z_um is not None else snapshot.stage_z_um
        z_text = "-" if z_value is None else f"{z_value:.3f} um"
        xy_device = snapshot.xy_stage_device or "-"
        z_device = snapshot.focus_stage_device or "-"
        return f"{xy_device}: X {x_text}, Y {y_text} | {z_device}: Z {z_text}"

    def _log_preset_guidance(self, preset_name: str) -> None:
        for line in build_preset_guidance_lines(self.settings, preset_name):
            self._append_log(line)

    def _handle_status_message(self, message: str) -> None:
        if message:
            self.mm_status_label.setText(message)
            self.statusBar().showMessage(message)

    def _handle_apply_illumination(self) -> None:
        self._apply_teledyne_runtime(reason="manual illumination apply", show_dialog=True)

    def _handle_safe_shutdown_illumination(self) -> None:
        success, message = self._perform_teledyne_safe_shutdown(
            reason="manual safe shutdown",
            show_dialog=True,
            refresh_ui=True,
        )
        if message:
            self._append_log(message)

    def _handle_start_bleach(self) -> None:
        self._pull_settings_from_widgets()
        if self.bleach_timer.isActive():
            return

        illumination = self.settings.illumination
        bleach = self.settings.bleach
        self._bleach_restore_power_mw = bleach.return_laser_power_mw
        self._bleach_restore_aotf_value = illumination.aotf_642_setpoint
        self._bleach_restore_aotf_enabled = illumination.aotf_642_enabled
        self._bleach_restore_modulation_mode = illumination.modulation_mode

        illumination.channel_642_enabled = True
        illumination.aotf_642_enabled = True
        illumination.laser_642_setpoint = bleach.bleach_laser_power_mw
        illumination.aotf_642_setpoint = bleach.bleach_aotf_value
        illumination.modulation_mode = "Independent mode"
        self.teledyne_controller.sync_from_settings(self.settings)
        self._load_settings_into_widgets()
        success, message = self._apply_teledyne_runtime(reason="bleach start", show_dialog=True)
        if not success:
            return

        self._bleach_remaining_seconds = int(round(bleach.duration_minutes * 60.0))
        self.bleach_timer.start()
        self._update_bleach_status_label()

    def _handle_stop_bleach(self) -> None:
        if self.bleach_timer.isActive():
            self.bleach_timer.stop()
        self._restore_post_bleach_state(reason="bleach stopped")

    def _tick_bleach_timer(self) -> None:
        self._bleach_remaining_seconds = max(0, self._bleach_remaining_seconds - 1)
        self._update_bleach_status_label()
        if self._bleach_remaining_seconds <= 0:
            self.bleach_timer.stop()
            self._restore_post_bleach_state(reason="bleach complete")

    def _update_bleach_status_label(self) -> None:
        if not self.bleach_timer.isActive():
            self.bleach_status_label.setText("Bleach idle")
            return
        minutes, seconds = divmod(self._bleach_remaining_seconds, 60)
        self.bleach_status_label.setText(
            f"Bleaching with 642={self.settings.bleach.bleach_laser_power_mw:.0f}, "
            f"AOTF={self.settings.bleach.bleach_aotf_value:.0f}, remaining {minutes:02d}:{seconds:02d}"
        )

    def _restore_post_bleach_state(self, *, reason: str) -> None:
        illumination = self.settings.illumination
        illumination.channel_642_enabled = True
        illumination.aotf_642_enabled = self._bleach_restore_aotf_enabled
        illumination.laser_642_setpoint = self._bleach_restore_power_mw
        illumination.aotf_642_setpoint = self._bleach_restore_aotf_value
        illumination.modulation_mode = self._bleach_restore_modulation_mode
        self.teledyne_controller.sync_from_settings(self.settings)
        self._load_settings_into_widgets()
        success, message = self._apply_teledyne_runtime(reason=reason, show_dialog=True)
        self._update_bleach_status_label()
        if message:
            self._append_log(message)

    def _handle_open_teledyne_module(self) -> None:
        self._pull_settings_from_widgets()
        success, message = self.teledyne_controller.open_module(self)
        self.teledyne_controller.sync_from_settings(self.settings)
        self._append_log(message)
        self._refresh_all_views()
        if not success:
            QtWidgets.QMessageBox.warning(self, "Teledyne Native Backend", message)
        self.statusBar().showMessage(message, 5000 if success else 8000)

    def _auto_open_teledyne_module(self) -> None:
        success, message = self.teledyne_controller.open_module(self)
        if success:
            self.teledyne_controller.sync_from_settings(self.settings)
        self._refresh_all_views()
        if success:
            self._append_log("Auto-reloaded the native Teledyne XML backend.")
        else:
            self._append_log(f"Automatic native Teledyne XML reload failed: {message}")

    def _handle_close_teledyne_module(self) -> None:
        self._pull_settings_from_widgets()
        self.teledyne_controller.sync_from_settings(self.settings)
        success, message = self.teledyne_controller.close_module()
        self._append_log(message)
        self._refresh_all_views()
        if not success:
            QtWidgets.QMessageBox.warning(self, "Teledyne Native Backend", message)
        self.statusBar().showMessage(message, 5000 if success else 8000)

    def _ensure_focuslock_module_ready(self) -> tuple[bool, str]:
        self._pull_settings_from_widgets()
        success, message = self.focuslock_controller.open_module(self)
        self._refresh_all_views()
        return success, message

    def _handle_open_focuslock_module(self) -> None:
        success, message = self._ensure_focuslock_module_ready()
        self._append_log(message)
        if not success:
            QtWidgets.QMessageBox.warning(self, "Focus Lock", message)
        self.statusBar().showMessage(message, 5000 if success else 8000)

    def _handle_close_focuslock_module(self) -> None:
        success, message = self.focuslock_controller.close_module()
        self._append_log(message)
        self._refresh_all_views()
        self.statusBar().showMessage(message, 5000 if success else 8000)

    def _handle_focuslock_toggle_lock(self) -> None:
        success, message = self._ensure_focuslock_module_ready()
        if not success:
            QtWidgets.QMessageBox.warning(self, "Focus Lock", message)
            return
        success, message = self.focuslock_controller.toggle_lock()
        self._append_log(message)
        self._refresh_all_views()
        self.statusBar().showMessage(message, 5000 if success else 8000)

    def _handle_focuslock_jump_positive(self) -> None:
        success, message = self._ensure_focuslock_module_ready()
        if not success:
            QtWidgets.QMessageBox.warning(self, "Focus Lock", message)
            return
        success, message = self.focuslock_controller.jump_positive()
        self._append_log(message)
        self._refresh_all_views()
        self.statusBar().showMessage(message, 5000 if success else 8000)

    def _handle_focuslock_jump_negative(self) -> None:
        success, message = self._ensure_focuslock_module_ready()
        if not success:
            QtWidgets.QMessageBox.warning(self, "Focus Lock", message)
            return
        success, message = self.focuslock_controller.jump_negative()
        self._append_log(message)
        self._refresh_all_views()
        self.statusBar().showMessage(message, 5000 if success else 8000)

    def _handle_focuslock_toggle_z_scan(self) -> None:
        success, message = self._ensure_focuslock_module_ready()
        if not success:
            QtWidgets.QMessageBox.warning(self, "Focus Lock", message)
            return
        success, message = self.focuslock_controller.toggle_z_scan()
        self._append_log(message)
        self._refresh_all_views()
        self.statusBar().showMessage(message, 5000 if success else 8000)
