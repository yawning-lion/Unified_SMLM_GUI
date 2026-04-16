from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import UnifiedSettings


INVALID_PATH_CHARS = set('<>:"/\\|?*')


@dataclass(frozen=True)
class AcquisitionPathPlan:
    session_folder_name: str
    session_dir: Path
    save_dir: Path
    base_name: str
    dataset_name: str | None
    dataset_path: Path | None
    output_path: Path
    mode_dir_name: str
    file_prefix: str


def _sanitize_component(value: str, fallback: str, *, allow_empty: bool = False) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "" if allow_empty else fallback

    normalized = "".join("_" if char in INVALID_PATH_CHARS or ord(char) < 32 else char for char in raw)
    normalized = normalized.strip(" .")
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    if not normalized:
        return "" if allow_empty else fallback
    return normalized


def preset_storage_profile(preset_name: str) -> tuple[str, str]:
    mapping = {
        "Search / Focus": ("roi_preview", "roi"),
        "ROI Preview": ("roi_preview", "roi"),
        "Widefield Test": ("widefield", "wf"),
        "STORM 2D": ("sr_smlm", "sr"),
        "Whole-Cell Z Scan": ("whole_cell_z", "zscan"),
    }
    return mapping.get(preset_name, ("capture", "capture"))


def build_session_folder_name(prefix: str, session_timestamp_prefix: str, sample_name: str) -> str:
    parts: list[str] = []
    normalized_prefix = _sanitize_component(prefix, "", allow_empty=True)
    normalized_session = _sanitize_component(session_timestamp_prefix, "session")
    normalized_sample = _sanitize_component(sample_name, "", allow_empty=True)
    if normalized_prefix:
        parts.append(normalized_prefix)
    parts.append(normalized_session)
    if normalized_sample:
        parts.append(normalized_sample)
    return "_".join(parts)


def build_acquisition_path_plan(
    settings: UnifiedSettings,
    *,
    timestamp: datetime | None = None,
    preview_only: bool = False,
) -> AcquisitionPathPlan:
    acquisition = settings.acquisition
    mode_dir_name, file_prefix = preset_storage_profile(settings.state.active_preset)
    session_folder_name = build_session_folder_name(
        acquisition.save_prefix,
        settings.state.session_timestamp_prefix,
        acquisition.sample_name,
    )
    session_dir = Path(acquisition.save_root).expanduser() / session_folder_name
    save_dir = session_dir / mode_dir_name
    timestamp_text = "<timestamp>" if preview_only else (timestamp or datetime.now()).strftime("%Y%m%d_%H%M%S")
    base_name = f"{file_prefix}_{timestamp_text}"
    normalized_format = acquisition.saving_format.strip().lower()
    keep_dataset = not (
        normalized_format == "image stack file"
        and settings.state.active_preset == "Widefield Test"
    )

    if normalized_format == "image stack file":
        dataset_name = f"{base_name}_mda"
        dataset_path = save_dir / dataset_name if keep_dataset else None
        if not keep_dataset:
            dataset_name = None
        output_path = save_dir / f"{base_name}.tif"
    else:
        dataset_name = None
        dataset_path = None
        output_path = save_dir / base_name

    return AcquisitionPathPlan(
        session_folder_name=session_folder_name,
        session_dir=session_dir,
        save_dir=save_dir,
        base_name=base_name,
        dataset_name=dataset_name,
        dataset_path=dataset_path,
        output_path=output_path,
        mode_dir_name=mode_dir_name,
        file_prefix=file_prefix,
    )
