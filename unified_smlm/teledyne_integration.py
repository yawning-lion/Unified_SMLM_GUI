from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config_store import (
    configure_runtime_environment,
    get_path,
    materialize_teledyne_runtime_xml,
    prepare_runtime_support_files,
)
from .models import UnifiedSettings
from .teledyne_native import (
    TeledyneSourceModel,
    TeledyneSourceRuntime,
    detect_runtime_capabilities,
)


@dataclass
class NativeTeledyneSnapshot:
    status: str
    config_path: str
    laser_summary: str
    aotf_summary: str
    modulation_summary: str
    camera_sync_summary: str
    daq_summary: str
    safe_shutdown_summary: str
    scope_summary: str


class IntegratedTeledyneCamController:
    def __init__(self, settings: UnifiedSettings) -> None:
        self.settings = settings
        prepare_runtime_support_files()
        configure_runtime_environment()
        self.config_path = materialize_teledyne_runtime_xml()
        self.calibration_path = get_path("teledyne_aotf_calibration")
        self.settings.paths.teledynecam_config = self.config_path
        self.settings.paths.teledynecam_aotf_calibration = self.calibration_path
        self.bundle_root = self._resolve_bundle_root()
        self.capabilities = detect_runtime_capabilities(self.bundle_root)
        self.model: TeledyneSourceModel | None = None
        self._runtime: TeledyneSourceRuntime | None = None
        self.last_error: str | None = None
        self._last_message = ""
        self.reload_config()
        self.sync_from_settings(settings)

    def status_text(self) -> str:
        if self.last_error:
            return f"Unavailable: {self.last_error}"
        if self.model is None:
            return "Native backend idle."
        state = "dirty" if self.model.dirty else "clean"
        calib_rows = self.model.calibration.row_count
        calib_text = f"calibration rows {calib_rows}" if calib_rows else "no calibration table"
        return (
            f"Source-aligned Python backend loaded {self.config_path.name} "
            f"({state}, {calib_text}, {self.capabilities.summary()})."
        )

    def open_module(self, _main_window: object | None = None) -> tuple[bool, str]:
        return self.reload_config()

    def close_module(self) -> tuple[bool, str]:
        return self.save_config()

    def cleanup(self) -> list[str]:
        actions: list[str] = []
        if self._runtime is not None:
            try:
                self._runtime.close()
                actions.append("Closed native Teledyne runtime adapters.")
            except Exception as exc:
                actions.append(f"Teledyne runtime cleanup reported an error: {exc}")
            finally:
                self._runtime = None
        return actions

    def reload_config(self) -> tuple[bool, str]:
        try:
            prepare_runtime_support_files()
            configure_runtime_environment()
            self.config_path = materialize_teledyne_runtime_xml()
            self.calibration_path = get_path("teledyne_aotf_calibration")
            self.settings.paths.teledynecam_config = self.config_path
            self.settings.paths.teledynecam_aotf_calibration = self.calibration_path
            if not self.config_path.exists():
                raise FileNotFoundError(self.config_path)
            self.bundle_root = self._resolve_bundle_root()
            self.capabilities = detect_runtime_capabilities(self.bundle_root)
            self.model = TeledyneSourceModel.load(self.config_path, self.calibration_path)
            if self._runtime is not None:
                self._runtime.model = self.model
                self._runtime.bundle_root = self.bundle_root
                self._runtime.capabilities = self.capabilities
                self._runtime.daq.config = self.model.daq
            self.last_error = None
            self._last_message = f"Loaded native Teledyne source model: {self.config_path.name}"
            return True, self._last_message
        except Exception as exc:
            self.model = None
            self.last_error = f"Native Teledyne config load failed: {exc}"
            return False, self.last_error

    def save_config(self) -> tuple[bool, str]:
        if self.model is None:
            return False, "Native Teledyne config is not loaded."
        try:
            self.model.save()
            self.last_error = None
            self._last_message = f"Saved native Teledyne config: {self.config_path.name}"
            return True, self._last_message
        except Exception as exc:
            self.last_error = f"Native Teledyne config save failed: {exc}"
            return False, self.last_error

    def sync_from_settings(self, settings: UnifiedSettings) -> None:
        self.settings = settings
        if self.model is None:
            return
        self.model.sync_unified_settings(settings)

    def build_runtime(self) -> TeledyneSourceRuntime:
        if self.model is None:
            raise RuntimeError("Native Teledyne model is not loaded.")
        if self._runtime is None:
            self._runtime = TeledyneSourceRuntime(self.model, self.bundle_root)
        else:
            self._runtime.model = self.model
            self._runtime.bundle_root = self.bundle_root
            self._runtime.capabilities = self.capabilities
            self._runtime.daq.config = self.model.daq
        return self._runtime

    def apply_runtime(self, *, reason: str = "") -> tuple[bool, str]:
        self.sync_from_settings(self.settings)
        if self.model is None:
            return False, "Native Teledyne model is not loaded."

        illumination = self.settings.illumination
        if self.settings.state.inspection_mode:
            message = (
                f"Inspection mode dry-run: would apply Teledyne runtime for {reason or 'current settings'} "
                f"with 647 laser {illumination.laser_642_setpoint:.1f} mW, "
                f"AOTF throughput {illumination.aotf_642_setpoint:.1f}, "
                f"mode {illumination.modulation_mode}."
            )
            self.last_error = None
            self._last_message = message
            return True, message

        try:
            runtime = self.build_runtime()
            runtime.apply_illumination_state(
                laser_id="647",
                laser_enabled=illumination.channel_642_enabled,
                laser_power_mw=illumination.laser_642_setpoint,
                aotf_enabled=illumination.aotf_642_enabled,
                aotf_throughput_percent=illumination.aotf_642_setpoint,
                modulation_mode=illumination.modulation_mode,
            )
            laser = self.model.lasers.get("647")
            analog_value = self.model.calibration.analog_value_for_percent(
                "647",
                float(illumination.aotf_642_setpoint),
            )
            freq_text = f"{laser.ao_freq_hz:.4f}" if laser is not None else "-"
            chan_text = str(laser.ao_chan) if laser is not None else "-"
            pwr_text = str(laser.ao_pwr) if laser is not None else "-"
            message = (
                f"Applied Teledyne runtime for {reason or 'current settings'}: "
                f"647 laser {illumination.laser_642_setpoint:.1f} mW, "
                f"AOTF throughput {illumination.aotf_642_setpoint:.1f}, "
                f"mode {illumination.modulation_mode}, "
                f"DDS freq {freq_text}, chan {chan_text}, amp {pwr_text}, "
                f"analog {analog_value:.3f} V."
            )
            self.last_error = None
            self._last_message = message
            return True, message
        except Exception as exc:
            self.last_error = f"Native Teledyne runtime apply failed: {exc}"
            return False, self.last_error

    def safe_shutdown_runtime(self, *, reason: str = "") -> tuple[bool, str]:
        safe_power = self.settings.illumination.safe_shutdown_setpoint
        if self.settings.state.inspection_mode:
            message = (
                f"Inspection mode dry-run: would safe-shutdown Teledyne runtime for {reason or 'current session'} "
                f"by ramping 647 to {safe_power:.1f}, disabling AOTF, then disabling the laser."
            )
            self.last_error = None
            self._last_message = message
            return True, message

        if self.model is None:
            return False, "Native Teledyne model is not loaded."

        try:
            runtime = self.build_runtime()
            runtime.set_laser_output("647", enabled=True, power_mw=safe_power)
            runtime.disable_all_aotf_outputs()
            runtime.set_laser_output("647", enabled=False)
            runtime.safe_shutdown()
            self._runtime = None
            message = (
                f"Applied Teledyne safe shutdown for {reason or 'current session'}: "
                f"set 647 laser to {safe_power:.1f}, disabled AOTF outputs, drove NI-DAQ outputs low, reset the AOTF DDS state, then turned the laser off."
            )
            self.last_error = None
            self._last_message = message
            return True, message
        except Exception as exc:
            self.last_error = f"Native Teledyne safe shutdown failed: {exc}"
            return False, self.last_error

    def ui_snapshot(self) -> NativeTeledyneSnapshot:
        if self.model is None:
            return NativeTeledyneSnapshot(
                status=self.status_text(),
                config_path=str(self.config_path),
                laser_summary="-",
                aotf_summary="-",
                modulation_summary=self.settings.illumination.modulation_mode,
                camera_sync_summary="-",
                daq_summary="-",
                safe_shutdown_summary=(
                    f"Set 642/647 target to {self.settings.illumination.safe_shutdown_setpoint:.1f}, "
                    "then disable AOTF and laser outputs."
                ),
                scope_summary="Native Python backend is unavailable until the Teledyne XML model loads.",
            )

        laser = self.model.lasers.get("647")
        camera = self.model.camera
        daq = self.model.daq
        target_power = (
            laser.unified_target_power
            if laser is not None and laser.unified_target_power is not None
            else self.settings.illumination.laser_642_setpoint
        )
        target_aotf = (
            laser.unified_aotf_target
            if laser is not None and laser.unified_aotf_target is not None
            else self.settings.illumination.aotf_642_setpoint
        )
        modulation_mode = (
            laser.unified_modulation_mode
            if laser is not None and laser.unified_modulation_mode
            else self.settings.illumination.modulation_mode
        )

        laser_summary = "-"
        aotf_summary = "-"
        if laser is not None:
            laser_summary = (
                f"{'Enabled' if laser.is_enable else 'Disabled'}, {laser.model or '-'} on "
                f"{laser.serial_port or '-'}, controller {laser.controller or '-'}, unified target {target_power:.1f}"
            )
            aotf_summary = (
                f"DDS amp {laser.ao_pwr}, freq {laser.ao_freq_hz:.4f}, chan {laser.ao_chan}, "
                f"calib rows {len(laser.calibration_values)}, unified target {target_aotf:.2f}"
            )

        camera_sync_summary = "-"
        if camera is not None:
            trigger_text = camera.unified_trigger_mode or self.settings.acquisition.trigger_mode
            camera_sync_summary = (
                f"{camera.camera_id}: exposure {camera.expose_time_ms:.1f} ms, trigger {trigger_text}, "
                f"save {_compact_camera_path(camera.record_path)}"
            )

        daq_summary = (
            f"{daq.device_name or '-'}: blank {daq.chan_out_aotf_blank or '-'}, "
            f"mod0 {daq.chan_out_aotf_mod.get(0, '-') or '-'}, "
            f"mod1 {daq.chan_out_aotf_mod.get(1, '-') or '-'}, "
            f"mod2 {daq.chan_out_aotf_mod.get(2, '-') or '-'}, "
            f"cam trig {daq.cam_trigger_chan or '-'}"
        )

        return NativeTeledyneSnapshot(
            status=self.status_text(),
            config_path=str(self.config_path),
            laser_summary=laser_summary,
            aotf_summary=aotf_summary,
            modulation_summary=modulation_mode,
            camera_sync_summary=camera_sync_summary,
            daq_summary=daq_summary,
            safe_shutdown_summary=(
                f"Set 642/647 target to {self.settings.illumination.safe_shutdown_setpoint:.1f}, "
                "then drive NI outputs low, reset AOTF DDS, and disable laser outputs."
            ),
            scope_summary=(
                "Python backend now mirrors the TeledyneCam C/Qt source structure: XML model, serial laser adapter, "
                f"AOTF DLL adapter, and NI-DAQ adapter live in one codebase. Runtime capability scan: {self.capabilities.summary()}. "
                "The live camera wrapper is still a separate follow-up."
            ),
        )

    def _resolve_bundle_root(self) -> Path:
        candidates = [
            Path(self.settings.paths.teledynecam_exe).parent,
            self.config_path.parent,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]


def _compact_camera_path(path_value: str) -> str:
    path = Path(str(path_value or "").strip())
    parts = list(path.parts)
    if len(parts) <= 2:
        return str(path) or "-"
    return "...\\" + "\\".join(parts[-2:])
