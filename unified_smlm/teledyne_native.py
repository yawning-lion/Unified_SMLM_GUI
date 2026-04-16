from __future__ import annotations

import csv
import ctypes
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
import xml.etree.ElementTree as ET

try:
    import nidaqmx
    from nidaqmx.constants import LineGrouping
except Exception:  # pragma: no cover - optional hardware dependency
    nidaqmx = None
    LineGrouping = None

try:
    import serial
except Exception:  # pragma: no cover - optional hardware dependency
    serial = None

if TYPE_CHECKING:
    from .models import UnifiedSettings

from .save_paths import build_acquisition_path_plan


def _find_child(parent: ET.Element, tag: str) -> ET.Element | None:
    for child in parent:
        if child.tag == tag:
            return child
    return None


def _text(parent: ET.Element | None, tag: str, default: str = "") -> str:
    if parent is None:
        return default
    child = _find_child(parent, tag)
    if child is None or child.text is None:
        return default
    return child.text.strip()


def _set_text(parent: ET.Element, tag: str, value: str) -> None:
    child = _find_child(parent, tag)
    if child is None:
        child = ET.SubElement(parent, tag)
    child.text = value


def _bool_text(value: bool) -> str:
    return "1" if value else "0"


def _to_int(value: str, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return default


def _to_float(value: str, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except Exception:
        return default


@dataclass
class TeledyneLaserConfig:
    laser_id: str
    name: str
    color: str
    model: str
    mode: str
    trigger_enable: bool
    is_enable: bool
    min_power_mw: float
    max_power_mw: float
    min_current_ma: float
    max_current_ma: float
    serial_port: str
    shg_temp_c: int
    controller: str
    ao_port: str
    ao_freq_hz: float
    ao_chan: int
    ao_pwr: int
    calibration_values: list[float] = field(default_factory=list)
    unified_target_power: float | None = None
    unified_aotf_target: float | None = None
    unified_modulation_mode: str = ""
    unified_safe_shutdown: float | None = None


@dataclass
class TeledyneCameraConfig:
    camera_id: str
    record_path: str
    expose_time_ms: float
    trigger_in: int
    trigger_out: int
    unified_trigger_mode: str = ""
    unified_roi_preset: str = ""
    unified_saving_format: str = ""


@dataclass
class TeledyneFocusLockConfig:
    raw_values: dict[str, str] = field(default_factory=dict)
    unified_mode: str = ""
    unified_locked: bool = False
    unified_jump_offset_um: float = 0.0
    unified_depth_count: int = 0
    unified_frames_per_depth_per_round: int = 0


@dataclass
class TeledyneDaqConfig:
    device_name: str = ""
    chan_out_aotf_blank: str = ""
    chan_out_aotf_mod: dict[int, str] = field(default_factory=dict)
    chan_out_405_laser_dig: str = ""
    chan_out_405_laser_mod: str = ""
    cam_trigger_chan: str = ""
    cam_expose_chan: str = ""
    inter_tans_chan: str = ""
    inter_start_chan: str = ""
    expose_laser_chan: str = ""
    focus_lock_laser_chan: str = ""
    focus_lock_cam_xy_chan: str = ""
    focus_lock_cam_z_chan: str = ""
    gh_aotf_fsk_blank: str = ""
    laser_digital_chan: str = ""


@dataclass
class TeledyneCalibrationTable:
    values: dict[str, list[float]] = field(default_factory=dict)

    @property
    def row_count(self) -> int:
        if not self.values:
            return 0
        return max((len(rows) for rows in self.values.values()), default=0)

    def analog_value_for_percent(self, laser_id: str, percent: float) -> float:
        values = self.values.get(laser_id, [])
        if not values:
            return 0.0
        index = max(0, min(len(values) - 1, int(round(percent * 10.0))))
        return float(values[index])


@dataclass
class TeledyneRuntimeCapabilities:
    bundle_root: Path
    aotf_dll_path: Path
    camera_sdk_path: Path
    serial_available: bool
    nidaqmx_available: bool
    aotf_dll_available: bool
    camera_sdk_available: bool

    def summary(self) -> str:
        parts = [
            f"serial {'ok' if self.serial_available else 'missing'}",
            f"nidaqmx {'ok' if self.nidaqmx_available else 'missing'}",
            f"AOTF DLL {'ok' if self.aotf_dll_available else 'missing'}",
            f"camera SDK {'ok' if self.camera_sdk_available else 'missing'}",
        ]
        return ", ".join(parts)


@dataclass
class TeledyneSourceModel:
    config_path: Path
    calibration_path: Path
    tree: ET.ElementTree
    root: ET.Element
    lasers: dict[str, TeledyneLaserConfig]
    camera: TeledyneCameraConfig | None
    focus_lock: TeledyneFocusLockConfig
    daq: TeledyneDaqConfig
    calibration: TeledyneCalibrationTable
    dirty: bool = False

    @classmethod
    def load(cls, config_path: Path, calibration_path: Path) -> "TeledyneSourceModel":
        tree = ET.parse(config_path)
        root = tree.getroot()
        calibration = _load_calibration_table(calibration_path)
        lasers = _load_lasers(root, calibration)
        camera = _load_camera(root)
        focus_lock = _load_focus_lock(root)
        daq = _load_daq(root)
        return cls(
            config_path=config_path,
            calibration_path=calibration_path,
            tree=tree,
            root=root,
            lasers=lasers,
            camera=camera,
            focus_lock=focus_lock,
            daq=daq,
            calibration=calibration,
        )

    def save(self) -> None:
        ET.indent(self.tree, space="    ")
        self.tree.write(self.config_path, encoding="utf-8", xml_declaration=True)
        self.dirty = False

    def sync_unified_settings(self, settings: "UnifiedSettings") -> None:
        path_plan = build_acquisition_path_plan(settings, preview_only=True)
        camera_node = self._ensure_camera_node()
        camera_id = camera_node.get("id", "UnifiedSMLM") or "UnifiedSMLM"
        _set_text(camera_node, "recordPath", str(path_plan.save_dir))
        _set_text(camera_node, "exposeTime", f"{settings.acquisition.exposure_ms:.1f}")
        _set_text(camera_node, "triggerIn", "1" if settings.acquisition.trigger_mode == "External" else "0")
        _set_text(camera_node, "triggerOut", "1" if settings.acquisition.trigger_mode == "External" else "0")
        _set_text(camera_node, "unifiedTriggerMode", settings.acquisition.trigger_mode)
        _set_text(camera_node, "unifiedRoiPreset", settings.acquisition.roi_name)
        _set_text(camera_node, "unifiedSavingFormat", settings.acquisition.saving_format)
        self.camera = TeledyneCameraConfig(
            camera_id=camera_id,
            record_path=str(path_plan.save_dir),
            expose_time_ms=settings.acquisition.exposure_ms,
            trigger_in=1 if settings.acquisition.trigger_mode == "External" else 0,
            trigger_out=1 if settings.acquisition.trigger_mode == "External" else 0,
            unified_trigger_mode=settings.acquisition.trigger_mode,
            unified_roi_preset=settings.acquisition.roi_name,
            unified_saving_format=settings.acquisition.saving_format,
        )

        laser = self.lasers.get("647")
        laser_node = self._find_laser_node("647")
        if laser is not None and laser_node is not None:
            laser.is_enable = settings.illumination.channel_642_enabled
            laser.unified_target_power = settings.illumination.laser_642_setpoint
            laser.unified_aotf_target = settings.illumination.aotf_642_setpoint
            laser.unified_modulation_mode = settings.illumination.modulation_mode
            laser.unified_safe_shutdown = settings.illumination.safe_shutdown_setpoint
            _set_text(laser_node, "isEnable", _bool_text(laser.is_enable))
            _set_text(laser_node, "unifiedTargetPower", f"{laser.unified_target_power:.1f}")
            _set_text(laser_node, "unifiedAotfTarget", f"{laser.unified_aotf_target:.2f}")
            _set_text(laser_node, "unifiedModulationMode", laser.unified_modulation_mode)
            _set_text(laser_node, "unifiedSafeShutdown", f"{laser.unified_safe_shutdown:.1f}")

        focus_lock_node = self._ensure_focus_lock_node()
        self.focus_lock.unified_mode = settings.focus_lock.mode
        self.focus_lock.unified_locked = settings.focus_lock.locked
        self.focus_lock.unified_jump_offset_um = settings.focus_lock.jump_offset_um
        self.focus_lock.unified_depth_count = settings.focus_lock.depth_count
        self.focus_lock.unified_frames_per_depth_per_round = settings.focus_lock.frames_per_depth_per_round
        _set_text(focus_lock_node, "unifiedMode", self.focus_lock.unified_mode)
        _set_text(focus_lock_node, "unifiedLocked", _bool_text(self.focus_lock.unified_locked))
        _set_text(focus_lock_node, "unifiedJumpOffsetUm", f"{self.focus_lock.unified_jump_offset_um:.2f}")
        _set_text(focus_lock_node, "unifiedDepthCount", str(self.focus_lock.unified_depth_count))
        _set_text(
            focus_lock_node,
            "unifiedFramesPerDepthPerRound",
            str(self.focus_lock.unified_frames_per_depth_per_round),
        )
        self.dirty = True

    def _find_laser_node(self, laser_id: str) -> ET.Element | None:
        for laser_node in self.root.findall("./lasers/laser"):
            node_id = laser_node.get("id", "")
            node_name = _text(laser_node, "name", "")
            if node_id == laser_id or node_name == laser_id:
                return laser_node
        return None

    def _ensure_camera_node(self) -> ET.Element:
        cameras = self.root.find("cameras")
        if cameras is None:
            cameras = ET.SubElement(self.root, "cameras")
        for camera in cameras.findall("camera"):
            return camera
        return ET.SubElement(cameras, "camera", {"id": "UnifiedSMLM"})

    def _ensure_focus_lock_node(self) -> ET.Element:
        node = self.root.find("focusLock")
        if node is None:
            node = ET.SubElement(self.root, "focusLock")
        return node


def detect_runtime_capabilities(bundle_root: Path) -> TeledyneRuntimeCapabilities:
    aotf_dll_path = bundle_root / "AotfLibrary.dll"
    camera_sdk_path = bundle_root / "thorlabs_tsi_camera_sdk.dll"
    return TeledyneRuntimeCapabilities(
        bundle_root=bundle_root,
        aotf_dll_path=aotf_dll_path,
        camera_sdk_path=camera_sdk_path,
        serial_available=serial is not None,
        nidaqmx_available=nidaqmx is not None,
        aotf_dll_available=aotf_dll_path.exists(),
        camera_sdk_available=camera_sdk_path.exists(),
    )


class AotfDllAdapter:
    def __init__(self, bundle_root: Path) -> None:
        self.bundle_root = bundle_root
        self.dll_path = bundle_root / "AotfLibrary.dll"
        self._dll = None
        self._controller = None
        self._dll_dir_handle = None

    def open(self) -> None:
        if self._controller is not None:
            return
        if not self.dll_path.exists():
            raise FileNotFoundError(self.dll_path)
        if hasattr(os, "add_dll_directory"):
            self._dll_dir_handle = os.add_dll_directory(str(self.bundle_root))
        self._dll = ctypes.WinDLL(str(self.dll_path))
        self._dll.AotfOpen.argtypes = [ctypes.c_int]
        self._dll.AotfOpen.restype = ctypes.c_void_p
        self._dll.AotfClose.argtypes = [ctypes.c_void_p]
        self._dll.AotfClose.restype = ctypes.c_bool
        self._dll.AotfWrite.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p]
        self._dll.AotfWrite.restype = ctypes.c_bool
        self._dll.AotfRead.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint),
        ]
        self._dll.AotfRead.restype = ctypes.c_bool
        self._dll.AotfIsReadDataAvailable.argtypes = [ctypes.c_void_p]
        self._dll.AotfIsReadDataAvailable.restype = ctypes.c_bool
        self._controller = self._dll.AotfOpen(0)
        if not self._controller:
            raise RuntimeError("AotfOpen failed")

    def close(self) -> None:
        if self._controller and self._dll:
            self.send_command("dds Reset\r")
            self.read_response()
            self._dll.AotfClose(self._controller)
        self._controller = None
        self._dll = None
        if self._dll_dir_handle is not None:
            self._dll_dir_handle.close()
            self._dll_dir_handle = None

    def send_command(self, command: str) -> None:
        self.open()
        payload = command.encode("latin-1")
        buffer = ctypes.create_string_buffer(payload)
        ok = self._dll.AotfWrite(self._controller, len(payload), buffer)
        if not ok:
            raise RuntimeError(f"AotfWrite failed for command: {command!r}")

    def read_response(self, timeout_ms: int = 50) -> str:
        self.open()
        deadline = time.time() + (timeout_ms / 1000.0)
        response = bytearray()
        while time.time() < deadline:
            if not self._dll.AotfIsReadDataAvailable(self._controller):
                time.sleep(0.002)
                continue
            one_byte = ctypes.create_string_buffer(1)
            bytes_read = ctypes.c_uint(0)
            ok = self._dll.AotfRead(self._controller, 1, one_byte, ctypes.byref(bytes_read))
            if not ok:
                raise RuntimeError("AotfRead failed")
            if bytes_read.value:
                response.extend(one_byte.raw[: bytes_read.value])
        return response.decode("latin-1", errors="replace")

    def safe_shutdown(self) -> None:
        self.send_command("dau en\r")
        self.read_response()
        self.send_command("dau gain * 255\r")
        self.read_response()


class LaserSerialAdapter:
    def __init__(self, laser: TeledyneLaserConfig) -> None:
        self.laser = laser
        self._port = None

    def open(self) -> None:
        if serial is None:
            raise RuntimeError("pyserial is not installed")
        if self._port is not None and self._port.is_open:
            return
        baudrate = 115200 if self.laser.model == "Coherent_OBIS" else 9600
        self._port = serial.Serial(
            port=self.laser.serial_port,
            baudrate=baudrate,
            timeout=0.2,
            write_timeout=0.2,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
        )

    def close(self) -> None:
        if self._port is not None:
            self._port.reset_input_buffer()
            self._port.reset_output_buffer()
            self._port.close()
        self._port = None

    def send_command(self, command: str) -> None:
        self.open()
        self._port.write(command.encode("latin-1"))
        self._port.flush()

    def read_response(self, timeout_s: float = 0.25) -> str:
        self.open()
        deadline = time.time() + timeout_s
        chunks: list[bytes] = []
        while time.time() < deadline:
            chunk = self._port.read_all()
            if chunk:
                chunks.append(chunk)
                text = b"".join(chunks).decode("latin-1", errors="replace")
                if self.laser.model == "Coherent_OBIS" and text.endswith("\n"):
                    break
                if self.laser.model == "MPB" and text.replace(" ", "").endswith("D>"):
                    break
            time.sleep(0.01)
        return b"".join(chunks).decode("latin-1", errors="replace")

    def set_enabled(self, enabled: bool) -> None:
        if self.laser.model == "Coherent_OBIS":
            self.send_command("SOUR:AM:STAT ON\r" if enabled else "SOUR:AM:STAT OFF\r")
        else:
            self.send_command("setldenable 1\r" if enabled else "setldenable 0\r")
        self.read_response()

    def set_power_mw(self, power_mw: float) -> None:
        if self.laser.model == "Coherent_OBIS":
            self.send_command(f"SOUR:POW:LEV:IMM:AMPL {power_mw / 1000.0:.6f}\r")
        else:
            self.send_command(f"setpower 0 {int(round(power_mw))}\r")
        self.read_response()

    def set_mode(self, mode: str) -> None:
        if self.laser.model == "Coherent_OBIS":
            if mode.upper() == "APC":
                self.send_command("SOURce:AM:INTernal CWP\r")
            elif mode.upper() == "ACC":
                self.send_command("SOURce:AM:INTernal CWC\r")
            else:
                self.send_command("SOURce:AM:EXTernal DIGital\r")
        else:
            self.send_command("powerenable 1\r" if mode.upper() == "APC" else "powerenable 0\r")
        self.read_response()


class NIDaqAdapter:
    def __init__(self, config: TeledyneDaqConfig) -> None:
        self.config = config
        self._aotf_mod_tasks: dict[int, object] = {}
        self._aotf_blank_task = None
        self._laser_405_dig_task = None
        self._laser_405_mod_task = None

    def open(self) -> None:
        if nidaqmx is None or LineGrouping is None:
            raise RuntimeError("nidaqmx is not installed")
        if self._aotf_mod_tasks:
            return

        for chan, physical_chan in self.config.chan_out_aotf_mod.items():
            if not physical_chan:
                continue
            task = nidaqmx.Task()
            task.ao_channels.add_ao_voltage_chan(physical_chan, min_val=0.0, max_val=5.0)
            task.start()
            task.write(0.0)
            self._aotf_mod_tasks[chan] = task

        if self.config.chan_out_aotf_blank:
            self._aotf_blank_task = nidaqmx.Task()
            self._aotf_blank_task.do_channels.add_do_chan(
                self.config.chan_out_aotf_blank,
                line_grouping=LineGrouping.CHAN_FOR_ALL_LINES,
            )
            self._aotf_blank_task.start()
            self._aotf_blank_task.write(False)

        if self.config.chan_out_405_laser_dig:
            self._laser_405_dig_task = nidaqmx.Task()
            self._laser_405_dig_task.do_channels.add_do_chan(
                self.config.chan_out_405_laser_dig,
                line_grouping=LineGrouping.CHAN_FOR_ALL_LINES,
            )
            self._laser_405_dig_task.start()
            self._laser_405_dig_task.write(False)

        if self.config.chan_out_405_laser_mod:
            self._laser_405_mod_task = nidaqmx.Task()
            self._laser_405_mod_task.ao_channels.add_ao_voltage_chan(
                self.config.chan_out_405_laser_mod,
                min_val=0.0,
                max_val=5.0,
            )
            self._laser_405_mod_task.start()
            self._laser_405_mod_task.write(0.0)

    def close(self) -> None:
        for task in self._aotf_mod_tasks.values():
            task.close()
        self._aotf_mod_tasks.clear()
        for task in [self._aotf_blank_task, self._laser_405_dig_task, self._laser_405_mod_task]:
            if task is not None:
                task.close()
        self._aotf_blank_task = None
        self._laser_405_dig_task = None
        self._laser_405_mod_task = None

    def set_aotf_blank(self, state: bool) -> None:
        self.open()
        if self._aotf_blank_task is not None:
            self._aotf_blank_task.write(bool(state))

    def set_aotf_analog(self, channel: int, value: float) -> None:
        self.open()
        task = self._aotf_mod_tasks.get(channel)
        if task is not None:
            task.write(float(value))

    def set_405_laser_state(self, state: bool) -> None:
        self.open()
        if self._laser_405_dig_task is not None:
            self._laser_405_dig_task.write(bool(state))

    def set_405_laser_analog(self, value: float) -> None:
        self.open()
        if self._laser_405_mod_task is not None:
            self._laser_405_mod_task.write(float(value))


class TeledyneSourceRuntime:
    def __init__(self, model: TeledyneSourceModel, bundle_root: Path) -> None:
        self.model = model
        self.bundle_root = bundle_root
        self.capabilities = detect_runtime_capabilities(bundle_root)
        self.aotf = AotfDllAdapter(bundle_root)
        self.daq = NIDaqAdapter(model.daq)

    def close(self) -> None:
        self.aotf.close()
        self.daq.close()

    def prepare_aotf(self) -> None:
        self.aotf.open()
        self.aotf.send_command("dau gain * 72\r")
        self.aotf.read_response()
        self.aotf.send_command("dau dis\r")
        self.aotf.read_response()

    def set_laser_output(self, laser_id: str, *, enabled: bool, power_mw: float | None = None) -> None:
        laser = self.model.lasers[laser_id]
        adapter = LaserSerialAdapter(laser)
        try:
            if enabled:
                adapter.open()
                adapter.set_enabled(True)
                adapter.set_mode(laser.mode)
                if power_mw is not None:
                    adapter.set_power_mw(power_mw)
            else:
                if power_mw is not None:
                    try:
                        adapter.open()
                        adapter.set_power_mw(power_mw)
                    except Exception:
                        pass
                adapter.open()
                adapter.set_enabled(False)
        finally:
            adapter.close()

    def set_independent_channel_enabled(self, laser_id: str, enabled: bool) -> None:
        laser = self.model.lasers[laser_id]
        if laser.controller != "AOTF_GH":
            if laser.controller == "NI" and laser_id == "405":
                self.daq.set_405_laser_state(enabled)
            return
        self.aotf.open()
        freq_value = laser.ao_freq_hz if enabled else 0.0
        self.aotf.send_command(f"dds f {laser.ao_chan} {freq_value:.6f}\r")
        self.aotf.read_response()

    def disable_all_aotf_outputs(self) -> None:
        self.aotf.open()
        self.aotf.send_command("DDS FSK * 0\r")
        self.aotf.read_response()
        self.aotf.send_command("dds f * 0\r")
        self.aotf.read_response()
        self.daq.open()
        self.daq.set_aotf_blank(False)
        self.daq.set_aotf_analog(0, 0.0)
        self.daq.set_aotf_analog(1, 0.0)
        self.daq.set_aotf_analog(2, 0.0)

    def apply_illumination_state(
        self,
        *,
        laser_id: str,
        laser_enabled: bool,
        laser_power_mw: float,
        aotf_enabled: bool,
        aotf_throughput_percent: float,
        modulation_mode: str,
    ) -> None:
        if laser_enabled:
            self.set_laser_output(laser_id, enabled=True, power_mw=laser_power_mw)
        else:
            self.disable_all_aotf_outputs()
            self.set_laser_output(laser_id, enabled=False)
            return

        self.prepare_aotf()

        if not aotf_enabled:
            self.disable_all_aotf_outputs()
            return

        channel_percents = {
            "488": 0.0,
            "560": 0.0,
            "647": 0.0,
        }
        channel_percents[laser_id] = float(aotf_throughput_percent)
        self.apply_modulation_mode(modulation_mode, channel_percents, primary_channel=laser_id)
        if modulation_mode == "Independent mode":
            self.set_independent_channel_enabled(laser_id, True)

    def apply_modulation_mode(
        self,
        mode: str,
        channel_percents: dict[str, float],
        *,
        primary_channel: str = "647",
    ) -> None:
        self.aotf.open()
        self.daq.open()
        if mode == "Independent mode":
            self._apply_independent_mode(channel_percents)
        elif mode == "one-chan FSK mode":
            self._apply_one_channel_fsk(channel_percents, primary_channel)
        elif mode == "two-chan FSK mode":
            self._apply_multi_channel_fsk(channel_percents, ["647", "560"])
        elif mode == "three-chan FSK mode":
            self._apply_multi_channel_fsk(channel_percents, ["647", "560", "488"])
        else:
            raise ValueError(f"Unsupported modulation mode: {mode}")

    def safe_shutdown(self) -> None:
        self.daq.set_aotf_blank(False)
        self.daq.set_aotf_analog(0, 0.0)
        self.daq.set_aotf_analog(1, 0.0)
        self.daq.set_aotf_analog(2, 0.0)
        self.daq.set_405_laser_state(False)
        self.daq.set_405_laser_analog(0.0)
        self.aotf.safe_shutdown()
        self.close()

    def _apply_independent_mode(self, channel_percents: dict[str, float]) -> None:
        self.aotf.send_command("DDS FSK * 0\r")
        self.aotf.read_response()
        self.aotf.send_command("dds f * 0\r")
        self.aotf.read_response()
        # The original TeledyneCam keeps the AOTF blank line asserted while
        # independent-mode channels are enabled via their per-channel DDS frequency.
        self.daq.set_aotf_blank(True)
        for laser_id in ["488", "560", "647"]:
            laser = self.model.lasers.get(laser_id)
            if laser is None:
                continue
            self.aotf.send_command(f"dds a {laser.ao_chan} {laser.ao_pwr}\r")
            self.aotf.read_response()
            analog_value = self.model.calibration.analog_value_for_percent(
                laser_id,
                float(channel_percents.get(laser_id, 0.0)),
            )
            self.daq.set_aotf_analog(laser.ao_chan, analog_value)

    def _apply_one_channel_fsk(self, channel_percents: dict[str, float], primary_channel: str) -> None:
        laser = self.model.lasers[primary_channel]
        analog_value = self.model.calibration.analog_value_for_percent(
            primary_channel,
            float(channel_percents.get(primary_channel, 0.0)),
        )
        self.aotf.send_command(f"dds a 0 {laser.ao_pwr}\r")
        self.aotf.read_response()
        self.aotf.send_command(
            f"dds f 0 {laser.ao_freq_hz:.6f} 0 {laser.ao_freq_hz:.6f} 0\r"
        )
        self.aotf.read_response()
        self.aotf.send_command("dds fsk 0 5\r")
        self.aotf.read_response()
        self.daq.set_aotf_blank(True)
        self.daq.set_aotf_analog(0, analog_value)
        self.daq.set_aotf_analog(1, 0.0)
        self.daq.set_aotf_analog(2, 0.0)

    def _apply_multi_channel_fsk(self, channel_percents: dict[str, float], ordered_ids: list[str]) -> None:
        for fsk_channel, laser_id in enumerate(ordered_ids):
            laser = self.model.lasers[laser_id]
            self.aotf.send_command(f"dds a {fsk_channel} {laser.ao_pwr}\r")
            self.aotf.read_response()
            self.aotf.send_command(
                f"dds f {fsk_channel} {laser.ao_freq_hz:.6f} 0 {laser.ao_freq_hz:.6f} 0\r"
            )
            self.aotf.read_response()
            self.aotf.send_command(f"dds fsk {fsk_channel} 5\r")
            self.aotf.read_response()
            analog_value = self.model.calibration.analog_value_for_percent(
                laser_id,
                float(channel_percents.get(laser_id, 0.0)),
            )
            self.daq.set_aotf_analog(fsk_channel, analog_value)

        for zero_channel in range(len(ordered_ids), 3):
            self.daq.set_aotf_analog(zero_channel, 0.0)
        self.daq.set_aotf_blank(True)


def _load_calibration_table(calibration_path: Path) -> TeledyneCalibrationTable:
    if not calibration_path.exists():
        return TeledyneCalibrationTable()
    with calibration_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        rows = list(reader)
    if not rows:
        return TeledyneCalibrationTable()
    headers = [header.strip() for header in rows[0] if header.strip()]
    values: dict[str, list[float]] = {header: [] for header in headers}
    for row in rows[1:]:
        for index, header in enumerate(headers):
            if index >= len(row):
                continue
            values[header].append(_to_float(row[index], 0.0))
    return TeledyneCalibrationTable(values=values)


def _load_lasers(root: ET.Element, calibration: TeledyneCalibrationTable) -> dict[str, TeledyneLaserConfig]:
    lasers: dict[str, TeledyneLaserConfig] = {}
    for laser_node in root.findall("./lasers/laser"):
        laser_id = laser_node.get("id", "") or _text(laser_node, "name", "")
        lasers[laser_id] = TeledyneLaserConfig(
            laser_id=laser_id,
            name=_text(laser_node, "name", laser_id),
            color=_text(laser_node, "color", "#ffffff"),
            model=_text(laser_node, "model", ""),
            mode=_text(laser_node, "mode", ""),
            trigger_enable=_text(laser_node, "triggerEnable", "0") == "1",
            is_enable=_text(laser_node, "isEnable", "0") == "1",
            min_power_mw=_to_float(_text(laser_node, "minPower", "0")),
            max_power_mw=_to_float(_text(laser_node, "maxPower", "0")),
            min_current_ma=_to_float(_text(laser_node, "minCurrent", "0")),
            max_current_ma=_to_float(_text(laser_node, "maxCurrent", "0")),
            serial_port=_text(laser_node, "serialPort", ""),
            shg_temp_c=_to_int(_text(laser_node, "shgTemp", "0")),
            controller=_text(laser_node, "controller", ""),
            ao_port=_text(laser_node, "AO_port", ""),
            ao_freq_hz=_to_float(_text(laser_node, "AO_freq", "0")),
            ao_chan=_to_int(_text(laser_node, "AO_chan", "0")),
            ao_pwr=_to_int(_text(laser_node, "AO_pwr", "0")),
            calibration_values=list(calibration.values.get(laser_id, [])),
            unified_target_power=_to_float(_text(laser_node, "unifiedTargetPower", ""), 0.0)
            if _text(laser_node, "unifiedTargetPower", "")
            else None,
            unified_aotf_target=_to_float(_text(laser_node, "unifiedAotfTarget", ""), 0.0)
            if _text(laser_node, "unifiedAotfTarget", "")
            else None,
            unified_modulation_mode=_text(laser_node, "unifiedModulationMode", ""),
            unified_safe_shutdown=_to_float(_text(laser_node, "unifiedSafeShutdown", ""), 0.0)
            if _text(laser_node, "unifiedSafeShutdown", "")
            else None,
        )
    return lasers


def _load_camera(root: ET.Element) -> TeledyneCameraConfig | None:
    cameras = root.find("cameras")
    if cameras is None:
        return None
    for camera_node in cameras.findall("camera"):
        camera_id = camera_node.get("id", "UnifiedSMLM") or "UnifiedSMLM"
        return TeledyneCameraConfig(
            camera_id=camera_id,
            record_path=_text(camera_node, "recordPath", ""),
            expose_time_ms=_to_float(_text(camera_node, "exposeTime", "0")),
            trigger_in=_to_int(_text(camera_node, "triggerIn", "0")),
            trigger_out=_to_int(_text(camera_node, "triggerOut", "0")),
            unified_trigger_mode=_text(camera_node, "unifiedTriggerMode", ""),
            unified_roi_preset=_text(camera_node, "unifiedRoiPreset", ""),
            unified_saving_format=_text(camera_node, "unifiedSavingFormat", ""),
        )
    return None


def _load_focus_lock(root: ET.Element) -> TeledyneFocusLockConfig:
    node = root.find("focusLock")
    raw_values: dict[str, str] = {}
    if node is not None:
        for child in list(node):
            raw_values[child.tag] = (child.text or "").strip()
    return TeledyneFocusLockConfig(
        raw_values=raw_values,
        unified_mode=raw_values.get("unifiedMode", ""),
        unified_locked=raw_values.get("unifiedLocked", "0") == "1",
        unified_jump_offset_um=_to_float(raw_values.get("unifiedJumpOffsetUm", "0"), 0.0),
        unified_depth_count=_to_int(raw_values.get("unifiedDepthCount", "0"), 0),
        unified_frames_per_depth_per_round=_to_int(raw_values.get("unifiedFramesPerDepthPerRound", "0"), 0),
    )


def _load_daq(root: ET.Element) -> TeledyneDaqConfig:
    node = root.find("NI-DAQmx")
    if node is None:
        return TeledyneDaqConfig()
    return TeledyneDaqConfig(
        device_name=_text(node, "deviceName", ""),
        chan_out_aotf_blank=_text(node, "chanOut_aotfBlank", ""),
        chan_out_aotf_mod={
            0: _text(node, "chanOut_aotfMod_1", ""),
            1: _text(node, "chanOut_aotfMod_2", ""),
            2: _text(node, "chanOut_aotfMod_3", ""),
        },
        chan_out_405_laser_dig=_text(node, "chanOut_405LaserDig", ""),
        chan_out_405_laser_mod=_text(node, "chanOut_405LaserMod", ""),
        cam_trigger_chan=_text(node, "camTriggerChan", ""),
        cam_expose_chan=_text(node, "camExposeChan", ""),
        inter_tans_chan=_text(node, "interTansChan", ""),
        inter_start_chan=_text(node, "interStartChan", ""),
        expose_laser_chan=_text(node, "exposeLaserChan", ""),
        focus_lock_laser_chan=_text(node, "focusLockLaserChan", ""),
        focus_lock_cam_xy_chan=_text(node, "focusLockCamXYchan", ""),
        focus_lock_cam_z_chan=_text(node, "focusLockCamZchan", ""),
        gh_aotf_fsk_blank=_text(node, "GH_AOTF_FSK_BLANK", ""),
        laser_digital_chan=_text(node, "laserDigitalChan", ""),
    )
