from __future__ import annotations

import math

from .models import UnifiedSettings, ZScanPlan


def compute_z_step_from_scan_inputs(z_start_um: float, z_end_um: float, depth_count: int) -> float:
    if int(depth_count) <= 1:
        return 0.0
    return (float(z_end_um) - float(z_start_um)) / float(int(depth_count) - 1)


def depth_count_from_scan_inputs(z_start_um: float, z_end_um: float, step_um: float) -> int:
    span = float(z_end_um) - float(z_start_um)
    step = float(step_um)
    if abs(span) < 1.0e-9 or abs(step) < 1.0e-9:
        return 1
    return max(2, int(round(abs(span / step))) + 1)


def compute_z_step_um(settings: UnifiedSettings) -> float:
    focus_lock = settings.focus_lock
    return compute_z_step_from_scan_inputs(
        focus_lock.z_start_um,
        focus_lock.z_end_um,
        focus_lock.depth_count,
    )


def compute_z_scan_plan(settings: UnifiedSettings) -> ZScanPlan:
    focus_lock = settings.focus_lock
    acquisition = settings.acquisition

    frames_per_depth_target = max(1, acquisition.storm_total_frames)
    frames_per_depth_per_round = max(1, focus_lock.frames_per_depth_per_round)
    rounds = int(math.ceil(frames_per_depth_target / float(frames_per_depth_per_round)))
    full_rounds = frames_per_depth_target // frames_per_depth_per_round
    last_round_frames = frames_per_depth_target % frames_per_depth_per_round
    if last_round_frames == 0:
        last_round_frames = frames_per_depth_per_round

    total_frames_all_depths = frames_per_depth_target * max(1, focus_lock.depth_count)

    return ZScanPlan(
        depth_count=max(1, focus_lock.depth_count),
        step_um=compute_z_step_um(settings),
        rounds=max(1, rounds),
        full_rounds=full_rounds,
        last_round_frames_per_depth=last_round_frames,
        frames_per_depth_per_round=frames_per_depth_per_round,
        total_frames_per_depth_target=frames_per_depth_target,
        total_frames_all_depths=total_frames_all_depths,
        exposure_ms=max(0.1, acquisition.exposure_ms),
        trigger_mode=acquisition.trigger_mode,
    )


def build_round_frames_per_depth(plan: ZScanPlan) -> tuple[int, ...]:
    round_frames: list[int] = []
    if plan.full_rounds > 0:
        round_frames.extend([int(plan.frames_per_depth_per_round)] * int(plan.full_rounds))
    if plan.rounds > plan.full_rounds:
        round_frames.append(int(plan.last_round_frames_per_depth))
    return tuple(max(1, int(value)) for value in round_frames)
