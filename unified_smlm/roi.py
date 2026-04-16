from __future__ import annotations

from pathlib import Path
import struct

from .models import RoiRect


ROI_TYPE_NAMES = {
    1: "rectangle",
    2: "oval",
    3: "line",
    4: "polygon",
    5: "freehand",
    7: "traced",
    8: "polyline",
    10: "point",
}


def parse_imagej_roi(path: str | Path) -> RoiRect:
    roi_path = Path(path)
    data = roi_path.read_bytes()
    if len(data) < 16:
        raise ValueError(f"ROI file is too short: {roi_path}")
    if data[:4] != b"Iout":
        raise ValueError(f"Unsupported ROI format: {roi_path}")

    roi_type = data[6]
    top = struct.unpack(">H", data[8:10])[0]
    left = struct.unpack(">H", data[10:12])[0]
    bottom = struct.unpack(">H", data[12:14])[0]
    right = struct.unpack(">H", data[14:16])[0]

    return RoiRect(
        kind=ROI_TYPE_NAMES.get(roi_type, f"type-{roi_type}"),
        x=int(left),
        y=int(top),
        width=max(0, int(right - left)),
        height=max(0, int(bottom - top)),
    )
