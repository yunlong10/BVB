#!/usr/bin/env python3
"""Grader for BVB video-reconstruction tasks (Harbor verifier).

reward = Dual VQA retention: of the questions the judge answers correctly on the
source video (fixed at authoring time in source_answers.jsonl), the share it still
answers correctly on a render of the submitted scene.

Steps:
  1. gate: /app/result.blend exists, is not a symlink, opens in Blender, has a scene
     camera and at least `min_meshes` mesh objects; otherwise reward 0
  2. render the scene camera across its timeline with BVB's renderer (512 px), as\n     many evenly spaced frames as the judge sees (16)
  3. show the judge those 16 frames and ask each counted question `votes` times
     (BVB's prompt and answer matching); a question is kept on a majority of
     correct votes
  4. write /logs/verifier/reward.txt, reward.json, reward_details.json, render.mp4

The rendering, frame sampling, judge prompt, and answer matching are imported
unchanged from the BVB repository (render_blend_video.py, dual_vqa_metric.py,
dual_vqa_scoring.py), copied next to this file by make_task.py.

Also importable at authoring time: make_task.py uses judge_question() to build
source_answers.jsonl from the source video with the same settings.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from dual_vqa_metric import ask_vlm, sample_frames_b64  # noqa: E402
from dual_vqa_scoring import semantic_correct  # noqa: E402

INSPECT_SCRIPT = r"""
import bpy, json, sys
sc = bpy.context.scene
cam = sc.camera
ad = cam.animation_data if cam else None
info = {
    "has_camera": cam is not None,
    "camera_animated": bool(ad and ad.action),
    "meshes": sum(1 for o in bpy.data.objects if o.type == "MESH"),
    "lights": sum(1 for o in bpy.data.objects if o.type == "LIGHT"),
    "frame_start": sc.frame_start,
    "frame_end": sc.frame_end,
}
print("BVB_INSPECT " + json.dumps(info))
"""


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def judge_question(client: Any, model: str, question: dict[str, Any], frames: list[str], votes: int) -> dict[str, Any]:
    """Ask one question `votes` times on the same frames; majority decides."""
    answers = []
    for _ in range(votes):
        answer, _usage = ask_vlm(client, model=model, question=str(question["question"]), frames_b64=frames)
        answers.append(answer)
    correct = [bool(semantic_correct(a, question)) for a in answers]
    return {"answers": answers, "correct_votes": sum(correct), "votes": votes,
            "correct": sum(correct) * 2 > votes}


def judge_all(questions: list[dict[str, Any]], frames: list[str], model: str, votes: int, workers: int = 8) -> dict[str, dict[str, Any]]:
    from openai import OpenAI

    client = OpenAI()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = pool.map(lambda q: judge_question(client, model, q, frames, votes), questions)
        return {str(q["id"]): r for q, r in zip(questions, results)}


def inspect_blend(blender: str, blend: Path, timeout: float) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(INSPECT_SCRIPT)
        script = handle.name
    try:
        proc = subprocess.run([blender, "-b", str(blend), "--python", script],
                              capture_output=True, text=True, timeout=timeout)
    finally:
        os.unlink(script)
    for line in proc.stdout.splitlines():
        if line.startswith("BVB_INSPECT "):
            return json.loads(line[len("BVB_INSPECT "):])
    raise RuntimeError("Blender could not open the scene:\n" + proc.stdout[-2000:] + proc.stderr[-2000:])


def write_reward(logs: Path, reward: float, details: dict[str, Any]) -> None:
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "reward.txt").write_text(f"{reward:.6f}\n")
    (logs / "reward.json").write_text(json.dumps({"reward": reward}) + "\n")
    (logs / "reward_details.json").write_text(json.dumps({"reward": reward, **details}, indent=2) + "\n")


def grade(candidate: Path, grader_dir: Path, logs: Path) -> float:
    config = json.loads((grader_dir / "config.json").read_text())
    questions = {str(q["id"]): q for q in load_jsonl(grader_dir / "questions.jsonl")}
    bank = {str(r["qa_id"]): r for r in load_jsonl(grader_dir / "source_answers.jsonl")}
    counted = [questions[qid] for qid, row in bank.items() if row["source_correct"]]

    def zero(reason: str, **extra: Any) -> float:
        write_reward(logs, 0.0, {"reason": reason, **extra})
        print(f"reward 0: {reason}", file=sys.stderr)
        return 0.0

    if not candidate.exists():
        return zero(f"no submission at {candidate}")
    if candidate.is_symlink():
        return zero("submission is a symlink")
    if not counted:
        return zero("task misconfigured: no counted questions in source_answers.jsonl")

    from render_blend_video import render_blend_to_mp4, resolve_blender_executable

    blender = resolve_blender_executable(os.getenv("BLENDER_BIN"))
    try:
        scene = inspect_blend(blender, candidate, timeout=float(config["render_timeout_sec"]))
    except Exception as exc:  # noqa: BLE001
        return zero(f"scene does not open: {exc}")
    if not scene["has_camera"]:
        return zero("scene has no camera", scene=scene)
    if scene["meshes"] < int(config["min_meshes"]):
        return zero(f"scene has {scene['meshes']} mesh objects; at least {config['min_meshes']} required", scene=scene)

    render = logs / "render.mp4"
    try:
        meta = render_blend_to_mp4(candidate, render, blender=blender, resolution=int(config["resolution"]),
                                   num_samples=int(config["render_frames"]), timeout=float(config["render_timeout_sec"]))
    except BaseException as exc:  # noqa: BLE001 - SystemExit / timeout from the renderer count too
        return zero(f"render failed: {exc.__class__.__name__}: {exc}", scene=scene)
    if not meta.get("ok") or not render.is_file():
        return zero("render failed", scene=scene, blender_stdout=meta.get("stdout_tail"),
                    blender_stderr=meta.get("stderr_tail"))

    frames = sample_frames_b64(render, int(config["n_frames"]))
    verdicts = judge_all(counted, frames, config["judge_model"], int(config["votes"]))

    rows = []
    for qid, question in questions.items():
        source = bank[qid]
        verdict = verdicts.get(qid)
        rows.append({
            "id": qid,
            "question": question["question"],
            "ground_truth": question["ground_truth"],
            "options": question.get("options"),
            "source_answers": source["answers"],
            "counted": bool(source["source_correct"]),
            "render_answers": verdict["answers"] if verdict else None,
            "kept": bool(verdict and verdict["correct"]),
        })
    kept = sum(r["kept"] for r in rows if r["counted"])
    reward = kept / len(counted)
    write_reward(logs, reward, {
        "kept": kept,
        "counted": len(counted),
        "judge_model": config["judge_model"],
        "votes": config["votes"],
        "n_frames": config["n_frames"],
        "scene": scene,
        "questions": rows,
    })
    print(f"reward {reward:.3f} ({kept}/{len(counted)} counted questions kept)")
    for r in rows:
        status = "not counted" if not r["counted"] else ("kept" if r["kept"] else "lost")
        print(f"  {r['id']}: {status:<11} render answers: {r['render_answers']}")
    return reward


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidate", type=Path, default=Path("/app/result.blend"))
    parser.add_argument("--grader-dir", type=Path, default=HERE)
    parser.add_argument("--logs", type=Path, default=Path("/logs/verifier"))
    args = parser.parse_args()
    try:
        grade(args.candidate, args.grader_dir, args.logs)
    except Exception as exc:  # noqa: BLE001
        write_reward(args.logs, 0.0, {"reason": f"grader error: {exc.__class__.__name__}: {exc}"})
        raise


if __name__ == "__main__":
    main()
