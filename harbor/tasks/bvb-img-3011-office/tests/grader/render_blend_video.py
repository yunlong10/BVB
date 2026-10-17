#!/usr/bin/env python3
"""Render a .blend file from the scene camera (Blender background).

Used by the vision-level V-JEPA similarity metric. Prefer
``render_blend_to_frames`` (PNG sequence) so callers can score without an
ffmpeg encode step; ``render_blend_to_mp4`` is a convenience wrapper.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


# Runs inside Blender (--python). Kept as a string so the host launcher needs
# no Blender Python packages.
BLENDER_RENDER_SCRIPT = r"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy


def arg_after(name: str) -> str:
    argv = sys.argv
    if "--" not in argv:
        raise SystemExit("Missing script args after --")
    args = argv[argv.index("--") + 1 :]
    for index, value in enumerate(args):
        if value == name and index + 1 < len(args):
            return args[index + 1]
    raise SystemExit(f"Missing required argument: {name}")


def arg_after_optional(name: str, default=None):
    argv = sys.argv
    if "--" not in argv:
        return default
    args = argv[argv.index("--") + 1 :]
    for index, value in enumerate(args):
        if value == name and index + 1 < len(args):
            return args[index + 1]
    return default


frames_dir = Path(arg_after("--frames-dir"))
resolution = int(arg_after_optional("--resolution", "512") or "512")
# Sparse sample count across the full [frame_start, frame_end] range.
# Prefer this over rendering a long consecutive prefix.
num_samples_raw = arg_after_optional("--num-samples", "")
num_samples = int(num_samples_raw) if num_samples_raw else None
# Legacy: consecutive prefix length (used only when --num-samples is absent).
max_frames_raw = arg_after_optional("--max-frames", "")
max_frames = int(max_frames_raw) if max_frames_raw else None

scene = bpy.context.scene
if scene.camera is None:
    raise SystemExit("BVB_RENDER_ERROR no_camera")

# Prefer EEVEE (fast). Blender 4.2+ renamed it to BLENDER_EEVEE_NEXT.
engine_candidates = ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES")
for engine in engine_candidates:
    try:
        scene.render.engine = engine
        break
    except TypeError:
        continue

scene.render.resolution_x = resolution
scene.render.resolution_y = resolution
scene.render.resolution_percentage = 100
fps = max(1, int(round(float(scene.render.fps) / max(1.0, float(scene.render.fps_base)))))
scene.render.fps = fps
scene.render.fps_base = 1.0
scene.render.use_file_extension = True
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGB"

frame_start = int(scene.frame_start)
frame_end = int(scene.frame_end)
span = max(1, frame_end - frame_start + 1)

if num_samples is not None and num_samples > 0:
    if num_samples == 1 or span == 1:
        sample_frames = [frame_start]
    elif num_samples >= span:
        sample_frames = list(range(frame_start, frame_end + 1))
    else:
        sample_frames = [
            frame_start + int(round(i * (span - 1) / (num_samples - 1)))
            for i in range(num_samples)
        ]
        # Deduplicate while preserving order (can happen on tiny spans).
        deduped = []
        seen = set()
        for frame in sample_frames:
            if frame not in seen:
                deduped.append(frame)
                seen.add(frame)
        sample_frames = deduped
else:
    # Consecutive prefix from the start of the timeline.
    if max_frames is not None and span > max_frames:
        frame_end = frame_start + max_frames - 1
    sample_frames = list(range(frame_start, frame_end + 1))

frames_dir.mkdir(parents=True, exist_ok=True)
for stale in frames_dir.glob("frame*.png"):
    stale.unlink()

# Still-frame renders with zero-padded names frame0000.png ...
for index, frame in enumerate(sample_frames):
    scene.frame_set(int(frame))
    scene.render.filepath = str(frames_dir / f"frame{index:04d}")
    result = bpy.ops.render.render(write_still=True)
    if "FINISHED" not in result:
        raise SystemExit(f"BVB_RENDER_ERROR render_failed frame={frame} result={result}")

written = sorted(frames_dir.glob("frame*.png"))
if not written:
    raise SystemExit("BVB_RENDER_ERROR missing_frames")

print(
    "BVB_RENDER_OK "
    + json.dumps(
        {
            "frames_dir": str(frames_dir),
            "num_frames": len(written),
            "engine": scene.render.engine,
            "timeline_start": frame_start,
            "timeline_end": int(scene.frame_end) if num_samples else frame_end,
            "sample_frames": sample_frames,
            "fps": fps,
            "resolution": resolution,
        }
    )
)
"""


def resolve_blender_executable(value: str | None) -> str:
    candidates: list[str] = []
    if value:
        candidates.append(value)
    candidates.extend(
        [
            "blender",
            "/Applications/Blender.app/Contents/MacOS/Blender",
            "/Applications/Blender 4.3.app/Contents/MacOS/Blender",
            "/Applications/Blender 4.2.app/Contents/MacOS/Blender",
            "/Applications/Blender 4.1.app/Contents/MacOS/Blender",
            "/Applications/Blender 4.0.app/Contents/MacOS/Blender",
            "/Applications/Blender 3.6.app/Contents/MacOS/Blender",
        ]
    )
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return found
        path = Path(candidate)
        if path.is_file():
            return str(path)
    raise SystemExit(
        "Could not find Blender. Pass --blender /path/to/Blender or set BLENDER_BIN."
    )


def render_blend_to_frames(
    blend_path: Path,
    frames_dir: Path,
    *,
    blender: str | None = None,
    resolution: int = 512,
    num_samples: int | None = 64,
    max_frames: int | None = None,
    timeout: float | None = 600.0,
) -> dict[str, Any]:
    """Render ``blend_path`` into ``frames_dir/frame*.png`` from the active camera.

    By default sparsely samples ``num_samples`` frames across the full timeline.
    Pass ``max_frames`` (and ``num_samples=None``) for a consecutive prefix instead.
    """
    blend_path = blend_path.resolve()
    frames_dir = frames_dir.resolve()
    if not blend_path.is_file():
        raise FileNotFoundError(f"Missing blend: {blend_path}")

    frames_dir.mkdir(parents=True, exist_ok=True)
    blender_executable = resolve_blender_executable(blender or os.getenv("BLENDER_BIN"))

    with tempfile.TemporaryDirectory(prefix="bvb_render_script_") as temp_dir:
        script_path = Path(temp_dir) / "render_one_blend.py"
        script_path.write_text(BLENDER_RENDER_SCRIPT, encoding="utf-8")
        command = [
            blender_executable,
            "--background",
            str(blend_path),
            "--python",
            str(script_path),
            "--",
            "--frames-dir",
            str(frames_dir),
            "--resolution",
            str(resolution),
        ]
        if num_samples is not None:
            command.extend(["--num-samples", str(num_samples)])
        elif max_frames is not None:
            command.extend(["--max-frames", str(max_frames)])

        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )

    ok_line = None
    for line in (completed.stdout or "").splitlines():
        if line.startswith("BVB_RENDER_OK "):
            ok_line = line[len("BVB_RENDER_OK ") :]
            break

    frames = sorted(frames_dir.glob("frame*.png"))
    meta: dict[str, Any] = {
        "blend_path": str(blend_path),
        "frames_dir": str(frames_dir),
        "num_frames": len(frames),
        "returncode": completed.returncode,
        "ok": completed.returncode == 0 and bool(ok_line) and bool(frames),
    }
    if ok_line:
        try:
            meta["render"] = json.loads(ok_line)
        except json.JSONDecodeError:
            meta["render_raw"] = ok_line
    if not meta["ok"]:
        meta["stdout_tail"] = (completed.stdout or "")[-4000:]
        meta["stderr_tail"] = (completed.stderr or "")[-4000:]
    return meta


def encode_png_sequence_to_mp4(frames_dir: Path, output_path: Path, fps: int) -> None:
    frames = sorted(frames_dir.glob("frame*.png"))
    if not frames:
        raise RuntimeError(f"No PNG frames in {frames_dir}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        sample_name = frames[0].name
        digits = "".join(ch for ch in sample_name[len("frame") :] if ch.isdigit())
        pad = len(digits) if digits else 4
        start_number = int(digits) if digits else 1
        input_pattern = str(frames_dir / f"frame%0{pad}d.png")
        command = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-framerate",
            str(max(1, fps)),
            "-start_number",
            str(start_number),
            "-i",
            input_pattern,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "23",
            str(output_path),
        ]
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        if completed.returncode == 0 and output_path.is_file():
            return

    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            "Need ffmpeg on PATH or opencv-python-headless to encode rendered frames."
        ) from exc

    first = cv2.imread(str(frames[0]))
    if first is None:
        raise RuntimeError(f"Failed to read frame: {frames[0]}")
    height, width = first.shape[:2]
    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        float(max(1, fps)),
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError(f"OpenCV failed to open VideoWriter for {output_path}")
    try:
        for frame_path in frames:
            image = cv2.imread(str(frame_path))
            if image is None:
                raise RuntimeError(f"Failed to read frame: {frame_path}")
            writer.write(image)
    finally:
        writer.release()
    if not output_path.is_file():
        raise RuntimeError(f"MP4 was not written: {output_path}")


def render_blend_to_mp4(
    blend_path: Path,
    output_path: Path,
    *,
    blender: str | None = None,
    resolution: int = 512,
    num_samples: int | None = 64,
    max_frames: int | None = None,
    timeout: float | None = 600.0,
) -> dict[str, Any]:
    """Render ``blend_path`` from the active camera into ``output_path`` (.mp4)."""
    blend_path = blend_path.resolve()
    output_path = output_path.resolve()
    if output_path.suffix.lower() != ".mp4":
        raise ValueError(f"Output must be .mp4, got: {output_path}")

    with tempfile.TemporaryDirectory(prefix="bvb_render_frames_") as temp_dir:
        frames_dir = Path(temp_dir) / "frames"
        meta = render_blend_to_frames(
            blend_path,
            frames_dir,
            blender=blender,
            resolution=resolution,
            num_samples=num_samples,
            max_frames=max_frames,
            timeout=timeout,
        )
        meta["output_path"] = str(output_path)
        if not meta.get("ok"):
            return meta
        fps = int((meta.get("render") or {}).get("fps") or 24)
        try:
            encode_png_sequence_to_mp4(frames_dir, output_path, fps=fps)
            meta["ok"] = output_path.is_file()
        except Exception as exc:  # noqa: BLE001
            meta["ok"] = False
            meta["stderr_tail"] = f"encode_failed: {type(exc).__name__}: {exc}"
        return meta


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a .blend camera view to MP4.")
    parser.add_argument("--blend", type=Path, required=True, help="Input .blend file.")
    parser.add_argument("--output", type=Path, required=True, help="Output .mp4 path.")
    parser.add_argument("--blender", default=os.getenv("BLENDER_BIN"))
    parser.add_argument("--resolution", type=int, default=512)
    parser.add_argument(
        "--num-samples",
        type=int,
        default=64,
        help="Sparse frames across the full camera timeline (default 64 for V-JEPA 2.1).",
    )
    parser.add_argument("--timeout", type=float, default=600.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    meta = render_blend_to_mp4(
        args.blend,
        args.output,
        blender=args.blender,
        resolution=args.resolution,
        num_samples=args.num_samples,
        timeout=args.timeout,
    )
    print(json.dumps(meta, indent=2))
    if not meta["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
