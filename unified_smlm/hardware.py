from __future__ import annotations

from pathlib import Path

from .models import HardwareStatus, MicroManagerSnapshot, UnifiedSettings


def _compact_path(path: Path, *, keep_parts: int = 2) -> str:
    parts = list(path.parts)
    if len(parts) <= keep_parts:
        return str(path)
    return "...\\" + "\\".join(parts[-keep_parts:])


class UnifiedHardwareManager:
    def __init__(self, settings: UnifiedSettings) -> None:
        self.settings = settings

    def _path_status(self, name: str, path: Path, action: str) -> HardwareStatus:
        if path.exists():
            state = "Ready"
            details = f"Found at {_compact_path(path)}"
        else:
            state = "Missing"
            details = f"Path not found: {_compact_path(path)}"
        return HardwareStatus(name=name, state=state, details=details, action=action)

    def evaluate_statuses(self, snapshot: MicroManagerSnapshot | None = None) -> list[HardwareStatus]:
        paths = self.settings.paths
        focuslock_vendor_root = Path(__file__).resolve().parent / "vendor" / "focuslock_ix83"
        mm_snapshot = snapshot or MicroManagerSnapshot()
        inspection_suffix = "Inspection mode skips live device handshakes."

        if mm_snapshot.running:
            mm_state = "Loaded"
            mm_details = (
                f"Embedded backend loaded {mm_snapshot.camera_device or 'camera'} "
                f"from {_compact_path(Path(mm_snapshot.cfg_path or paths.micromanager_cfg))}"
            )
            mm_action = "Use Start Live / Snap / ROI controls in the GUI."
        else:
            mm_state = "Idle"
            mm_details = "Embedded backend is not loaded yet."
            mm_action = "Select a cfg and click Load Config in the GUI."

        statuses = [
            self._path_status("Micro-Manager root", paths.micromanager_root, "Keep device adapters available"),
            self._path_status("Micro-Manager config", paths.micromanager_cfg, "Load the desired cfg in the GUI"),
            HardwareStatus(
                name="Embedded Micro-Manager backend",
                state=mm_state,
                details=mm_details,
                action=mm_action,
            ),
            self._path_status("Teledyne hardware bundle", paths.teledynecam_exe, "Keep DLLs available for the native Python backend"),
            self._path_status("Teledyne config XML", paths.teledynecam_config, "Reload or save it from the source-backed Teledyne panel"),
            self._path_status(
                "Teledyne AOTF calibration",
                paths.teledynecam_aotf_calibration,
                "Keep the calibration table available for the source-backed Teledyne Python runtime",
            ),
            self._path_status("ROI preset", paths.roi_file, "Keep the ROI file available"),
            self._path_status("Integrated focus lock bundle", focuslock_vendor_root, "Load the workspace vendor copy in-process"),
            HardwareStatus(
                name="sCMOS camera",
                state="Streaming" if mm_snapshot.live_running else ("Configured" if mm_snapshot.running else "Unknown"),
                details=(
                    f"MM camera device: {mm_snapshot.camera_device or 'not loaded'}."
                    if mm_snapshot.running
                    else f"Camera backend is not loaded. {inspection_suffix}"
                ),
                action="Load the Micro-Manager cfg and start live preview",
            ),
            HardwareStatus(
                name="ODT camera",
                state="Not connected" if self.settings.state.inspection_mode else "Unknown",
                details=f"ODT camera is not checked from this GUI yet. {inspection_suffix}",
                action="Power on the ODT camera and reopen the GUI",
            ),
            HardwareStatus(
                name="Laser combiner / AOTF",
                state="Not connected" if self.settings.state.inspection_mode else "Unknown",
                details=f"Controller API is not handshaked in inspection mode. {inspection_suffix}",
                action="Power on the laser combiner and AOTF, then use Reconnect Hardware",
            ),
            HardwareStatus(
                name="Focus lock camera",
                state="Not connected" if self.settings.state.inspection_mode else "Unknown",
                details=f"Focus lock camera is not queried in inspection mode. {inspection_suffix}",
                action="Power on the focus lock camera, then open the integrated Focus Lock module",
            ),
            HardwareStatus(
                name="Prior Z stage",
                state="Not connected" if self.settings.state.inspection_mode else "Unknown",
                details=f"Stage control is not queried in inspection mode. {inspection_suffix}",
                action="Power on the stage controller, then open the integrated Focus Lock module",
            ),
        ]
        return statuses

    def inspection_banner(self) -> str:
        if self.settings.state.inspection_mode:
            return (
                "Inspection mode is active. The source-backed Teledyne Python backend and focus lock remain in-process, but device handshakes stay conservative "
                "until you explicitly load a Micro-Manager cfg and start acquisition."
            )
        return "Live mode requested. Micro-Manager now runs in-process inside the unified GUI."

    def reconnect_hardware(self, snapshot: MicroManagerSnapshot | None = None) -> list[HardwareStatus]:
        return self.evaluate_statuses(snapshot=snapshot)

    def perform_safe_shutdown(self) -> list[str]:
        illumination = self.settings.illumination
        actions = []

        illumination.laser_642_setpoint = illumination.safe_shutdown_setpoint
        illumination.aotf_642_setpoint = 0.0
        illumination.aotf_642_enabled = False
        illumination.channel_642_enabled = False
        illumination.modulation_mode = "Independent mode"

        if self.settings.state.inspection_mode:
            actions.append(
                "Inspection mode dry-run: set 642 laser to the safe shutdown setpoint, disabled AOTF, and skipped live hardware commands."
            )
        else:
            actions.append(
                "Applied the internal safe shutdown model. Direct hardware command hooks still need device APIs for live power ramp-down."
            )
        return actions
