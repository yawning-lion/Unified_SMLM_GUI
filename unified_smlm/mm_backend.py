from __future__ import annotations

from dataclasses import dataclass
from contextlib import nullcontext
import os
from pathlib import Path
import threading
import tempfile
import time
from typing import Any, Iterable

import numpy
from PyQt5 import QtCore
import tifffile

from .config_store import configure_runtime_environment, get_runtime_value
from .models import (
    CameraPropertySpec,
    ConfigGroupSpec,
    MDAAcquisitionRequest,
    MicroManagerSnapshot,
    RoiRect,
)
from .roi import parse_imagej_roi

try:
    from pycromanager import Acquisition, Core, multi_d_acquisition_events, start_headless, stop_headless
except Exception as exc:  # pragma: no cover - import availability depends on the runtime env
    Acquisition = None
    Core = None
    multi_d_acquisition_events = None
    start_headless = None
    stop_headless = None
    _PYCROMANAGER_IMPORT_ERROR = exc
else:
    _PYCROMANAGER_IMPORT_ERROR = None


@dataclass
class _BackendState:
    running: bool = False
    cfg_path: str = ""
    acquisition_running: bool = False
    last_save_path: str = ""


@dataclass(frozen=True)
class _TriggerActionPlan:
    config_actions: tuple[tuple[str, str], ...]
    property_actions: tuple[tuple[str, str], ...]
    description: str


class MicroManagerWorker(QtCore.QObject):
    snapshot_ready = QtCore.pyqtSignal(object)
    frame_ready = QtCore.pyqtSignal(object)
    properties_ready = QtCore.pyqtSignal(object)
    config_groups_ready = QtCore.pyqtSignal(object)
    external_scan_requested = QtCore.pyqtSignal(object)
    error_raised = QtCore.pyqtSignal(str)
    status_changed = QtCore.pyqtSignal(str)
    acquisition_finished = QtCore.pyqtSignal(bool, str)

    def __init__(self, mm_root: Path, java_path: Path, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._mm_root = Path(mm_root)
        self._java_path = Path(java_path)
        self._core: Any | None = None
        self._state = _BackendState()
        self._poll_timer = QtCore.QTimer(self)
        self._poll_timer.setInterval(70)
        self._poll_timer.timeout.connect(self._poll_sequence)
        self._headless_started = False
        self._active_acquisition: Any | None = None
        self._active_acquisition_lock = threading.Lock()
        self._acquisition_thread: threading.Thread | None = None
        self._acquisition_stop_event = threading.Event()
        self._external_scan_wait_event = threading.Event()
        self._external_scan_result: tuple[bool, str] | None = None
        self._external_trigger_arm_delay_s = float(
            get_runtime_value("external_trigger_arm_delay_seconds", 0.35)
        )

    @QtCore.pyqtSlot(str)
    def load_config(self, cfg_path: str) -> None:
        cfg = Path(cfg_path)
        if not cfg.exists():
            self.error_raised.emit(f"Config file not found: {cfg}")
            return

        self.shutdown()

        try:
            self._prepare_runtime_env()
            self.status_changed.emit("Initializing pycromanager Python backend...")
            start_headless(str(self._mm_root), str(cfg), python_backend=True)
            self._headless_started = True
            self._core = Core()
            self._state = _BackendState(running=True, cfg_path=str(cfg))
            self._emit_full_state("Config loaded.")
        except Exception as exc:
            self._core = None
            self._headless_started = False
            self._state = _BackendState()
            self.error_raised.emit(f"Failed to load Micro-Manager config: {exc}")

    @QtCore.pyqtSlot()
    def start_live(self) -> None:
        if self._core is None:
            self.error_raised.emit("Micro-Manager backend is not loaded.")
            return
        if self._state.acquisition_running:
            self.error_raised.emit("Acquisition is running. Stop it before starting live preview.")
            return
        try:
            self._core.start_continuous_sequence_acquisition(0)
            self._poll_timer.start()
            self._emit_snapshot("Live running.")
        except Exception as exc:
            self.error_raised.emit(f"Failed to start live: {exc}")

    @QtCore.pyqtSlot()
    def stop_live(self) -> None:
        if self._core is None:
            return
        try:
            self._poll_timer.stop()
            if self._core.is_sequence_running():
                self._core.stop_sequence_acquisition()
            self._emit_snapshot("Live stopped.")
        except Exception as exc:
            self.error_raised.emit(f"Failed to stop live: {exc}")

    @QtCore.pyqtSlot(object)
    def run_acquisition(self, request: object) -> None:
        if self._core is None:
            message = "Micro-Manager backend is not loaded."
            self.error_raised.emit(message)
            self.acquisition_finished.emit(False, message)
            return
        if not isinstance(request, MDAAcquisitionRequest):
            message = f"Invalid acquisition request: {type(request).__name__}"
            self.error_raised.emit(message)
            self.acquisition_finished.emit(False, message)
            return
        if request.frame_count <= 0 or request.expected_image_count <= 0:
            message = "Acquisition frame count must be positive."
            self.error_raised.emit(message)
            self.acquisition_finished.emit(False, message)
            return
        if request.coordinated_focus_lock_scan:
            if request.trigger_mode.strip().lower() != "external":
                message = "Whole-cell coordinated scan requires External trigger mode."
                self.error_raised.emit(message)
                self.acquisition_finished.emit(False, message)
                return
            if not request.z_round_frames_per_depth:
                message = "Whole-cell coordinated scan requires at least one planned scan round."
                self.error_raised.emit(message)
                self.acquisition_finished.emit(False, message)
                return
            planned_frames_per_depth = sum(int(value) for value in request.z_round_frames_per_depth)
            if planned_frames_per_depth != int(request.frame_count):
                message = (
                    "Whole-cell coordinated scan frame planning mismatch: "
                    f"per-depth target {request.frame_count}, planned {planned_frames_per_depth}."
                )
                self.error_raised.emit(message)
                self.acquisition_finished.emit(False, message)
                return
            planned_images = sum(int(value) for value in request.z_round_frames_per_depth) * max(1, int(request.depth_count))
            if planned_images != int(request.expected_image_count):
                message = (
                    "Whole-cell coordinated scan image planning mismatch: "
                    f"expected {request.expected_image_count}, planned {planned_images}."
                )
                self.error_raised.emit(message)
                self.acquisition_finished.emit(False, message)
                return
        if self._state.acquisition_running:
            message = "Another acquisition is already running."
            self.error_raised.emit(message)
            self.acquisition_finished.emit(False, message)
            return

        save_dir = Path(request.save_dir).expanduser()
        save_dir.mkdir(parents=True, exist_ok=True)

        try:
            self._poll_timer.stop()
            if self._core.is_sequence_running():
                self._core.stop_sequence_acquisition()
        except Exception:
            pass

        self._acquisition_stop_event.clear()
        self._state.acquisition_running = True
        self._emit_snapshot(
            f"Starting MDA acquisition: {request.preset_name} ({request.expected_image_count} images planned)"
        )
        self._acquisition_thread = threading.Thread(
            target=self._execute_acquisition,
            args=(request,),
            name="MicroManagerMDAThread",
            daemon=True,
        )
        self._acquisition_thread.start()

    @QtCore.pyqtSlot()
    def stop_acquisition(self) -> None:
        self._acquisition_stop_event.set()
        self._external_scan_result = (False, "Acquisition stop requested.")
        self._external_scan_wait_event.set()
        with self._active_acquisition_lock:
            active_acquisition = self._active_acquisition
        if active_acquisition is not None:
            try:
                active_acquisition.abort()
            except Exception as exc:
                self.error_raised.emit(f"Failed to abort acquisition cleanly: {exc}")

    @QtCore.pyqtSlot(bool, str)
    def resolve_external_scan(self, success: bool, message: str) -> None:
        self._external_scan_result = (bool(success), str(message))
        self._external_scan_wait_event.set()

    @QtCore.pyqtSlot(float)
    def set_exposure(self, exposure_ms: float) -> None:
        if self._core is None:
            return
        try:
            self._core.set_exposure(float(exposure_ms))
            self._emit_snapshot("Exposure updated.")
        except Exception as exc:
            self.error_raised.emit(f"Failed to set exposure: {exc}")

    @QtCore.pyqtSlot(str, str)
    def set_property(self, name: str, value: str) -> None:
        if self._core is None:
            return
        try:
            camera = self._core.get_camera_device()
            self._core.set_property(camera, name, value)
            self._emit_full_state(f"Property {name} updated.")
        except Exception as exc:
            self.error_raised.emit(f"Failed to set property {name}: {exc}")

    @QtCore.pyqtSlot(str, str)
    def set_config_group(self, group_name: str, preset_name: str) -> None:
        if self._core is None:
            return
        try:
            self._core.set_config(group_name, preset_name)
            self._core.wait_for_config(group_name, preset_name)
            self._emit_full_state(f"Config group {group_name} updated.")
        except Exception as exc:
            self.error_raised.emit(f"Failed to set config group {group_name}: {exc}")

    @QtCore.pyqtSlot(str)
    def apply_trigger_mode(self, trigger_mode: str) -> None:
        if self._core is None:
            return
        if self._state.acquisition_running:
            self.error_raised.emit("Cannot change trigger mode while an acquisition is running.")
            return
        try:
            plan = self._build_trigger_action_plan(trigger_mode)
            camera = str(self._core.get_camera_device() or "")
            for group_name, preset_name in plan.config_actions:
                self._core.set_config(group_name, preset_name)
                self._core.wait_for_config(group_name, preset_name)
            for property_name, value in plan.property_actions:
                self._core.set_property(camera, property_name, value)
            readback = self._build_trigger_readback_summary(camera)
            self._emit_full_state(
                f"Trigger mode {trigger_mode} applied via {plan.description}. Readback: {readback}"
            )
        except Exception as exc:
            self.error_raised.emit(f"Failed to apply trigger mode {trigger_mode}: {exc}")

    @QtCore.pyqtSlot(str)
    def apply_roi_file(self, roi_path: str) -> None:
        if self._core is None:
            return
        try:
            roi = parse_imagej_roi(roi_path)
            if roi.kind != "rectangle":
                raise ValueError(f"ROI kind {roi.kind} cannot be applied to camera ROI")
            self._core.set_roi(int(roi.x), int(roi.y), int(roi.width), int(roi.height))
            self._emit_snapshot(f"ROI applied from {Path(roi_path).name}.")
        except Exception as exc:
            self.error_raised.emit(f"Failed to apply ROI: {exc}")

    @QtCore.pyqtSlot()
    def clear_roi(self) -> None:
        if self._core is None:
            return
        try:
            self._core.clear_roi()
            self._emit_snapshot("ROI cleared.")
        except Exception as exc:
            self.error_raised.emit(f"Failed to clear ROI: {exc}")

    @QtCore.pyqtSlot()
    def snap(self) -> None:
        if self._core is None:
            return
        try:
            self._core.snap_image()
            image = numpy.asarray(self._core.get_image())
            self.frame_ready.emit(image.copy())
            self._emit_snapshot("Snap acquired.")
        except Exception as exc:
            self.error_raised.emit(f"Failed to snap image: {exc}")

    @QtCore.pyqtSlot()
    def refresh(self) -> None:
        if self._core is None:
            self.snapshot_ready.emit(MicroManagerSnapshot(status_message="Backend idle."))
            self.properties_ready.emit([])
            self.config_groups_ready.emit([])
            return
        self._emit_full_state("State refreshed.")

    @QtCore.pyqtSlot()
    def poll_stage_positions(self) -> None:
        if self._core is None:
            return
        self.snapshot_ready.emit(self._build_snapshot(self._default_status_message()))

    @QtCore.pyqtSlot()
    def shutdown(self) -> None:
        self._poll_timer.stop()
        self._acquisition_stop_event.set()
        self._external_scan_result = None
        self._external_scan_wait_event.set()
        self.stop_acquisition()

        acquisition_thread = self._acquisition_thread
        if acquisition_thread is not None and acquisition_thread.is_alive():
            acquisition_thread.join(timeout=5.0)
        self._acquisition_thread = None

        if self._core is not None:
            try:
                if self._core.is_sequence_running():
                    self._core.stop_sequence_acquisition()
            except Exception:
                pass
            try:
                self._core.unload_all_devices()
            except Exception:
                pass

        self._core = None
        if self._headless_started:
            try:
                stop_headless()
            except Exception:
                pass
        self._headless_started = False
        time.sleep(0.15)
        self._state = _BackendState()
        self._external_scan_result = None
        self._external_scan_wait_event.clear()
        self.snapshot_ready.emit(MicroManagerSnapshot())
        self.properties_ready.emit([])
        self.config_groups_ready.emit([])

    def _execute_acquisition(self, request: MDAAcquisitionRequest) -> None:
        frame_counter = 0
        dataset = None
        actual_dataset_path: Path | None = None
        normalized_format = request.saving_format.strip().lower()
        streaming_separate_images = normalized_format == "separate image files"
        use_temporary_dataset = normalized_format == "image stack file" and request.dataset_path is None
        output_path = Path(request.output_path)
        if streaming_separate_images:
            self._prepare_streaming_output_dir(output_path)

        def image_process_fn(image, metadata):
            nonlocal frame_counter
            image_array = numpy.asarray(image)
            frame_counter += 1
            if streaming_separate_images:
                axes = self._axes_from_metadata(metadata, frame_counter - 1)
                tifffile.imwrite(str(output_path / self._separate_image_name(request.base_name, axes)), image_array)
            self.frame_ready.emit(image_array.copy())
            if (
                frame_counter == 1
                or frame_counter == request.expected_image_count
                or frame_counter % 50 == 0
            ):
                self.status_changed.emit(
                    f"MDA acquiring {frame_counter} / {request.expected_image_count} images..."
                )
            if streaming_separate_images:
                return None
            return image, metadata

        try:
            temporary_dataset_context = (
                tempfile.TemporaryDirectory(prefix="unified_stack_export_")
                if use_temporary_dataset
                else nullcontext(None)
            )
            with temporary_dataset_context as temporary_dataset_dir:
                acquisition_directory = None if streaming_separate_images else str(Path(request.save_dir).expanduser())
                acquisition_name = request.dataset_name or request.base_name
                if use_temporary_dataset:
                    acquisition_directory = str(temporary_dataset_dir)
                    acquisition_name = "mda_export"

                with Acquisition(
                    directory=acquisition_directory,
                    name=acquisition_name,
                    image_process_fn=image_process_fn,
                    show_display=False,
                ) as acquisition:
                    with self._active_acquisition_lock:
                        self._active_acquisition = acquisition
                    acquisition.acquire(self._build_event_generator(request))
                    if request.coordinated_focus_lock_scan:
                        self._await_external_scan_sequence(request, acquisition)
                    if not streaming_separate_images:
                        dataset = acquisition.get_dataset()

            with self._active_acquisition_lock:
                self._active_acquisition = None
            final_primary_path = output_path if streaming_separate_images else None
            final_dataset_path: Path | None = None
            if not streaming_separate_images and dataset is None:
                raise RuntimeError("The MDA acquisition completed without a dataset handle.")
            if streaming_separate_images:
                if frame_counter <= 0 and not self._acquisition_stop_event.is_set():
                    raise RuntimeError("The streaming TIFF acquisition completed without writing any frames.")
            else:
                actual_dataset_path = Path(str(dataset.path))
                final_primary_path, final_dataset_path = self._finalize_mda_output(
                    request=request,
                    dataset=dataset,
                    actual_dataset_path=actual_dataset_path,
                )
                dataset = None

            self._state.last_save_path = str(final_primary_path)
            if self._acquisition_stop_event.is_set():
                message = self._format_acquisition_result_message(
                    f"MDA acquisition stopped after {frame_counter} images.",
                    final_primary_path,
                    final_dataset_path,
                )
                self._emit_snapshot(message)
                self.acquisition_finished.emit(False, message)
            else:
                message = self._format_acquisition_result_message(
                    f"MDA acquisition complete: {frame_counter} images.",
                    final_primary_path,
                    final_dataset_path,
                )
                self._emit_snapshot(message)
                self.acquisition_finished.emit(True, message)
        except Exception as exc:
            with self._active_acquisition_lock:
                self._active_acquisition = None
            if dataset is not None:
                try:
                    dataset.close()
                except Exception:
                    pass
            if self._acquisition_stop_event.is_set():
                message = f"MDA acquisition stopped with backend cleanup error: {exc}"
                self.error_raised.emit(message)
                self.acquisition_finished.emit(False, message)
            else:
                message = f"MDA acquisition failed: {exc}"
                self.error_raised.emit(message)
                self.acquisition_finished.emit(False, message)
        finally:
            self._state.acquisition_running = False
            self._acquisition_stop_event.clear()
            self._external_scan_result = None
            self._external_scan_wait_event.clear()
            self._emit_snapshot("Config loaded." if self._state.running else "Backend idle.")

    def _build_event_generator(self, request: MDAAcquisitionRequest):
        if request.coordinated_focus_lock_scan:
            return self._iter_focus_lock_external_z_events(request)
        if request.preset_name == "Whole-Cell Z Scan" and request.depth_count > 1:
            if self._has_mm_focus_stage():
                return self._iter_mm_z_events(request)
            self.status_changed.emit(
                "No Micro-Manager focus stage is configured in the loaded cfg. "
                "Whole-cell Z acquisition will use MDA z-axis labels only and will not command Z motion."
            )
            return self._iter_external_z_label_events(request)
        return self._iter_time_events(request)

    def _iter_time_events(self, request: MDAAcquisitionRequest):
        offset = 0
        chunk_size = 1000
        while offset < request.frame_count:
            chunk = min(chunk_size, request.frame_count - offset)
            for event in multi_d_acquisition_events(num_time_points=chunk, time_interval_s=0):
                axes = dict(event.get("axes", {}))
                axes["time"] = int(axes.get("time", 0)) + offset
                yield {
                    "axes": axes,
                    "exposure": float(request.exposure_ms),
                }
            offset += chunk

    def _iter_mm_z_events(self, request: MDAAcquisitionRequest):
        offset = 0
        chunk_size = 250
        while offset < request.frame_count:
            chunk = min(chunk_size, request.frame_count - offset)
            for event in multi_d_acquisition_events(
                num_time_points=chunk,
                time_interval_s=0,
                z_start=float(request.z_start_um),
                z_end=float(request.z_end_um),
                z_step=float(request.z_step_um),
                order="tz",
            ):
                axes = dict(event.get("axes", {}))
                axes["time"] = int(axes.get("time", 0)) + offset
                updated_event = dict(event)
                updated_event["axes"] = axes
                updated_event["exposure"] = float(request.exposure_ms)
                yield updated_event
            offset += chunk

    def _iter_external_z_label_events(self, request: MDAAcquisitionRequest):
        offset = 0
        chunk_size = 250
        while offset < request.frame_count:
            chunk = min(chunk_size, request.frame_count - offset)
            for event in multi_d_acquisition_events(num_time_points=chunk, time_interval_s=0):
                base_time = int(event.get("axes", {}).get("time", 0)) + offset
                for z_index in range(max(1, int(request.depth_count))):
                    yield {
                        "axes": {
                            "time": base_time,
                            "z": z_index,
                        },
                        "exposure": float(request.exposure_ms),
                    }
            offset += chunk

    def _iter_focus_lock_external_z_events(self, request: MDAAcquisitionRequest):
        time_offset = 0
        depth_count = max(1, int(request.depth_count))
        for frames_per_depth in request.z_round_frames_per_depth:
            round_frames = max(1, int(frames_per_depth))
            for z_index in range(depth_count):
                for local_time in range(round_frames):
                    yield {
                        "axes": {
                            "time": time_offset + local_time,
                            "z": z_index,
                        },
                        "exposure": float(request.exposure_ms),
                    }
            time_offset += round_frames

    def _await_external_scan_sequence(self, request: MDAAcquisitionRequest, acquisition) -> None:
        self._external_scan_result = None
        self._external_scan_wait_event.clear()
        self.status_changed.emit(
            "MDA armed for external trigger. Waiting for the integrated focus lock to drive Z motion and trigger pulses..."
        )
        if self._external_trigger_arm_delay_s > 0:
            arm_delay_ms = int(round(self._external_trigger_arm_delay_s * 1000.0))
            self.status_changed.emit(
                f"External-trigger MDA queued. Holding {arm_delay_ms} ms so the camera can finish arming before the focus lock emits DAQ pulses..."
            )
            time.sleep(self._external_trigger_arm_delay_s)
        self.external_scan_requested.emit(request)

        while not self._external_scan_wait_event.wait(timeout=0.1):
            if self._acquisition_stop_event.is_set():
                try:
                    acquisition.abort()
                except Exception:
                    pass
                raise RuntimeError("Acquisition stopped while waiting for the coordinated whole-cell Z scan.")

        success, message = self._external_scan_result or (False, "The coordinated whole-cell Z scan did not report a result.")
        self._external_scan_result = None
        self._external_scan_wait_event.clear()
        if not success:
            try:
                acquisition.abort()
            except Exception:
                pass
            raise RuntimeError(message)
        waiting_text = (
            "Waiting for the external-trigger image stream to finish writing."
            if request.saving_format.strip().lower() == "separate image files"
            else "Waiting for the external-trigger MDA dataset to finish writing."
        )
        self.status_changed.emit(f"{message} {waiting_text}")

    def _finalize_mda_output(
        self,
        *,
        request: MDAAcquisitionRequest,
        dataset,
        actual_dataset_path: Path,
    ) -> tuple[Path, Path | None]:
        output_path = Path(request.output_path)
        target_dataset_path = Path(request.dataset_path) if request.dataset_path else None
        normalized_format = request.saving_format.strip().lower()

        if normalized_format == "image stack file":
            output_path.parent.mkdir(parents=True, exist_ok=True)
            self._export_dataset_to_stack(dataset, output_path)

        dataset.close()
        renamed_dataset_path = None
        if target_dataset_path is not None:
            renamed_dataset_path = self._rename_dataset_path(actual_dataset_path, target_dataset_path)
        elif normalized_format != "image stack file":
            renamed_dataset_path = actual_dataset_path

        if normalized_format == "image stack file":
            return output_path, renamed_dataset_path
        if renamed_dataset_path is None:
            raise RuntimeError("The completed MDA dataset path is unavailable.")
        return renamed_dataset_path, renamed_dataset_path

    def _export_dataset_to_stack(self, dataset, output_path: Path) -> None:
        with tifffile.TiffWriter(str(output_path), bigtiff=True) as writer:
            wrote_anything = False
            for axes in self._iter_dataset_axes(dataset):
                writer.write(numpy.asarray(dataset.read_image(**axes)))
                wrote_anything = True
        if not wrote_anything:
            raise RuntimeError("The completed MDA dataset does not contain any images to export.")

    def _separate_image_name(self, base_name: str, axes: dict[str, Any]) -> str:
        parts = [base_name]
        if "position" in axes:
            parts.append(f"p{int(axes['position']):03d}")
        if "channel" in axes:
            channel_value = axes["channel"]
            if isinstance(channel_value, (int, numpy.integer)):
                parts.append(f"c{int(channel_value):03d}")
            else:
                normalized = "".join(char if str(char).isalnum() else "_" for char in str(channel_value)).strip("_")
                parts.append(f"c_{normalized or 'channel'}")
        if "time" in axes:
            parts.append(f"t{int(axes['time']):06d}")
        if "z" in axes:
            parts.append(f"z{int(axes['z']):03d}")
        for axis_name in sorted(axes):
            if axis_name in {"position", "channel", "time", "z"}:
                continue
            axis_value = axes[axis_name]
            normalized_name = "".join(char for char in str(axis_name).lower() if char.isalnum()) or "axis"
            normalized_value = "".join(char if str(char).isalnum() else "_" for char in str(axis_value)).strip("_")
            parts.append(f"{normalized_name}_{normalized_value or 'value'}")
        return "_".join(parts) + ".tif"

    def _iter_dataset_axes(self, dataset) -> Iterable[dict[str, Any]]:
        axes_map = getattr(dataset, "axes", {}) or {}
        preferred_order = ["position", "channel", "time", "z"]
        ordered_axes = [axis_name for axis_name in preferred_order if axis_name in axes_map]
        ordered_axes.extend(
            axis_name for axis_name in sorted(axes_map) if axis_name not in ordered_axes
        )

        if not ordered_axes:
            yield {}
            return

        def walk(index: int, current_axes: dict[str, Any]):
            if index >= len(ordered_axes):
                if dataset.has_image(**current_axes):
                    yield dict(current_axes)
                return
            axis_name = ordered_axes[index]
            for axis_value in list(axes_map[axis_name]):
                current_axes[axis_name] = axis_value
                yield from walk(index + 1, current_axes)
            current_axes.pop(axis_name, None)

        yield from walk(0, {})

    def _prepare_streaming_output_dir(self, output_dir: Path) -> None:
        if output_dir.exists():
            if not output_dir.is_dir():
                raise RuntimeError(f"Streaming TIFF output path is not a directory: {output_dir}")
            if any(output_dir.iterdir()):
                raise RuntimeError(f"Streaming TIFF output directory already exists and is not empty: {output_dir}")
            return
        output_dir.mkdir(parents=True, exist_ok=False)

    def _axes_from_metadata(self, metadata: Any, fallback_time_index: int) -> dict[str, Any]:
        axes: dict[str, Any] = {}
        if isinstance(metadata, dict):
            metadata_axes = metadata.get("Axes")
            if isinstance(metadata_axes, dict):
                axes = dict(metadata_axes)
        if not axes:
            axes["time"] = int(fallback_time_index)
        return axes

    def _format_acquisition_result_message(
        self,
        prefix: str,
        primary_output_path: Path,
        dataset_path: Path | None,
    ) -> str:
        message = f"{prefix} Primary output: {primary_output_path}"
        if dataset_path is not None:
            message += f" | Dataset: {dataset_path}"
        return message

    def _rename_dataset_path(self, actual_path: Path, target_path: Path) -> Path:
        actual_resolved = str(actual_path.resolve())
        target_resolved = str(target_path.resolve())
        if actual_resolved == target_resolved:
            return target_path

        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists():
            raise RuntimeError(f"Target dataset path already exists: {target_path}")
        actual_path.rename(target_path)
        return target_path

    def _has_mm_focus_stage(self) -> bool:
        if self._core is None:
            return False
        try:
            return bool(str(self._core.get_focus_device() or "").strip())
        except Exception:
            return False

    def _build_trigger_action_plan(self, trigger_mode: str) -> _TriggerActionPlan:
        is_external = trigger_mode.strip().lower().startswith("external")
        group_specs = self._collect_config_groups()
        property_specs = self._collect_property_specs()

        config_actions: list[tuple[str, str]] = []
        property_actions: list[tuple[str, str]] = []
        description_parts: list[str] = []

        scmos_group = self._find_group_spec(group_specs, "scmos_preset")
        if scmos_group is not None:
            preset = self._match_value(
                scmos_group.presets,
                ["external_level", "external level", "external", "level"] if is_external else ["internal"],
            )
            if preset:
                config_actions.append((scmos_group.name, preset))
                description_parts.append(f"{scmos_group.name}={preset}")

        output_trigger_group = self._find_group_spec(group_specs, "output_trigger_1", "output trigger 1")
        if output_trigger_group is not None:
            preset = self._match_value(output_trigger_group.presets, ["exposure"])
            if preset:
                config_actions.append((output_trigger_group.name, preset))
                description_parts.append(f"{output_trigger_group.name}={preset}")

        output_trigger_source_group = self._find_group_spec(
            group_specs,
            "output_trigger_1_source",
            "output trigger 1 source",
        )
        if output_trigger_source_group is not None:
            preset = self._match_value(output_trigger_source_group.presets, ["readout end"])
            if preset:
                config_actions.append((output_trigger_source_group.name, preset))
                description_parts.append(f"{output_trigger_source_group.name}={preset}")

        output_trigger_polarity_group = self._find_group_spec(
            group_specs,
            "output_trigger_1_polarity",
            "output trigger 1 polarity",
        )
        if output_trigger_polarity_group is not None:
            preset = self._match_value(output_trigger_polarity_group.presets, ["positive"])
            if preset:
                config_actions.append((output_trigger_polarity_group.name, preset))
                description_parts.append(f"{output_trigger_polarity_group.name}={preset}")

        output_trigger_group_2 = self._find_group_spec(group_specs, "output_trigger_2", "output trigger 2")
        if output_trigger_group_2 is not None:
            preset = self._match_value(output_trigger_group_2.presets, ["exposure"])
            if preset:
                config_actions.append((output_trigger_group_2.name, preset))
                description_parts.append(f"{output_trigger_group_2.name}={preset}")

        output_trigger_source_group_2 = self._find_group_spec(
            group_specs,
            "output_trigger_2_source",
            "output trigger 2 source",
        )
        if output_trigger_source_group_2 is not None:
            preset = self._match_value(output_trigger_source_group_2.presets, ["readout end"])
            if preset:
                config_actions.append((output_trigger_source_group_2.name, preset))
                description_parts.append(f"{output_trigger_source_group_2.name}={preset}")

        output_trigger_polarity_group_2 = self._find_group_spec(
            group_specs,
            "output_trigger_2_polarity",
            "output trigger 2 polarity",
        )
        if output_trigger_polarity_group_2 is not None:
            preset = self._match_value(output_trigger_polarity_group_2.presets, ["positive"])
            if preset:
                config_actions.append((output_trigger_polarity_group_2.name, preset))
                description_parts.append(f"{output_trigger_polarity_group_2.name}={preset}")

        trigger_source_group = self._find_group_spec(group_specs, "trigger_source", "trigger source")
        if trigger_source_group is not None:
            preset = self._match_value(
                trigger_source_group.presets,
                ["external"] if is_external else ["internal", "software"],
            )
            if preset:
                config_actions.append((trigger_source_group.name, preset))
                description_parts.append(f"{trigger_source_group.name}={preset}")

        trigger_kind_group = self._find_group_spec(group_specs, "ext_trigger_kind", "trigger_active")
        if trigger_kind_group is not None:
            preset = self._match_value(
                trigger_kind_group.presets,
                ["level", "syncreadout", "edge"] if is_external else ["edge", "normal"],
            )
            if preset:
                config_actions.append((trigger_kind_group.name, preset))
                description_parts.append(f"{trigger_kind_group.name}={preset}")

        trigger_source_property = self._find_property_spec(
            property_specs,
            "trigger source",
            "triggersource",
        )
        if trigger_source_property is not None and trigger_source_group is None:
            value = self._match_value(
                trigger_source_property.allowed_values or [trigger_source_property.value],
                ["external"] if is_external else ["internal", "software"],
            )
            if value:
                property_actions.append((trigger_source_property.name, value))
                description_parts.append(f"{trigger_source_property.name}={value}")

        trigger_active_property = self._find_property_spec(
            property_specs,
            "trigger active",
            "triggeractive",
        )
        if trigger_active_property is not None and trigger_kind_group is None:
            value = self._match_value(
                trigger_active_property.allowed_values or [trigger_active_property.value],
                ["level", "syncreadout", "edge"] if is_external else ["edge", "normal"],
            )
            if value:
                property_actions.append((trigger_active_property.name, value))
                description_parts.append(f"{trigger_active_property.name}={value}")

        output_trigger_property = self._find_property_spec(
            property_specs,
            "output trigger kind 0",
            "output trigger kind[0]",
        )
        if output_trigger_property is not None and output_trigger_group is None:
            value = self._match_value(
                output_trigger_property.allowed_values or [output_trigger_property.value],
                ["exposure"],
            )
            if value:
                property_actions.append((output_trigger_property.name, value))
                description_parts.append(f"{output_trigger_property.name}={value}")

        output_trigger_source_property = self._find_property_spec(
            property_specs,
            "output trigger source 0",
            "output trigger source[0]",
        )
        if output_trigger_source_property is not None and output_trigger_source_group is None:
            value = self._match_value(
                output_trigger_source_property.allowed_values or [output_trigger_source_property.value],
                ["readout end"],
            )
            if value:
                property_actions.append((output_trigger_source_property.name, value))
                description_parts.append(f"{output_trigger_source_property.name}={value}")

        output_trigger_polarity_property = self._find_property_spec(
            property_specs,
            "output trigger polarity 0",
            "output trigger polarity[0]",
        )
        if output_trigger_polarity_property is not None and output_trigger_polarity_group is None:
            value = self._match_value(
                output_trigger_polarity_property.allowed_values or [output_trigger_polarity_property.value],
                ["positive"],
            )
            if value:
                property_actions.append((output_trigger_polarity_property.name, value))
                description_parts.append(f"{output_trigger_polarity_property.name}={value}")

        output_trigger_property_2 = self._find_property_spec(
            property_specs,
            "output trigger kind 1",
            "output trigger kind[1]",
        )
        if output_trigger_property_2 is not None and output_trigger_group_2 is None:
            value = self._match_value(
                output_trigger_property_2.allowed_values or [output_trigger_property_2.value],
                ["exposure"],
            )
            if value:
                property_actions.append((output_trigger_property_2.name, value))
                description_parts.append(f"{output_trigger_property_2.name}={value}")

        output_trigger_source_property_2 = self._find_property_spec(
            property_specs,
            "output trigger source 1",
            "output trigger source[1]",
        )
        if output_trigger_source_property_2 is not None and output_trigger_source_group_2 is None:
            value = self._match_value(
                output_trigger_source_property_2.allowed_values or [output_trigger_source_property_2.value],
                ["readout end"],
            )
            if value:
                property_actions.append((output_trigger_source_property_2.name, value))
                description_parts.append(f"{output_trigger_source_property_2.name}={value}")

        output_trigger_polarity_property_2 = self._find_property_spec(
            property_specs,
            "output trigger polarity 1",
            "output trigger polarity[1]",
        )
        if output_trigger_polarity_property_2 is not None and output_trigger_polarity_group_2 is None:
            value = self._match_value(
                output_trigger_polarity_property_2.allowed_values or [output_trigger_polarity_property_2.value],
                ["positive"],
            )
            if value:
                property_actions.append((output_trigger_polarity_property_2.name, value))
                description_parts.append(f"{output_trigger_polarity_property_2.name}={value}")

        if not config_actions and not property_actions:
            available_groups = ", ".join(group.name for group in group_specs) or "none"
            available_properties = ", ".join(spec.name for spec in property_specs) or "none"
            raise RuntimeError(
                "No compatible trigger config group or property was found. "
                f"Available groups: {available_groups}. Available camera properties: {available_properties}."
            )

        return _TriggerActionPlan(
            config_actions=tuple(config_actions),
            property_actions=tuple(property_actions),
            description=", ".join(description_parts),
        )

    def _find_group_spec(self, specs: list[ConfigGroupSpec], *candidates: str) -> ConfigGroupSpec | None:
        normalized_candidates = {self._normalized_key(value) for value in candidates}
        for spec in specs:
            normalized_name = self._normalized_key(spec.name)
            if normalized_name in normalized_candidates:
                return spec
        for spec in specs:
            normalized_name = self._normalized_key(spec.name)
            if any(candidate in normalized_name for candidate in normalized_candidates):
                return spec
        return None

    def _find_property_spec(
        self,
        specs: list[CameraPropertySpec],
        *candidates: str,
    ) -> CameraPropertySpec | None:
        normalized_candidates = {self._normalized_key(value) for value in candidates}
        for spec in specs:
            normalized_name = self._normalized_key(spec.name)
            if normalized_name in normalized_candidates:
                return spec
        for spec in specs:
            normalized_name = self._normalized_key(spec.name)
            if any(candidate in normalized_name for candidate in normalized_candidates):
                return spec
        return None

    def _match_value(self, values: Iterable[str], preferred: Iterable[str]) -> str:
        normalized_values = {self._normalized_key(value): str(value) for value in values}
        for candidate in preferred:
            normalized_candidate = self._normalized_key(candidate)
            if normalized_candidate in normalized_values:
                return normalized_values[normalized_candidate]
        for candidate in preferred:
            normalized_candidate = self._normalized_key(candidate)
            for normalized_value, raw_value in normalized_values.items():
                if normalized_candidate and normalized_candidate in normalized_value:
                    return raw_value
        return ""

    @staticmethod
    def _normalized_key(value: str) -> str:
        return "".join(character for character in str(value).lower() if character.isalnum())

    def _build_trigger_readback_summary(self, camera: str) -> str:
        if self._core is None or not camera:
            return "no camera"
        property_names = [
            "TRIGGER SOURCE",
            "TRIGGER ACTIVE",
            "TriggerPolarity",
            "OUTPUT TRIGGER KIND[0]",
            "OUTPUT TRIGGER SOURCE[0]",
            "OUTPUT TRIGGER POLARITY[0]",
            "OUTPUT TRIGGER KIND[1]",
            "OUTPUT TRIGGER SOURCE[1]",
            "OUTPUT TRIGGER POLARITY[1]",
        ]
        parts: list[str] = []
        for property_name in property_names:
            try:
                if self._core.has_property(camera, property_name):
                    parts.append(f"{property_name}={self._core.get_property(camera, property_name)}")
            except Exception:
                continue
        return ", ".join(parts) if parts else "no readable trigger properties"

    def _poll_sequence(self) -> None:
        if self._core is None:
            return
        try:
            latest: numpy.ndarray | None = None
            while self._core.get_remaining_image_count() > 0:
                latest = numpy.asarray(self._core.pop_next_tagged_image().pix)
            if latest is not None:
                self.frame_ready.emit(latest.copy())
                self._emit_snapshot("Live running.")
        except Exception as exc:
            self._poll_timer.stop()
            self.error_raised.emit(f"Live polling failed: {exc}")

    def _emit_full_state(self, message: str) -> None:
        self._emit_snapshot(message)
        self.properties_ready.emit(self._collect_property_specs())
        self.config_groups_ready.emit(self._collect_config_groups())

    def _emit_snapshot(self, message: str) -> None:
        self.snapshot_ready.emit(self._build_snapshot(message))
        self.status_changed.emit(message)

    def _build_snapshot(self, message: str) -> MicroManagerSnapshot:
        if self._core is None:
            return MicroManagerSnapshot(status_message=message)

        roi_rect = self._core.get_roi()
        roi = RoiRect(
            kind="rectangle",
            x=int(roi_rect[0]),
            y=int(roi_rect[1]),
            width=int(roi_rect[2]),
            height=int(roi_rect[3]),
        )

        pixel_type = ""
        camera = str(self._core.get_camera_device() or "")
        if camera and self._core.has_property(camera, "PixelType"):
            pixel_type = str(self._core.get_property(camera, "PixelType"))

        xy_stage_device = ""
        focus_stage_device = ""
        stage_x_um: float | None = None
        stage_y_um: float | None = None
        stage_z_um: float | None = None

        try:
            xy_stage_device = str(self._core.get_xy_stage_device() or "")
        except Exception:
            xy_stage_device = ""
        if xy_stage_device:
            try:
                stage_x_um = float(self._core.get_x_position(xy_stage_device))
                stage_y_um = float(self._core.get_y_position(xy_stage_device))
            except Exception:
                stage_x_um = None
                stage_y_um = None

        try:
            focus_stage_device = str(self._core.get_focus_device() or "")
        except Exception:
            focus_stage_device = ""
        if focus_stage_device:
            try:
                stage_z_um = float(self._core.get_position(focus_stage_device))
            except Exception:
                stage_z_um = None

        return MicroManagerSnapshot(
            running=self._state.running,
            mm_root=str(self._mm_root),
            cfg_path=self._state.cfg_path,
            camera_device=camera,
            xy_stage_device=xy_stage_device,
            focus_stage_device=focus_stage_device,
            live_running=bool(self._core.is_sequence_running()),
            acquisition_running=self._state.acquisition_running,
            exposure_ms=float(self._core.get_exposure()),
            image_width=int(self._core.get_image_width()),
            image_height=int(self._core.get_image_height()),
            pixel_type=pixel_type,
            stage_x_um=stage_x_um,
            stage_y_um=stage_y_um,
            stage_z_um=stage_z_um,
            roi=roi,
            last_save_path=self._state.last_save_path,
            status_message=message,
        )

    def _default_status_message(self) -> str:
        if not self._state.running:
            return "Backend idle."
        if self._state.acquisition_running:
            return "Acquisition running"
        if self._core is not None:
            try:
                if self._core.is_sequence_running():
                    return "Live running."
            except Exception:
                pass
        return "Config loaded."

    def _collect_property_specs(self) -> list[CameraPropertySpec]:
        if self._core is None:
            return []
        camera = self._core.get_camera_device()
        specs: list[CameraPropertySpec] = []
        for name in list(self._core.get_device_property_names(camera)):
            allowed = [str(value) for value in list(self._core.get_allowed_property_values(camera, name))]
            has_limits = bool(self._core.has_property_limits(camera, name))
            lower = float(self._core.get_property_lower_limit(camera, name)) if has_limits else None
            upper = float(self._core.get_property_upper_limit(camera, name)) if has_limits else None
            specs.append(
                CameraPropertySpec(
                    name=str(name),
                    value=str(self._core.get_property(camera, name)),
                    read_only=bool(self._core.is_property_read_only(camera, name)),
                    allowed_values=allowed,
                    has_limits=has_limits,
                    lower_limit=lower,
                    upper_limit=upper,
                )
            )
        return sorted(specs, key=lambda item: item.name.lower())

    def _collect_config_groups(self) -> list[ConfigGroupSpec]:
        if self._core is None:
            return []
        groups: list[ConfigGroupSpec] = []
        for group in list(self._core.get_available_config_groups()):
            group_name = str(group)
            presets = [str(preset) for preset in list(self._core.get_available_configs(group_name))]
            try:
                current = str(self._core.get_current_config(group_name))
            except Exception:
                current = ""
            groups.append(ConfigGroupSpec(name=group_name, presets=presets, current_preset=current))
        return sorted(groups, key=lambda item: item.name.lower())

    def _prepare_runtime_env(self) -> None:
        if Acquisition is None or Core is None or start_headless is None or stop_headless is None:
            raise RuntimeError(f"pycromanager import failed: {_PYCROMANAGER_IMPORT_ERROR}")
        configure_runtime_environment()
        os.environ["PATH"] = str(self._mm_root) + os.pathsep + os.environ.get("PATH", "")
