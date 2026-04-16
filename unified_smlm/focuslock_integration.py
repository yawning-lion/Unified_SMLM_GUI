from __future__ import annotations

import numpy
import os
from pathlib import Path
import sys
import threading
from typing import Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from .config_store import configure_runtime_environment, get_path, prepare_runtime_support_files
from .models import MDAAcquisitionRequest, UnifiedSettings
from .planning import compute_z_scan_plan, depth_count_from_scan_inputs


VENDOR_ROOT = Path(__file__).resolve().parent / "vendor" / "focuslock_ix83"


class IntegratedFocusLockController(QtCore.QObject):
    preview_ready = QtCore.pyqtSignal(object)
    camera_preview_ready = QtCore.pyqtSignal(object)
    status_ready = QtCore.pyqtSignal(float, float)
    stage_position_ready = QtCore.pyqtSignal(float)
    ui_state_changed = QtCore.pyqtSignal()
    scan_finished = QtCore.pyqtSignal(bool, str)

    def __init__(self, settings: UnifiedSettings) -> None:
        super().__init__()
        self.settings = settings
        self.dialog: Optional[QtWidgets.QDialog] = None
        self.last_error: str | None = None
        self._preview_connected = False
        self._ui_connected = False
        self._syncing_ui = False
        self._scan_active = False
        self._scan_thread: threading.Thread | None = None
        self._scan_stop_requested = threading.Event()
        self._camera_preview_timer = QtCore.QTimer(self)
        self._camera_preview_timer.setInterval(60)
        self._camera_preview_timer.timeout.connect(self._poll_camera_preview)

    def vendor_root(self) -> Path:
        return VENDOR_ROOT

    def is_available(self) -> bool:
        return VENDOR_ROOT.exists()

    def is_open(self) -> bool:
        return self.dialog is not None

    def is_visible(self) -> bool:
        return False

    def has_preview(self) -> bool:
        return bool(self.dialog and hasattr(self.dialog, "lock_display1"))

    def status_text(self) -> str:
        if self.last_error:
            return f"Unavailable: {self.last_error}"
        if not self.dialog:
            return "Not initialized"

        mode_text = self.current_mode_name()
        lock_text = "Locked" if self.is_locked() else "Unlocked"
        scan_text = " | Z Scan running" if self.is_scanning() else ""
        return f"Hidden native runtime | {mode_text} | {lock_text}{scan_text}"

    def current_mode_name(self) -> str:
        if self.dialog is None or not hasattr(self.dialog, "buttons"):
            return "Unknown"
        for button in self.dialog.buttons:
            if button.isChecked():
                return button.text().strip() or "Unknown"
        return "Unknown"

    def is_locked(self) -> bool:
        if self.dialog is None or not hasattr(self.dialog, "lock_display1"):
            return False
        return bool(self.dialog.lock_display1.amLocked())

    def is_scanning(self) -> bool:
        return self._scan_active

    def open_module(self, parent: QtWidgets.QWidget) -> tuple[bool, str]:
        if self.dialog is None:
            try:
                prepare_runtime_support_files()
                self._apply_runtime_env_from_settings(self.settings)
                focuslock_class, parameters = self._load_focuslock_class()
                self.dialog = focuslock_class(False, parameters, parent)
                self._connect_preview_signals()
                self._connect_ui_signals()
                self.dialog.hide()
            except Exception as exc:
                self.dialog = None
                self.last_error = self._format_error(exc)
                return False, self.last_error

        self.sync_from_settings(self.settings)
        self.last_error = None
        if not self._camera_preview_timer.isActive():
            self._camera_preview_timer.start()
        self.ui_state_changed.emit()
        return True, "Integrated focus lock backend initialized inside the unified GUI."

    def close_module(self) -> tuple[bool, str]:
        if self.dialog is None:
            return False, "Integrated focus lock backend is not initialized."
        self.cleanup()
        return True, "Integrated focus lock backend shut down."

    def sync_from_settings(self, settings: UnifiedSettings) -> None:
        self.settings = settings
        if self.dialog is None:
            return

        plan = compute_z_scan_plan(settings)
        focus_settings = settings.focus_lock
        mode_map = {
            "Off": 0,
            "Always On": 1,
            "Lock + Z Scan Calibration": 2,
        }
        target_mode = mode_map.get(focus_settings.mode, 1)

        self._syncing_ui = True
        try:
            self._apply_runtime_env_from_settings(settings)
            params = getattr(self.dialog, "parameters", None)
            if params is not None:
                params.set("focuslock.qpd_zcenter", focus_settings.qpd_zcenter_um)
                params.set("focuslock.qpd_scale", focus_settings.qpd_scale)
                params.set("focuslock.qpd_sum_min", focus_settings.qpd_sum_min)
                params.set("focuslock.qpd_sum_max", focus_settings.qpd_sum_max)
                params.set("focuslock.lock_step", focus_settings.lock_step_um)
                params.set("focuslock.is_locked_buffer_length", focus_settings.is_locked_buffer_length)
                params.set("focuslock.is_locked_offset_thresh", focus_settings.is_locked_offset_thresh)
                params.set("focuslock.qpd_mode", target_mode)
                params.set("focuslock.zscan_start", focus_settings.z_start_um)
                params.set("focuslock.zscan_stop", focus_settings.z_end_um)
                params.set("focuslock.zscan_step", plan.step_um)
                params.set("focuslock.zscan_frames_to_pause", focus_settings.frames_per_depth_per_round)
                self.dialog.newParameters(params)

            button = self.dialog.buttons[target_mode]
            if not button.isChecked():
                button.click()

            self.dialog.ui.jumpSpinBox.setValue(focus_settings.jump_offset_um)
            self.dialog.ui.zScanStartSpinBox.setValue(focus_settings.z_start_um)
            self.dialog.ui.zScanEndSpinBox.setValue(focus_settings.z_end_um)
            self.dialog.ui.zScanStepSpinBox.setValue(plan.step_um)
            self.dialog.ui.zScanFramesSpinBox.setValue(focus_settings.frames_per_depth_per_round)

            if self.dialog.lock_display1.shouldDisplayLockButton():
                current_locked = bool(self.dialog.lock_display1.amLocked())
                if current_locked != focus_settings.locked:
                    self.dialog.handleLockButton(False)
                else:
                    self.dialog.toggleLockButtonText(current_locked)
            self.dialog.toggleLockLabelDisplay(self.dialog.lock_display1.shouldDisplayLockLabel())
            self.dialog.toggleZScanBoxDisplay(self.dialog.lock_display1.shouldDisplayZScanBox())
            self.dialog.toggleZScanLabelDisplay(self.dialog.lock_display1.shouldDisplayZScanLabel())
            self.dialog.toggleZScanButtonText(self.dialog.lock_display1.amScanning())
        finally:
            self._syncing_ui = False

        self.ui_state_changed.emit()

    def sync_to_settings(self, settings: UnifiedSettings) -> None:
        self.settings = settings
        if self.dialog is None:
            return

        focus_settings = settings.focus_lock
        focus_settings.mode = self.current_mode_name()
        focus_settings.locked = self.is_locked()
        focus_settings.jump_offset_um = float(self.dialog.ui.jumpSpinBox.value())
        focus_settings.z_start_um = float(self.dialog.ui.zScanStartSpinBox.value())
        focus_settings.z_end_um = float(self.dialog.ui.zScanEndSpinBox.value())
        focus_settings.frames_per_depth_per_round = max(1, int(round(self.dialog.ui.zScanFramesSpinBox.value())))
        focus_settings.depth_count = depth_count_from_scan_inputs(
            focus_settings.z_start_um,
            focus_settings.z_end_um,
            float(self.dialog.ui.zScanStepSpinBox.value()),
        )

        params = getattr(self.dialog, "parameters", None)
        if params is not None:
            focus_settings.qpd_zcenter_um = float(params.get("focuslock.qpd_zcenter", focus_settings.qpd_zcenter_um))
            focus_settings.qpd_scale = float(params.get("focuslock.qpd_scale", focus_settings.qpd_scale))
            focus_settings.qpd_sum_min = float(params.get("focuslock.qpd_sum_min", focus_settings.qpd_sum_min))
            focus_settings.qpd_sum_max = float(params.get("focuslock.qpd_sum_max", focus_settings.qpd_sum_max))
            focus_settings.lock_step_um = float(params.get("focuslock.lock_step", focus_settings.lock_step_um))
            focus_settings.is_locked_buffer_length = int(
                params.get("focuslock.is_locked_buffer_length", focus_settings.is_locked_buffer_length)
            )
            focus_settings.is_locked_offset_thresh = float(
                params.get("focuslock.is_locked_offset_thresh", focus_settings.is_locked_offset_thresh)
            )

    def toggle_lock(self) -> tuple[bool, str]:
        if self.dialog is None:
            return False, "Initialize the integrated focus lock first."
        self.dialog.handleLockButton(False)
        self._handle_vendor_ui_event()
        return True, "Focus lock locked." if self.is_locked() else "Focus lock unlocked."

    def jump_positive(self) -> tuple[bool, str]:
        if self.dialog is None:
            return False, "Initialize the integrated focus lock first."
        step_um = float(self.dialog.ui.jumpSpinBox.value())
        self.dialog.handleJumpPButton(False)
        self._handle_vendor_ui_event()
        return True, f"Focus lock jumped +{step_um:.3f} um."

    def jump_negative(self) -> tuple[bool, str]:
        if self.dialog is None:
            return False, "Initialize the integrated focus lock first."
        step_um = float(self.dialog.ui.jumpSpinBox.value())
        self.dialog.handleJumpNButton(False)
        self._handle_vendor_ui_event()
        return True, f"Focus lock jumped -{step_um:.3f} um."

    def toggle_z_scan(self) -> tuple[bool, str]:
        if self.dialog is None:
            return False, "Initialize the integrated focus lock first."
        if self._scan_active:
            return self.stop_active_scan()
        focus_settings = self.settings.focus_lock
        return self._start_scan_sequence(
            z_start_um=float(focus_settings.z_start_um),
            z_end_um=float(focus_settings.z_end_um),
            z_step_um=float(compute_z_scan_plan(self.settings).step_um),
            round_frames_per_depth=(int(focus_settings.frames_per_depth_per_round),),
            trigger_exposure_ms=float(self.settings.acquisition.exposure_ms),
            label="Focus lock Z scan",
        )

    def run_coordinated_whole_cell_scan(self, request: MDAAcquisitionRequest) -> tuple[bool, str]:
        if self.dialog is None:
            return False, "Initialize the integrated focus lock first."
        if self._scan_active:
            return False, "Another focus lock scan is already running."
        if not request.coordinated_focus_lock_scan:
            return False, "The acquisition request is not configured for coordinated focus lock scanning."
        if not request.z_round_frames_per_depth:
            return False, "No whole-cell Z scan rounds were planned."
        return self._start_scan_sequence(
            z_start_um=float(request.z_start_um),
            z_end_um=float(request.z_end_um),
            z_step_um=float(request.z_step_um),
            round_frames_per_depth=tuple(int(value) for value in request.z_round_frames_per_depth),
            trigger_exposure_ms=float(request.exposure_ms),
            label=f"Whole-cell Z scan ({len(request.z_round_frames_per_depth)} rounds)",
        )

    def stop_active_scan(self) -> tuple[bool, str]:
        if self.dialog is None:
            return False, "Initialize the integrated focus lock first."
        if not self._scan_active:
            return False, "No focus lock scan is running."
        self._scan_stop_requested.set()
        control_thread = self._control_thread()
        if control_thread is not None:
            control_thread.stopScanning()
        self.ui_state_changed.emit()
        return True, "Focus lock Z scan stop requested."

    def cleanup(self) -> list[str]:
        actions: list[str] = []
        if self.dialog is None:
            return actions

        if self._scan_active:
            stop_success, stop_message = self.stop_active_scan()
            if stop_message:
                actions.append(stop_message)
        join_success, join_message = self._wait_for_scan_thread(timeout_s=5.0)
        if join_message:
            actions.append(join_message)
        self._camera_preview_timer.stop()

        try:
            self.dialog.cleanup()
            actions.append("Cleaned up integrated focus lock module.")
        except Exception as exc:
            actions.append(f"Integrated focus lock cleanup reported an error: {exc}")
        finally:
            self._preview_connected = False
            self._ui_connected = False
            self.dialog = None
            self.ui_state_changed.emit()
        return actions

    def _wait_for_scan_thread(self, timeout_s: float) -> tuple[bool, str]:
        scan_thread = self._scan_thread
        if scan_thread is None:
            return True, ""
        if scan_thread.is_alive():
            scan_thread.join(timeout=max(0.0, float(timeout_s)))
        if scan_thread.is_alive():
            return (
                False,
                f"Integrated focus lock scan thread is still active after {timeout_s:.1f} s; the current DAQ pulse train may still be draining.",
            )
        self._scan_thread = None
        return True, "Integrated focus lock scan thread is idle."

    def _connect_preview_signals(self) -> None:
        if self.dialog is None or self._preview_connected:
            return
        lock_display = getattr(self.dialog, "lock_display1", None)
        if lock_display is None:
            return
        if hasattr(lock_display, "lockDisplay"):
            lock_display.lockDisplay.connect(self._handle_preview_pixmap)
        if hasattr(lock_display, "lockStatus"):
            lock_display.lockStatus.connect(self._handle_lock_status)
        self._preview_connected = True

    def _connect_ui_signals(self) -> None:
        if self.dialog is None or self._ui_connected:
            return

        for button in getattr(self.dialog, "buttons", []):
            button.clicked.connect(self._handle_vendor_ui_event)

        self.dialog.ui.lockButton.clicked.connect(self._handle_vendor_ui_event)
        self.dialog.ui.jumpPButton.clicked.connect(self._handle_vendor_ui_event)
        self.dialog.ui.jumpNButton.clicked.connect(self._handle_vendor_ui_event)
        self.dialog.ui.jumpSpinBox.valueChanged.connect(self._handle_vendor_ui_event)
        self.dialog.ui.zScanButton.clicked.connect(self._handle_vendor_ui_event)
        self.dialog.ui.zScanStartSpinBox.valueChanged.connect(self._handle_vendor_ui_event)
        self.dialog.ui.zScanEndSpinBox.valueChanged.connect(self._handle_vendor_ui_event)
        self.dialog.ui.zScanStepSpinBox.valueChanged.connect(self._handle_vendor_ui_event)
        self.dialog.ui.zScanFramesSpinBox.valueChanged.connect(self._handle_vendor_ui_event)
        if hasattr(self.dialog.lock_display1, "scanningUpdate_2"):
            self.dialog.lock_display1.scanningUpdate_2.connect(self._handle_vendor_ui_event)
        self._ui_connected = True

    def _handle_vendor_ui_event(self, *_args) -> None:
        if self._syncing_ui:
            return
        self.sync_to_settings(self.settings)
        self.ui_state_changed.emit()

    def _handle_preview_pixmap(self, pixmap: object) -> None:
        if isinstance(pixmap, QtGui.QPixmap):
            self.preview_ready.emit(pixmap)

    def _handle_lock_status(self, offset: float, power: float) -> None:
        self.status_ready.emit(float(offset), float(power))
        if self.dialog is None or not hasattr(self.dialog, "lock_display1"):
            return
        try:
            _offset_value, _power_value, stage_z = self.dialog.lock_display1.getOffsetPowerStage()
            self.stage_position_ready.emit(float(stage_z))
        except Exception:
            return

    def _control_thread(self):
        if self.dialog is None or not hasattr(self.dialog, "lock_display1"):
            return None
        return getattr(self.dialog.lock_display1, "control_thread", None)

    def _poll_camera_preview(self) -> None:
        control_thread = self._control_thread()
        if control_thread is None:
            return
        try:
            preview_data = control_thread.getImage()
        except Exception:
            return
        if not isinstance(preview_data, list) or len(preview_data) < 6:
            return
        frame = preview_data[0]
        if not isinstance(frame, numpy.ndarray) or frame.ndim != 2:
            return

        sigma = max(6.0, float(preview_data[5]) if len(preview_data) > 5 else 8.0)
        circles: list[dict[str, object]] = []
        if float(preview_data[1]) != 0.0:
            circles.append(
                {
                    "x": float(preview_data[1]),
                    "y": float(preview_data[2]),
                    "radius": max(12.0, sigma * 2.0),
                    "color": (0, 255, 0),
                }
            )
        if float(preview_data[3]) != 0.0:
            circles.append(
                {
                    "x": float(preview_data[3]),
                    "y": float(preview_data[4]),
                    "radius": max(12.0, sigma * 2.0),
                    "color": (255, 64, 64),
                }
            )

        self.camera_preview_ready.emit(
            {
                "frame": frame.copy(),
                "circles": circles,
            }
        )

    def _start_scan_sequence(
        self,
        *,
        z_start_um: float,
        z_end_um: float,
        z_step_um: float,
        round_frames_per_depth: tuple[int, ...],
        trigger_exposure_ms: float,
        label: str,
    ) -> tuple[bool, str]:
        control_thread = self._control_thread()
        if control_thread is None:
            return False, "The integrated focus lock runtime does not expose a scan control thread."
        if self._scan_active:
            return False, "Another focus lock scan is already running."
        if abs(float(z_step_um)) < 1.0e-9:
            return False, "Z step cannot be 0 for scanning."
        if not round_frames_per_depth:
            return False, "No scan rounds were provided."

        self._scan_stop_requested.clear()
        self._scan_active = True
        self.ui_state_changed.emit()
        self._scan_thread = threading.Thread(
            target=self._run_scan_sequence,
            args=(
                control_thread,
                float(z_start_um),
                float(z_end_um),
                float(z_step_um),
                tuple(max(1, int(value)) for value in round_frames_per_depth),
                float(trigger_exposure_ms),
                label,
            ),
            name="FocusLockScanThread",
            daemon=True,
        )
        self._scan_thread.start()
        return True, f"{label} started."

    def _run_scan_sequence(
        self,
        control_thread,
        z_start_um: float,
        z_end_um: float,
        z_step_um: float,
        round_frames_per_depth: tuple[int, ...],
        trigger_exposure_ms: float,
        label: str,
    ) -> None:
        success = False
        message = ""
        completed_rounds = 0
        try:
            for round_index, frames_per_depth in enumerate(round_frames_per_depth, start=1):
                if self._scan_stop_requested.is_set():
                    break
                completed = bool(
                    control_thread.startScanning(
                        z_start_um,
                        z_end_um,
                        z_step_um,
                        False,
                        int(frames_per_depth),
                        float(trigger_exposure_ms),
                    )
                )
                if not completed:
                    break
                completed_rounds = round_index

            if self._scan_stop_requested.is_set():
                message = f"{label} stopped after {completed_rounds} / {len(round_frames_per_depth)} rounds."
            elif completed_rounds == len(round_frames_per_depth):
                success = True
                message = f"{label} completed: {completed_rounds} rounds finished."
            else:
                message = f"{label} stopped early during round {completed_rounds + 1}."
        except Exception as exc:
            message = f"{label} failed: {exc}"
        finally:
            self._scan_stop_requested.clear()
            self._scan_active = False
            self._scan_thread = None
            self.ui_state_changed.emit()
            self.scan_finished.emit(success, message)

    def _apply_runtime_env_from_settings(self, settings: UnifiedSettings) -> None:
        focus_settings = settings.focus_lock
        os.environ["SMLM_PRIOR_COM"] = str(max(1, int(focus_settings.prior_com_port)))
        configure_runtime_environment()

    def _ensure_vendor_import_path(self) -> None:
        vendor_path = str(VENDOR_ROOT)
        if vendor_path not in sys.path:
            sys.path.insert(0, vendor_path)

    def _load_focuslock_class(self):
        self._ensure_vendor_import_path()

        import sc_library.parameters as params
        from focusLock.IX83FocusLock import AFocusLockZ

        general_parameters = params.halParameters(str(VENDOR_ROOT / "settings_default.xml"))
        setup_name = general_parameters.get("setup_name")
        runtime_xml_path = get_path("focuslock_runtime_xml")
        setup_parameters = params.halParameters(str(runtime_xml_path))
        setup_parameters.set("setup_name", setup_name)
        return AFocusLockZ, setup_parameters

    @staticmethod
    def _format_error(exc: Exception) -> str:
        return (
            "Integrated focus lock failed to start. "
            f"{exc} "
            "Check the focus lock camera, Prior Z stage, uc480 driver, and PriorScientificSDK.dll."
        )
