#!/usr/bin/env python3
"""Official Dual VQA metric: retention of VLM answers on camera renders.

For each Stage-1 run with ``camera_renders/<scene>.mp4``:

1. Ensure shared original-video answers exist under
   ``sandbox/results/_dual_vqa_shared/original_answers.jsonl`` (queried once).
2. Ask the judge VLM the same VSI-Bench questions on sparse frames from each
   render.
3. Score with ``dual_vqa_scoring.semantic_correct``.
4. Write ``dual_vqa.jsonl`` + ``dual_vqa_summary.json`` into the run directory.

Writes separate Dual VQA files and leaves Latent Similarity outputs unchanged.

Requires ``OPENAI_API_KEY`` (or ``--api-key``). Optional dotenv:
``misc/videoqa_pilot/.env`` or ``eval/.env``.

Examples::

  python eval/dual_vqa_metric.py \\
    --run sandbox/results/mini-harness-gpt-5.6-sol-reasoning-xhigh-run01

  python eval/dual_vqa_metric.py --ensure-originals-only
  python eval/dual_vqa_metric.py --text-only
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Any

import cv2
from openai import OpenAI

from dual_vqa_scoring import (
    DUAL_VQA_JSONL,
    DUAL_VQA_SUMMARY,
    ORIGINAL_ANSWERS,
    TEXT_ONLY_ANSWERS,
    load_answer_bank,
    load_qa_metadata,
    make_answer_row,
    make_dual_vqa_row,
    read_jsonl,
    semantic_correct,
    shared_dir,
    summarize_dual_vqa_rows,
    write_jsonl,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS = REPO_ROOT / "sandbox" / "results"
DEFAULT_META = Path(__file__).resolve().parent / "test.jsonl"
DEFAULT_VSI_BENCH = REPO_ROOT / "VSI-Bench"
DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_N_FRAMES = 16
MAX_SIDE = 384
JPEG_QUALITY = 80
MAX_RETRIES = 6


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def original_video(vsi_bench: Path, scene: str, dataset: str) -> Path:
    return vsi_bench / dataset / f"{scene}.mp4"


def render_video(run_dir: Path, scene: str) -> Path:
    return run_dir / "camera_renders" / f"{scene}.mp4"


def sample_frames_b64(video: Path, n: int) -> list[str]:
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {video}")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    idxs = [int(i * (total - 1) / max(n - 1, 1)) for i in range(n)]
    out: list[str] = []
    for idx in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            continue
        height, width = frame.shape[:2]
        scale = MAX_SIDE / max(height, width)
        if scale < 1:
            frame = cv2.resize(frame, (int(width * scale), int(height * scale)))
        ok, buf = cv2.imencode(
            ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]
        )
        if not ok:
            continue
        out.append(base64.b64encode(buf.tobytes()).decode("ascii"))
    cap.release()
    if len(out) < 2:
        raise RuntimeError(f"too few frames from {video}")
    return out


def ask_vlm(
    client: OpenAI,
    *,
    model: str,
    question: str,
    frames_b64: list[str] | None,
) -> tuple[str, dict[str, Any]]:
    if frames_b64 is None:
        prompt = (
            "You are answering a spatial video question about an egocentric "
            "indoor scene, but you are NOT given any video frames. Answer from "
            "the question text alone (and any options it contains). Reply with "
            "the shortest possible answer (a number, a short phrase, or a single "
            "letter A/B/C/D). No explanation.\n\n"
            f"Question: {question}"
        )
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    else:
        prompt = (
            "You are answering a spatial video question from egocentric indoor video. "
            "Use only the provided frames. Reply with the shortest possible answer "
            "(a number, a short phrase, or a single letter A/B/C/D). No explanation.\n\n"
            f"Question: {question}"
        )
        content = [{"type": "text", "text": prompt}]
        for b64 in frames_b64:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{b64}",
                        "detail": "low",
                    },
                }
            )
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": content}],
                max_completion_tokens=32,
                temperature=0,
            )
            answer = (resp.choices[0].message.content or "").strip()
            usage = {
                "prompt_tokens": getattr(resp.usage, "prompt_tokens", None),
                "completion_tokens": getattr(resp.usage, "completion_tokens", None),
                "total_tokens": getattr(resp.usage, "total_tokens", None),
            }
            return answer, usage
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(min(2**attempt, 60))
    raise RuntimeError(f"ask_vlm failed after retries: {last_err}")


def append_jsonl(path: Path, row: dict[str, Any], lock: Lock) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)


def rewrite_answer_bank(path: Path, bank: dict[str, dict[str, Any]]) -> None:
    rows = [bank[key] for key in sorted(bank, key=lambda qa_id: int(qa_id))]
    write_jsonl(path, rows)


def ensure_originals(
    *,
    client: OpenAI,
    metadata: dict[str, dict[str, Any]],
    vsi_bench: Path,
    results_dir: Path,
    model: str,
    n_frames: int,
    workers: int,
    qa_ids: set[str] | None,
) -> dict[str, dict[str, Any]]:
    path = shared_dir(results_dir) / ORIGINAL_ANSWERS
    bank = load_answer_bank(path)
    needed = []
    for qa_id, qa in metadata.items():
        if qa_ids is not None and qa_id not in qa_ids:
            continue
        if qa_id in bank:
            continue
        scene = str(qa["scene_name"])
        dataset = str(qa["dataset"])
        video = original_video(vsi_bench, scene, dataset)
        if not video.is_file():
            continue
        needed.append((qa_id, qa, video))
    if not needed:
        return bank

    lock = Lock()
    print(f"[originals] querying {len(needed)} missing answers → {path}", flush=True)

    def worker(item: tuple[str, dict[str, Any], Path]) -> dict[str, Any]:
        qa_id, qa, video = item
        frames = sample_frames_b64(video, n_frames)
        answer, usage = ask_vlm(
            client, model=model, question=str(qa["question"]), frames_b64=frames
        )
        row = make_answer_row(
            qa_id=qa_id,
            qa=qa,
            answer=answer,
            view="original",
            model=model,
            n_frames=n_frames,
            correct=semantic_correct(answer, qa),
            extra={"usage": usage, "video": str(video)},
        )
        append_jsonl(path, row, lock)
        return row

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(worker, item) for item in needed]
        for index, fut in enumerate(as_completed(futs), start=1):
            row = fut.result()
            bank[str(row["qa_id"])] = row
            if index % 50 == 0 or index == len(needed):
                print(f"[originals] {index}/{len(needed)}", flush=True)
    # Compact / dedupe bank file after append-heavy resume.
    rewrite_answer_bank(path, bank)
    return bank


def ensure_text_only(
    *,
    client: OpenAI,
    metadata: dict[str, dict[str, Any]],
    results_dir: Path,
    model: str,
    workers: int,
) -> dict[str, dict[str, Any]]:
    path = shared_dir(results_dir) / TEXT_ONLY_ANSWERS
    bank = load_answer_bank(path)
    needed = [
        (qa_id, qa)
        for qa_id, qa in metadata.items()
        if qa_id not in bank
    ]
    if not needed:
        print(f"[text-only] already complete ({len(bank)}) → {path}", flush=True)
        return bank

    lock = Lock()
    print(f"[text-only] querying {len(needed)} → {path}", flush=True)

    def worker(item: tuple[str, dict[str, Any]]) -> dict[str, Any]:
        qa_id, qa = item
        answer, usage = ask_vlm(
            client, model=model, question=str(qa["question"]), frames_b64=None
        )
        row = make_answer_row(
            qa_id=qa_id,
            qa=qa,
            answer=answer,
            view="text_only",
            model=model,
            n_frames=None,
            correct=semantic_correct(answer, qa),
            extra={"usage": usage},
        )
        append_jsonl(path, row, lock)
        return row

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(worker, item) for item in needed]
        for index, fut in enumerate(as_completed(futs), start=1):
            row = fut.result()
            bank[str(row["qa_id"])] = row
            if index % 100 == 0 or index == len(needed):
                print(f"[text-only] {index}/{len(needed)}", flush=True)
    rewrite_answer_bank(path, bank)
    return bank


def discover_render_qa_ids(run_dir: Path, metadata: dict[str, dict[str, Any]]) -> set[str]:
    cam = run_dir / "camera_renders"
    if not cam.is_dir():
        return set()
    scenes = {path.stem for path in cam.glob("*.mp4")}
    return {
        qa_id
        for qa_id, qa in metadata.items()
        if str(qa.get("scene_name")) in scenes
    }


def score_run(
    *,
    client: OpenAI,
    run_dir: Path,
    metadata: dict[str, dict[str, Any]],
    original_bank: dict[str, dict[str, Any]],
    model: str,
    n_frames: int,
    workers: int,
    resume: bool,
    force: bool,
) -> dict[str, Any]:
    out_jsonl = run_dir / DUAL_VQA_JSONL
    out_summary = run_dir / DUAL_VQA_SUMMARY
    if force:
        for path in (out_jsonl, out_summary):
            if path.exists():
                path.unlink()

    done: dict[str, dict[str, Any]] = {}
    if resume and out_jsonl.is_file():
        for row in read_jsonl(out_jsonl):
            done[str(row["qa_id"])] = row

    qa_ids = sorted(discover_render_qa_ids(run_dir, metadata), key=int)
    jobs: list[tuple[str, dict[str, Any], Path]] = []
    for qa_id in qa_ids:
        if qa_id in done and done[qa_id].get("status") == "ok":
            continue
        qa = metadata[qa_id]
        video = render_video(run_dir, str(qa["scene_name"]))
        if not video.is_file():
            continue
        jobs.append((qa_id, qa, video))

    lock = Lock()
    print(
        f"[run] {run_dir.name}: done={len(done)} pending={len(jobs)} "
        f"model={model} frames={n_frames}",
        flush=True,
    )

    def worker(item: tuple[str, dict[str, Any], Path]) -> dict[str, Any]:
        qa_id, qa, video = item
        try:
            frames = sample_frames_b64(video, n_frames)
            answer, usage = ask_vlm(
                client,
                model=model,
                question=str(qa["question"]),
                frames_b64=frames,
            )
            rendered_correct = semantic_correct(answer, qa)
            orig = original_bank.get(qa_id)
            row = make_dual_vqa_row(
                qa_id=qa_id,
                qa=qa,
                rendered_answer=answer,
                rendered_correct=rendered_correct,
                original_correct=None if orig is None else bool(orig["correct"]),
                judge_model=model,
                n_frames=n_frames,
            )
            row["usage"] = usage
            row["video"] = str(video)
            return row
        except Exception as exc:  # noqa: BLE001
            return {
                "qa_id": qa_id,
                "scene_name": str(qa.get("scene_name", "")),
                "question_type": str(qa.get("question_type", "")),
                "status": "error",
                "error": str(exc),
                "judge_model": model,
                "n_frames": n_frames,
                "protocol": "dual_vqa_v1",
            }

    if jobs:
        # Append-only while running; rewrite compact file at the end.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(worker, item): item[0] for item in jobs}
            finished = 0
            for fut in as_completed(futs):
                row = fut.result()
                done[str(row["qa_id"])] = row
                append_jsonl(out_jsonl, row, lock)
                finished += 1
                if finished % 100 == 0 or finished == len(jobs):
                    print(
                        f"[run] {run_dir.name}: +{finished}/{len(jobs)}",
                        flush=True,
                    )

    ordered = [done[qa_id] for qa_id in sorted(done, key=int)]
    # Drop usage/video from the published jsonl to keep HF artifacts compact.
    publish = []
    for row in ordered:
        slim = {
            key: value
            for key, value in row.items()
            if key not in {"usage", "video", "error"}
            or row.get("status") != "ok"
        }
        if row.get("status") != "ok" and "error" in row:
            slim["error"] = row["error"]
        publish.append(slim)
    write_jsonl(out_jsonl, publish)
    summary = summarize_dual_vqa_rows(
        publish, judge_model=model, n_frames=n_frames, source="dual_vqa_metric"
    )
    out_summary.write_text(json.dumps(summary, indent=2) + "\n")
    print(
        f"[run] {run_dir.name}: retention={summary.get('retention_rate')} "
        f"n={summary.get('num_ok')} → {out_summary}",
        flush=True,
    )
    return summary


def resolve_run_dir(raw: str | Path, results_dir: Path) -> Path:
    path = Path(raw)
    if path.is_dir():
        return path.resolve()
    candidate = results_dir / str(raw)
    if candidate.is_dir():
        return candidate.resolve()
    raise SystemExit(f"run directory not found: {raw}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        action="append",
        default=[],
        help="Run dir path or name under --results-dir; repeatable.",
    )
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--qa-metadata", type=Path, default=DEFAULT_META)
    parser.add_argument("--vsi-bench", type=Path, default=DEFAULT_VSI_BENCH)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--n-frames", type=int, default=DEFAULT_N_FRAMES)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--api-key", default=None)
    parser.add_argument(
        "--ensure-originals-only",
        action="store_true",
        help="Only fill shared original answers; do not score runs.",
    )
    parser.add_argument(
        "--text-only",
        action="store_true",
        help="Fill shared text-only answer bank (chance floor B).",
    )
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    for dotenv in (
        REPO_ROOT / "eval" / ".env",
        REPO_ROOT / "misc" / "videoqa_pilot" / ".env",
    ):
        load_dotenv(dotenv)

    api_key = args.api_key or os.environ.get("OPENAI_API_KEY")
    needs_api = bool(args.run) or args.ensure_originals_only or args.text_only
    if needs_api and not api_key:
        raise SystemExit(
            "Set OPENAI_API_KEY, pass --api-key, or put it in eval/.env"
        )

    metadata = load_qa_metadata(args.qa_metadata)
    client = OpenAI(api_key=api_key) if needs_api else None
    resume = args.resume and not args.no_resume

    if args.text_only:
        assert client is not None
        ensure_text_only(
            client=client,
            metadata=metadata,
            results_dir=args.results_dir,
            model=args.model,
            workers=args.workers,
        )
        if not args.run and not args.ensure_originals_only:
            return

    run_dirs = [resolve_run_dir(name, args.results_dir) for name in args.run]
    needed_qa: set[str] | None = None
    if run_dirs:
        needed_qa = set()
        for run_dir in run_dirs:
            needed_qa |= discover_render_qa_ids(run_dir, metadata)

    if args.ensure_originals_only or run_dirs:
        assert client is not None
        original_bank = ensure_originals(
            client=client,
            metadata=metadata,
            vsi_bench=args.vsi_bench,
            results_dir=args.results_dir,
            model=args.model,
            n_frames=args.n_frames,
            workers=args.workers,
            qa_ids=needed_qa,
        )
    else:
        original_bank = load_answer_bank(
            shared_dir(args.results_dir) / ORIGINAL_ANSWERS
        )

    if args.ensure_originals_only and not run_dirs:
        print(
            json.dumps(
                {
                    "n_original_answers": len(original_bank),
                    "path": str(shared_dir(args.results_dir) / ORIGINAL_ANSWERS),
                },
                indent=2,
            )
        )
        return

    if not run_dirs:
        raise SystemExit("pass --run, --ensure-originals-only, and/or --text-only")

    assert client is not None
    summaries = {}
    for run_dir in run_dirs:
        summaries[run_dir.name] = score_run(
            client=client,
            run_dir=run_dir,
            metadata=metadata,
            original_bank=original_bank,
            model=args.model,
            n_frames=args.n_frames,
            workers=args.workers,
            resume=resume,
            force=args.force,
        )
    print(json.dumps({"runs": list(summaries)}, indent=2))


if __name__ == "__main__":
    main()
