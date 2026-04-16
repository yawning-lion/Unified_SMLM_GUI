from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import os
from pathlib import Path

from .config_store import (
    configure_runtime_environment,
    get_default_section,
    get_path,
    load_system_config,
    prepare_runtime_support_files,
)


@dataclass
class ExternalPaths:
    micromanager_root: Path
    micromanager_java: Path
    micromanager_cfg: Path
    teledynecam_exe: Path
    teledynecam_config: Path
    teledynecam_aotf_calibration: Path
    roi_file: Path


@dataclass
class AcquisitionSettings:
    sample_name: str = ""
    save_prefix: str = ""
    save_root: str = ""
    trial_index: int = 0
    auto_advance_trial: bool = True
    roi_name: str = ""
    exposure_ms: float = 25.0
    trigger_mode: str = "Internal"
    saving_format: str = "Image Stack File"
    widefield_frames: int = 10
    storm_total_frames: int = 20000


@dataclass
class IlluminationSettings:
    channel_642_enabled: bool = True
    laser_642_setpoint: float = 100.0
    aotf_642_enabled: bool = True
    aotf_642_setpoint: float = 4.4
    modulation_mode: str = "Independent mode"
    safe_shutdown_setpoint: float = 100.0


@dataclass
class FocusLockSettings:
    mode: str = "Always On"
    locked: bool = False
    jump_offset_um: float = 10.0
    z_start_um: float = -4.5
    z_end_um: float = 4.5
    depth_count: int = 10
    frames_per_depth_per_round: int = 100
    qpd_zcenter_um: float = 200.0
    qpd_scale: float = 1.0
    qpd_sum_min: float = 25.0
    qpd_sum_max: float = 256.0
    lock_step_um: float = 0.04
    is_locked_buffer_length: int = 1
    is_locked_offset_thresh: float = 0.1
    prior_com_port: int = 20


@dataclass
class BleachSettings:
    duration_minutes: float = 4.0
    bleach_laser_power_mw: float = 1000.0
    bleach_aotf_value: float = 100.0
    return_laser_power_mw: float = 400.0


@dataclass
class AppState:
    inspection_mode: bool = False
    active_preset: str = "ROI Preview"
    preview_running: bool = False
    theme: str = "Light"
    session_timestamp_prefix: str = ""


@dataclass
class HardwareStatus:
    name: str
    state: str
    details: str
    action: str


@dataclass
class ZScanPlan:
    depth_count: int
    step_um: float
    rounds: int
    full_rounds: int
    last_round_frames_per_depth: int
    frames_per_depth_per_round: int
    total_frames_per_depth_target: int
    total_frames_all_depths: int
    exposure_ms: float
    trigger_mode: str


@dataclass
class RoiRect:
    kind: str
    x: int
    y: int
    width: int
    height: int


@dataclass
class CameraPropertySpec:
    name: str
    value: str
    read_only: bool
    allowed_values: list[str] = field(default_factory=list)
    has_limits: bool = False
    lower_limit: float | None = None
    upper_limit: float | None = None


@dataclass
class ConfigGroupSpec:
    name: str
    presets: list[str]
    current_preset: str


@dataclass
class MicroManagerSnapshot:
    running: bool = False
    mm_root: str = ""
    cfg_path: str = ""
    camera_device: str = ""
    xy_stage_device: str = ""
    focus_stage_device: str = ""
    live_running: bool = False
    acquisition_running: bool = False
    exposure_ms: float = 0.0
    image_width: int = 0
    image_height: int = 0
    pixel_type: str = ""
    stage_x_um: float | None = None
    stage_y_um: float | None = None
    stage_z_um: float | None = None
    roi: RoiRect | None = None
    last_save_path: str = ""
    status_message: str = "Micro-Manager backend idle."


@dataclass
class MDAAcquisitionRequest:
    preset_name: str
    frame_count: int
    expected_image_count: int
    saving_format: str
    base_name: str
    save_dir: str
    output_path: str
    dataset_name: str | None
    dataset_path: str | None
    exposure_ms: float
    trigger_mode: str
    z_start_um: float = 0.0
    z_end_um: float = 0.0
    z_step_um: float = 0.0
    depth_count: int = 1
    coordinated_focus_lock_scan: bool = False
    z_round_frames_per_depth: tuple[int, ...] = ()


@dataclass
class UnifiedSettings:
    paths: ExternalPaths
    acquisition: AcquisitionSettings = field(default_factory=AcquisitionSettings)
    illumination: IlluminationSettings = field(default_factory=IlluminationSettings)
    focus_lock: FocusLockSettings = field(default_factory=FocusLockSettings)
    bleach: BleachSettings = field(default_factory=BleachSettings)
    state: AppState = field(default_factory=AppState)


def build_default_paths() -> ExternalPaths:
    config = load_system_config()
    prepare_runtime_support_files(config=config)
    configure_runtime_environment(config=config)
    mm_root = get_path("micromanager_root", config=config)
    return ExternalPaths(
        micromanager_root=mm_root,
        micromanager_java=mm_root / "jre" / "bin" / "java.exe",
        micromanager_cfg=get_path("micromanager_cfg", config=config),
        teledynecam_exe=get_path("teledyne_exe", config=config),
        teledynecam_config=get_path("teledyne_runtime_config", config=config),
        teledynecam_aotf_calibration=get_path("teledyne_aotf_calibration", config=config),
        roi_file=get_path("roi_file", config=config),
    )


def build_default_settings() -> UnifiedSettings:
    config = load_system_config()
    prepare_runtime_support_files(config=config)
    configure_runtime_environment(config=config)
    settings = UnifiedSettings(paths=build_default_paths())
    _apply_section(settings.acquisition, get_default_section("acquisition", config=config))
    _apply_section(settings.illumination, get_default_section("illumination", config=config))
    _apply_section(settings.focus_lock, get_default_section("focus_lock", config=config))
    _apply_section(settings.bleach, get_default_section("bleach", config=config))
    _apply_section(settings.state, get_default_section("state", config=config))
    _apply_env_overrides(settings)
    if not settings.acquisition.roi_name:
        settings.acquisition.roi_name = str(settings.paths.roi_file)
    settings.state.session_timestamp_prefix = datetime.now().strftime("%Y%m%d_%H%M%S")
    from .presets import apply_preset

    apply_preset(settings, settings.state.active_preset)
    return settings


def _apply_section(target: object, values: dict) -> None:
    for key, value in values.items():
        if hasattr(target, key):
            setattr(target, key, value)


def _apply_env_overrides(settings: UnifiedSettings) -> None:
    save_root_override = os.environ.get("SMLM_SAVE_ROOT", "").strip()
    if save_root_override:
        settings.acquisition.save_root = save_root_override

    active_preset_override = os.environ.get("SMLM_ACTIVE_PRESET", "").strip()
    if active_preset_override:
        settings.state.active_preset = active_preset_override
