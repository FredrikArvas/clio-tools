"""motion_delta.py — Hitta anomali-frames via frame-till-frame-differens.

Logik:
- Ladda varje frame som gråskala numpy-array
- Beräkna absolut differens mot föregående frame
- En "spike" (hög max-delta i en region) indikerar att något nytt dök upp
- Klustrera konsekutiva anomali-frames till "events" för vidare analys

Kräver inga externa API-anrop — allt lokalt med PIL + numpy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image


@dataclass
class DeltaResult:
    frame_index: int
    frame_path: str
    mean_delta: float      # snittdiff hela bilden (0–255)
    peak_delta: float      # max pixelförändring i någon 8x8-cell
    is_anomaly: bool
    anomaly_region: tuple[int, int] | None = None  # (grid_x, grid_y) för starkaste delta


@dataclass
class AnomalyEvent:
    """Grupp av konsekutiva anomali-frames — troligen ett och samma fenomen."""
    event_id: int
    frames: list[DeltaResult] = field(default_factory=list)

    @property
    def start_frame(self) -> int:
        return self.frames[0].frame_index if self.frames else 0

    @property
    def end_frame(self) -> int:
        return self.frames[-1].frame_index if self.frames else 0

    @property
    def peak(self) -> float:
        return max(f.peak_delta for f in self.frames) if self.frames else 0.0

    @property
    def frame_paths(self) -> list[str]:
        return [f.frame_path for f in self.frames]


def _load_gray(path: str) -> np.ndarray:
    return np.array(Image.open(path).convert("L"), dtype=np.float32)


def _grid_peak(diff: np.ndarray, cell_size: int = 8) -> tuple[float, tuple[int, int]]:
    """Dela upp diff-matrisen i celler, returnera max cell-medelvärde och dess position.

    Cellbaserad analys är mer robust mot enstaka brus-pixlar än absolut max.
    """
    h, w = diff.shape
    best_val = 0.0
    best_pos = (0, 0)
    rows = h // cell_size
    cols = w // cell_size
    for r in range(rows):
        for c in range(cols):
            cell = diff[r*cell_size:(r+1)*cell_size, c*cell_size:(c+1)*cell_size]
            val = float(cell.mean())
            if val > best_val:
                best_val = val
                best_pos = (c, r)
    return best_val, best_pos


def compute_deltas(
    frame_paths: list[str],
    peak_threshold: float = 12.0,
    cell_size: int = 8,
) -> list[DeltaResult]:
    """Beräkna frame-differenser för alla frames.

    peak_threshold: cell-medelvärde (0–255) över vilket en frame flaggas.
    Typvärden: 8=känslig (mycket brus), 12=balanserad, 20=konservativ.
    """
    results: list[DeltaResult] = []
    prev: np.ndarray | None = None

    for i, path in enumerate(frame_paths):
        curr = _load_gray(path)

        if prev is None:
            results.append(DeltaResult(
                frame_index=i + 1,
                frame_path=path,
                mean_delta=0.0,
                peak_delta=0.0,
                is_anomaly=False,
            ))
            prev = curr
            continue

        diff = np.abs(curr - prev)
        mean_d = float(diff.mean())
        peak_d, region = _grid_peak(diff, cell_size)

        results.append(DeltaResult(
            frame_index=i + 1,
            frame_path=path,
            mean_delta=mean_d,
            peak_delta=peak_d,
            is_anomaly=peak_d >= peak_threshold,
            anomaly_region=region if peak_d >= peak_threshold else None,
        ))
        prev = curr

    return results


def cluster_events(
    deltas: list[DeltaResult],
    gap_frames: int = 4,
    min_frames: int = 1,
) -> list[AnomalyEvent]:
    """Klustrera anomali-frames till events.

    gap_frames: max antal normala frames mellan anomalier i samma event.
    min_frames: minsta antal anomali-frames för att bilda ett event.
    """
    events: list[AnomalyEvent] = []
    current: list[DeltaResult] = []
    gap = 0

    for delta in deltas:
        if delta.is_anomaly:
            current.append(delta)
            gap = 0
        elif current:
            gap += 1
            if gap <= gap_frames:
                # Inkludera gap-frames i eventet för kontext
                current.append(delta)
            else:
                if sum(1 for f in current if f.is_anomaly) >= min_frames:
                    events.append(AnomalyEvent(event_id=len(events) + 1, frames=current))
                current = []
                gap = 0

    if current and sum(1 for f in current if f.is_anomaly) >= min_frames:
        events.append(AnomalyEvent(event_id=len(events) + 1, frames=current))

    return events


def print_delta_summary(deltas: list[DeltaResult], events: list[AnomalyEvent]) -> None:
    anomaly_count = sum(1 for d in deltas if d.is_anomaly)
    print(f"  Frames analyserade : {len(deltas)}")
    print(f"  Anomali-frames     : {anomaly_count}")
    print(f"  Events klustrade   : {len(events)}")
    if events:
        print()
        print(f"  {'Event':<6} {'Frames':<8} {'Peak-delta':<12} {'Frame-span'}")
        print(f"  {'-'*6} {'-'*8} {'-'*12} {'-'*20}")
        for ev in events:
            span = f"{ev.start_frame}–{ev.end_frame}"
            print(f"  {ev.event_id:<6} {len(ev.frames):<8} {ev.peak:<12.1f} {span}")
    print()
