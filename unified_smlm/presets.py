from __future__ import annotations

from .config_store import get_preset_defaults
from .planning import compute_z_scan_plan
from .models import UnifiedSettings


PRESET_SEARCH_FOCUS = "Search / Focus"
PRESET_ROI_PREVIEW = "ROI Preview"
PRESET_WIDEFIELD_TEST = "Widefield Test"
PRESET_STORM_2D = "STORM 2D"
PRESET_WHOLE_CELL_Z = "Whole-Cell Z Scan"


PRESET_ORDER = [
    PRESET_ROI_PREVIEW,
    PRESET_WIDEFIELD_TEST,
    PRESET_STORM_2D,
    PRESET_WHOLE_CELL_Z,
]


def build_preset_guidance_lines(settings: UnifiedSettings, preset_name: str) -> list[str]:
    if preset_name == PRESET_SEARCH_FOCUS:
        preset_name = PRESET_ROI_PREVIEW
    acquisition = settings.acquisition
    illumination = settings.illumination
    focus_lock = settings.focus_lock
    lines = [
        f"Preset guide: {preset_name}",
        (
            "Current config: "
            f"Exposure {acquisition.exposure_ms:.1f} ms | "
            f"Trigger {acquisition.trigger_mode} | "
            f"Saving {acquisition.saving_format} | "
            f"Modulation {illumination.modulation_mode} | "
            f"642 {illumination.laser_642_setpoint:.1f} mW | "
            f"AOTF {illumination.aotf_642_setpoint:.1f} | "
            f"Focus {focus_lock.mode} / {'Locked' if focus_lock.locked else 'Unlocked'}"
        ),
    ]

    if preset_name == PRESET_ROI_PREVIEW:
        lines.extend(
            [
                "Use: Verify the final cropped field of view, brightness, and focus stability after the sample has already been found.",
                "This is the only preview preset in the unified GUI. Use it to find focus first; the GUI no longer auto-locks focus when you enter a preset.",
                "How to use: Load Config -> let the default ROI apply -> find focus with live preview -> manually lock at the desired plane -> confirm that the ROI, signal level, and lock stability look correct -> then switch to Widefield Test, STORM 2D, or Whole-Cell Z Scan.",
                f"Preview target: {acquisition.widefield_frames} frames for a short confirmation run.",
            ]
        )
    elif preset_name == PRESET_WIDEFIELD_TEST:
        lines.extend(
            [
                "Use: Acquire a short internal-trigger stack to verify saving, brightness, and sample quality before a long run.",
                "How to use: Load Config -> confirm ROI and focus -> keep trigger on Internal -> press Acquire for a short stack check.",
                f"Configured stack length: {acquisition.widefield_frames} frames saved as {acquisition.saving_format}.",
            ]
        )
    elif preset_name == PRESET_STORM_2D:
        lines.extend(
            [
                "Use: Standard 2D single-molecule acquisition after the fluorophores have been driven into a sparse blinking state.",
                "How to use: Load Config -> confirm ROI -> manually lock focus at the imaging plane -> set the illumination path to one-chan FSK mode -> keep trigger on Internal -> press Acquire.",
                "Entry requirement: the focus lock must already be initialized and manually locked before this preset can be selected.",
                f"Configured acquisition length: {acquisition.storm_total_frames} frames saved as {acquisition.saving_format}.",
            ]
        )
    elif preset_name == PRESET_WHOLE_CELL_Z:
        plan = compute_z_scan_plan(settings)
        lines.extend(
            [
                "Use: Coordinated whole-cell Z acquisition. The camera is armed in External trigger mode first, then the focus-lock DAQ routine moves Z and emits one trigger per frame.",
                (
                    "Whole-cell Z config: "
                    f"Start {focus_lock.z_start_um:.3f} um | "
                    f"End {focus_lock.z_end_um:.3f} um | "
                    f"Step {plan.step_um:.3f} um | "
                    f"Depths {focus_lock.depth_count} | "
                    f"Frames/depth/round {focus_lock.frames_per_depth_per_round} | "
                    f"Rounds {plan.rounds}"
                ),
                "Z Start and Z End are relative to the current focus-lock stage position at the moment the coordinated scan begins. In other words, the current locked plane is the reference point for the scan.",
                "The default range is symmetric around the current locked plane (-4.5 um to +4.5 um) because the usual workflow is to focus near the cell center before scanning.",
                "If the current locked plane is treated as 0.000 um, then Start = 0 and End = 9 means the scan runs from the current plane upward to +9 um and returns to the reference plane between rounds.",
                "Recommended button order: Load Config -> initialize focus lock -> find focus -> manually lock at the reference plane you want to scan around -> set Start / End / Z Step or Depth Count -> confirm External trigger and one-chan FSK mode -> press Acquire.",
                "Entry requirement: the focus lock must already be initialized and manually locked before this preset can be selected.",
                "For a real dataset, press Acquire. Do not press Run Z Scan first. Acquire now arms the camera and then launches the coordinated DAQ-driven scan automatically.",
                f"Configured per-depth target: {acquisition.storm_total_frames} frames total, split into {plan.rounds} rounds.",
            ]
        )

    return lines


def apply_preset(settings: UnifiedSettings, preset_name: str) -> None:
    if preset_name == PRESET_SEARCH_FOCUS:
        preset_name = PRESET_ROI_PREVIEW
    acquisition = settings.acquisition
    illumination = settings.illumination
    focus_lock = settings.focus_lock
    settings.state.active_preset = preset_name
    preset = get_preset_defaults(preset_name)
    if not preset:
        return

    if "trigger_mode" in preset:
        acquisition.trigger_mode = str(preset["trigger_mode"])
    if "saving_format" in preset:
        acquisition.saving_format = str(preset["saving_format"])
    if "widefield_frames" in preset:
        acquisition.widefield_frames = int(preset["widefield_frames"])
    if "channel_642_enabled" in preset:
        illumination.channel_642_enabled = bool(preset["channel_642_enabled"])
    if "aotf_642_enabled" in preset:
        illumination.aotf_642_enabled = bool(preset["aotf_642_enabled"])
    if "modulation_mode" in preset:
        illumination.modulation_mode = str(preset["modulation_mode"])
    if "laser_642_setpoint_max" in preset:
        illumination.laser_642_setpoint = min(
            float(illumination.laser_642_setpoint),
            float(preset["laser_642_setpoint_max"]),
        )
    elif "laser_642_setpoint" in preset:
        illumination.laser_642_setpoint = float(preset["laser_642_setpoint"])
    if "aotf_642_setpoint" in preset:
        illumination.aotf_642_setpoint = float(preset["aotf_642_setpoint"])
    if "focus_mode" in preset:
        focus_lock.mode = str(preset["focus_mode"])
    if "z_start_um" in preset:
        focus_lock.z_start_um = float(preset["z_start_um"])
    if "z_end_um" in preset:
        focus_lock.z_end_um = float(preset["z_end_um"])
    if "depth_count" in preset:
        focus_lock.depth_count = int(preset["depth_count"])
    if "frames_per_depth_per_round" in preset:
        focus_lock.frames_per_depth_per_round = int(preset["frames_per_depth_per_round"])
