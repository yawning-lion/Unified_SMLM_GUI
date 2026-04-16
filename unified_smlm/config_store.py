from __future__ import annotations

import copy
import json
import os
from functools import lru_cache
from pathlib import Path
import xml.etree.ElementTree as ET


PACKAGE_ROOT = Path(__file__).resolve().parent
_DLL_DIR_HANDLES: list[object] = []
_REGISTERED_DLL_DIRS: set[str] = set()


def package_root() -> Path:
    return PACKAGE_ROOT


def system_config_path() -> Path:
    override = os.environ.get("SMLM_SYSTEM_CONFIG", "").strip()
    if override:
        return Path(override).expanduser()
    return PACKAGE_ROOT / "system_config.json"


def load_system_config(*, force_reload: bool = False) -> dict:
    if force_reload:
        _load_system_config_cached.cache_clear()
    return copy.deepcopy(_load_system_config_cached())


@lru_cache(maxsize=1)
def _load_system_config_cached() -> dict:
    config_path = system_config_path()
    with config_path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def resolve_path(value: str | os.PathLike[str]) -> Path:
    path = Path(str(value)).expanduser()
    if path.is_absolute():
        return path
    return PACKAGE_ROOT / path


def get_path(key: str, *, config: dict | None = None) -> Path:
    cfg = config or load_system_config()
    env_override = _PATH_OVERRIDE_ENV_VARS.get(key, "")
    if env_override:
        override_value = os.environ.get(env_override, "").strip()
        if override_value:
            return resolve_path(override_value)
    value = cfg.get("paths", {}).get(key, "")
    return resolve_path(value)


def get_default_section(section_name: str, *, config: dict | None = None) -> dict:
    cfg = config or load_system_config()
    return copy.deepcopy(cfg.get("defaults", {}).get(section_name, {}))


def get_preset_defaults(preset_name: str, *, config: dict | None = None) -> dict:
    cfg = config or load_system_config()
    return copy.deepcopy(cfg.get("preset_defaults", {}).get(preset_name, {}))


def get_runtime_value(key: str, default=None, *, config: dict | None = None):
    cfg = config or load_system_config()
    return copy.deepcopy(cfg.get("runtime", {}).get(key, default))


def prepare_runtime_support_files(*, config: dict | None = None) -> None:
    cfg = config or load_system_config()
    focuslock_output_dir = get_path("focuslock_output_dir", config=cfg)
    focuslock_log_file = get_path("focuslock_log_file", config=cfg)
    teledyne_runtime_config = get_path("teledyne_runtime_config", config=cfg)

    focuslock_output_dir.mkdir(parents=True, exist_ok=True)
    focuslock_log_file.parent.mkdir(parents=True, exist_ok=True)
    teledyne_runtime_config.parent.mkdir(parents=True, exist_ok=True)

    materialize_focuslock_runtime_xml(config=cfg)
    materialize_teledyne_runtime_xml(config=cfg)


def configure_runtime_environment(*, config: dict | None = None) -> None:
    cfg = config or load_system_config()
    bin_dir = get_path("bin_dir", config=cfg)
    teledyne_bundle_root = get_path("teledyne_bundle_root", config=cfg)

    if bin_dir.exists():
        _prepend_path_once(bin_dir)
        _register_dll_directory(bin_dir)
    if teledyne_bundle_root.exists():
        _prepend_path_once(teledyne_bundle_root)
        _register_dll_directory(teledyne_bundle_root)

    prior_sdk_dll = get_path("prior_sdk_dll", config=cfg)
    uc480_dll = get_path("uc480_dll", config=cfg)
    uc480_tools_dll = get_path("uc480_tools_dll", config=cfg)

    os.environ["SMLM_PRIOR_SDK_DLL"] = str(prior_sdk_dll)
    os.environ["SMLM_UC480_DLL"] = str(uc480_dll)
    os.environ["SMLM_UC480_TOOLS_DLL"] = str(uc480_tools_dll)
    os.environ["SMLM_FOCUSLOCK_OUTPUT_DIR"] = str(get_path("focuslock_output_dir", config=cfg))


def materialize_teledyne_runtime_xml(*, config: dict | None = None) -> Path:
    cfg = config or load_system_config()
    source_path = get_path("teledyne_base_config", config=cfg)
    runtime_path = get_path("teledyne_runtime_config", config=cfg)

    tree = ET.parse(source_path)
    root = tree.getroot()
    hardware_cfg = cfg.get("hardware", {}).get("teledyne", {})

    focus_lock_node = _ensure_xml_node(root, "focusLock")
    for field_name, xml_tag in _TELEDYNE_FOCUSLOCK_FIELD_MAP.items():
        if field_name in hardware_cfg.get("focus_lock", {}):
            _set_xml_text(focus_lock_node, xml_tag, _xml_value(hardware_cfg["focus_lock"][field_name]))

    lasers_cfg = hardware_cfg.get("lasers", {})
    for laser_node in root.findall("./lasers/laser"):
        laser_id = laser_node.get("id", "") or _get_xml_text(laser_node, "name", "")
        if laser_id not in lasers_cfg:
            continue
        overrides = lasers_cfg[laser_id]
        for field_name, xml_tag in _TELEDYNE_LASER_FIELD_MAP.items():
            if field_name in overrides:
                _set_xml_text(laser_node, xml_tag, _xml_value(overrides[field_name]))

    daq_cfg = hardware_cfg.get("daq", {})
    daq_node = _ensure_xml_node(root, "NI-DAQmx")
    for field_name, xml_tag in _TELEDYNE_DAQ_FIELD_MAP.items():
        if field_name in daq_cfg:
            _set_xml_text(daq_node, xml_tag, _xml_value(daq_cfg[field_name]))

    ET.indent(tree, space="    ")
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(runtime_path, encoding="utf-8", xml_declaration=True)
    return runtime_path


def materialize_focuslock_runtime_xml(*, config: dict | None = None) -> Path:
    cfg = config or load_system_config()
    source_path = get_path("focuslock_base_xml", config=cfg)
    runtime_path = get_path("focuslock_runtime_xml", config=cfg)

    tree = ET.parse(source_path)
    root = tree.getroot()

    film_node = _ensure_xml_node(root, "film")
    directory_node = _ensure_xml_node(film_node, "directory")
    logfile_node = _ensure_xml_node(film_node, "logfile")

    directory_node.text = str(get_path("focuslock_output_dir", config=cfg))
    logfile_node.text = str(get_path("focuslock_log_file", config=cfg))

    ET.indent(tree, space="    ")
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(runtime_path, encoding="utf-8", xml_declaration=True)
    return runtime_path


def _prepend_path_once(path: Path) -> None:
    raw_path = str(path)
    existing = os.environ.get("PATH", "")
    parts = existing.split(os.pathsep) if existing else []
    if raw_path not in parts:
        os.environ["PATH"] = raw_path + os.pathsep + existing if existing else raw_path


def _register_dll_directory(path: Path) -> None:
    if not hasattr(os, "add_dll_directory"):
        return
    raw_path = str(path)
    if raw_path in _REGISTERED_DLL_DIRS:
        return
    try:
        handle = os.add_dll_directory(raw_path)
    except OSError:
        return
    _DLL_DIR_HANDLES.append(handle)
    _REGISTERED_DLL_DIRS.add(raw_path)


def _ensure_xml_node(parent: ET.Element, tag: str) -> ET.Element:
    node = parent.find(tag)
    if node is None:
        node = ET.SubElement(parent, tag)
    return node


def _set_xml_text(parent: ET.Element, tag: str, value: str) -> None:
    node = _ensure_xml_node(parent, tag)
    node.text = value


def _get_xml_text(parent: ET.Element, tag: str, default: str = "") -> str:
    node = parent.find(tag)
    if node is None or node.text is None:
        return default
    return node.text.strip()


def _xml_value(value) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


_TELEDYNE_FOCUSLOCK_FIELD_MAP = {
    "cam_model": "camModel",
    "piezo_comm": "piezoComm",
    "piezo_para": "piezoPara",
    "aoi_x": "aoi_x",
    "aoi_y": "aoi_y",
    "aoi_w": "aoi_w",
    "aoi_h": "aoi_h",
    "target_fps": "targetFPS",
    "img_exposure_us": "imgExposure",
    "ref_pos_mm": "refPos",
    "kp": "Kp",
    "ki": "Ki",
    "kd": "Kd",
    "pix_conve_ratio": "pixConveRatio",
    "spot_size": "spotSize",
    "spot_amp": "spotAmp",
    "spot_x": "spotX",
    "spot_y": "spotY",
    "spot_width": "spotWidth",
    "spot_offset": "spotOffset",
}


_TELEDYNE_LASER_FIELD_MAP = {
    "name": "name",
    "color": "color",
    "model": "model",
    "mode": "mode",
    "trigger_enable": "triggerEnable",
    "is_enable": "isEnable",
    "min_power_mw": "minPower",
    "max_power_mw": "maxPower",
    "min_current_ma": "minCurrent",
    "max_current_ma": "maxCurrent",
    "serial_port": "serialPort",
    "shg_temp_c": "shgTemp",
    "controller": "controller",
    "ao_port": "AO_port",
    "ao_freq_hz": "AO_freq",
    "ao_chan": "AO_chan",
    "ao_pwr": "AO_pwr",
}


_TELEDYNE_DAQ_FIELD_MAP = {
    "device_name": "deviceName",
    "chan_out_aotf_blank": "chanOut_aotfBlank",
    "chan_out_aotf_mod_1": "chanOut_aotfMod_1",
    "chan_out_aotf_mod_2": "chanOut_aotfMod_2",
    "chan_out_aotf_mod_3": "chanOut_aotfMod_3",
    "chan_out_405_laser_dig": "chanOut_405LaserDig",
    "chan_out_405_laser_mod": "chanOut_405LaserMod",
    "cam_trigger_chan": "camTriggerChan",
    "t1": "t1",
    "t2": "t2",
    "t3": "t3",
    "cam_expose_chan": "camExposeChan",
    "inter_tans_chan": "interTansChan",
    "inter_start_chan": "interStartChan",
    "expose_laser_chan": "exposeLaserChan",
    "focus_lock_laser_chan": "focusLockLaserChan",
    "focus_lock_cam_xy_chan": "focusLockCamXYchan",
    "focus_lock_cam_z_chan": "focusLockCamZchan",
    "gh_aotf_fsk_blank": "GH_AOTF_FSK_BLANK",
    "laser_digital_chan": "laserDigitalChan",
}


_PATH_OVERRIDE_ENV_VARS = {
    "micromanager_root": "SMLM_MM_ROOT",
    "micromanager_cfg": "SMLM_MM_CFG",
    "roi_file": "SMLM_ROI_FILE",
    "teledyne_bundle_root": "SMLM_TELEDYNE_BUNDLE_ROOT",
    "teledyne_exe": "SMLM_TELEDYNE_EXE",
    "teledyne_base_config": "SMLM_TELEDYNE_BASE_CONFIG",
    "teledyne_runtime_config": "SMLM_TELEDYNE_RUNTIME_CONFIG",
    "teledyne_aotf_calibration": "SMLM_TELEDYNE_AOTF_CALIBRATION",
    "bin_dir": "SMLM_BIN_DIR",
    "prior_sdk_dll": "SMLM_PRIOR_SDK_DLL",
    "uc480_dll": "SMLM_UC480_DLL",
    "uc480_tools_dll": "SMLM_UC480_TOOLS_DLL",
    "focuslock_base_xml": "SMLM_FOCUSLOCK_BASE_XML",
    "focuslock_runtime_xml": "SMLM_FOCUSLOCK_RUNTIME_XML",
    "focuslock_output_dir": "SMLM_FOCUSLOCK_OUTPUT_DIR",
    "focuslock_log_file": "SMLM_FOCUSLOCK_LOG_FILE",
}
