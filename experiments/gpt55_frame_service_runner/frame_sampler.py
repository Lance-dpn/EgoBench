"""Uniform video frame sampler for the GPT frame-service experiment."""

from __future__ import annotations

import base64
import json
import math
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SampledFrame:
    frame_id: str
    timestamp: float
    path: Path


def _run_command(cmd: list[str]) -> str:
    result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return result.stdout.strip()


def video_duration_seconds(video_path: Path) -> float:
    output = _run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
    )
    return max(0.0, float(output or 0.0))


def frame_timestamps(duration: float, fps: float, max_frames: int = 0) -> list[float]:
    if duration <= 0 or fps <= 0:
        return []
    step = 1.0 / fps
    count = max(1, int(math.ceil(duration * fps)))
    timestamps = [min(idx * step, max(0.0, duration - 0.001)) for idx in range(count)]
    if max_frames and len(timestamps) > max_frames:
        if max_frames == 1:
            return [timestamps[len(timestamps) // 2]]
        last = len(timestamps) - 1
        indexes = [round(i * last / (max_frames - 1)) for i in range(max_frames)]
        return [timestamps[idx] for idx in indexes]
    return timestamps


def _cache_metadata_path(output_dir: Path) -> Path:
    return output_dir / "frames_metadata.json"


def _read_cached_frames(output_dir: Path, cache_key: dict) -> list[SampledFrame] | None:
    metadata_path = _cache_metadata_path(output_dir)
    if not metadata_path.exists():
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if metadata.get("cache_key") != cache_key:
        return None
    frames = []
    for item in metadata.get("frames", []):
        path = output_dir / item["filename"]
        if not path.exists():
            return None
        frames.append(SampledFrame(frame_id=item["frame_id"], timestamp=float(item["timestamp"]), path=path))
    return frames


def sample_video_frames(
    video_path: str | Path,
    output_dir: str | Path,
    *,
    fps: float = 2.0,
    max_side: int = 1920,
    jpeg_quality: int = 3,
    max_frames: int = 0,
    rotation: str = "none",
    refresh: bool = False,
) -> list[SampledFrame]:
    video = Path(video_path).resolve()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    duration = video_duration_seconds(video)
    timestamps = frame_timestamps(duration, fps, max_frames=max_frames)
    stat = video.stat()
    cache_key = {
        "video_path": str(video),
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
        "duration": round(duration, 3),
        "fps": fps,
        "max_side": max_side,
        "jpeg_quality": jpeg_quality,
        "max_frames": max_frames,
        "rotation": rotation,
        "timestamps": [round(ts, 3) for ts in timestamps],
    }
    if not refresh:
        cached = _read_cached_frames(output, cache_key)
        if cached is not None:
            return cached

    frames: list[SampledFrame] = []
    filters = []
    if max_side > 0:
        filters.append(f"scale='if(gt(iw,ih),min({max_side},iw),-2)':'if(gt(iw,ih),-2,min({max_side},ih))'")
    if rotation == "clockwise":
        filters.append("transpose=1")
    elif rotation == "counterclockwise":
        filters.append("transpose=2")
    elif rotation == "180":
        filters.append("transpose=2,transpose=2")
    elif rotation != "none":
        raise ValueError(f"Unsupported frame rotation: {rotation}")
    video_filter = ",".join(filters)
    for idx, timestamp in enumerate(timestamps):
        frame_id = f"F{idx:03d}"
        filename = f"{frame_id}_t{timestamp:.2f}.jpg"
        path = output / filename
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            str(jpeg_quality),
            str(path),
        ]
        if video_filter:
            cmd[8:8] = ["-vf", video_filter]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        frames.append(SampledFrame(frame_id=frame_id, timestamp=round(timestamp, 3), path=path))

    metadata = {
        "cache_key": cache_key,
        "video": {
            "path": str(video),
            "filename": video.name,
            "duration": round(duration, 3),
        },
        "frames": [
            {"frame_id": item.frame_id, "timestamp": item.timestamp, "filename": item.path.name}
            for item in frames
        ],
    }
    _cache_metadata_path(output).write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return frames


def image_data_url(path: str | Path) -> str:
    frame_path = Path(path)
    data = base64.b64encode(frame_path.read_bytes()).decode("utf-8")
    return f"data:image/jpeg;base64,{data}"


def frame_metadata(frames: list[SampledFrame]) -> list[dict[str, object]]:
    return [
        {
            "frame_id": frame.frame_id,
            "timestamp": frame.timestamp,
            "path": os.fspath(frame.path),
        }
        for frame in frames
    ]
