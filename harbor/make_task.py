#!/usr/bin/env python3
"""Turn a video + questions + golden scene into a Harbor task for BVB-style video reconstruction.

    python harbor/make_task.py --name my-kitchen \\
        --video ~/Desktop/kitchen.mov --questions my_questions.jsonl --golden golden.blend

Writes harbor/tasks/<name>/ with instruction.md, task.toml, environment/ (Blender 4.2 + the
video), solution/ (the golden scene + solve.sh), and tests/ (verifier image, test.sh, and
the grader with the held-back questions).

The video is normalized (30 fps, no audio, 640 px on the long side) and baked into the agent
image. The judge's answers on that video are computed once here (needs OPENAI_API_KEY) and
stored as tests/grader/source_answers.jsonl: only questions the judge gets right on the
source count toward the reward, so every submission is graded against the same source answers.

Run from the BVB repository root with the Stage-1 venv (it has openai + opencv):
    sandbox/.venv/bin/python harbor/make_task.py ...
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HARBOR = Path(__file__).resolve().parent
REPO = HARBOR.parent
TEMPLATE = HARBOR / "template"
VENDORED = ["render_blend_video.py", "dual_vqa_metric.py", "dual_vqa_scoring.py"]
NUMERIC_TYPES = {"object_counting", "object_size_estimation", "room_size_estimation", "object_abs_distance"}
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def load_dotenv() -> None:
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def validate_questions(path: Path) -> list[dict]:
    """Check the BVB / VSI-Bench question format. Errors stop the build; warnings print."""
    rows = [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]
    errors, warnings, seen = [], [], set()
    for n, q in enumerate(rows, start=1):
        where = f"{path.name} line {n}"
        for key in ("id", "question_type", "question", "ground_truth"):
            if key not in q:
                errors.append(f"{where}: missing '{key}'")
        if errors:
            continue
        if q["id"] in seen:
            errors.append(f"{where}: duplicate id {q['id']}")
        seen.add(q["id"])
        options = q.get("options")
        if q["question_type"] in NUMERIC_TYPES:
            if options:
                errors.append(f"{where}: {q['question_type']} is numeric; set options to null")
            try:
                float(str(q["ground_truth"]))
            except ValueError:
                errors.append(f"{where}: {q['question_type']} needs a numeric ground_truth, got {q['ground_truth']!r}")
            continue
        if not options:
            errors.append(f"{where}: multiple-choice question needs options like [\"A. left\", \"B. right\"]")
            continue
        letters = {}
        for option in options:
            m = re.match(r"^([A-D])\.\s+(.+)$", str(option))
            if not m:
                errors.append(f"{where}: option {option!r} must look like 'A. text'")
                continue
            letters[m.group(1)] = m.group(2)
        if str(q["ground_truth"]) not in letters:
            errors.append(f"{where}: ground_truth {q['ground_truth']!r} is not one of the option letters {sorted(letters)}")
        # The judge never sees the options list, only the question text: the choices must be in it.
        # (Order and route questions list items or steps instead of every candidate answer.)
        text = q["question"].lower()
        missing = [t for t in letters.values()
                   if not all(word in text for word in re.findall(r"[a-z0-9]+", t.lower()))]
        if missing and q["question_type"] not in ("obj_appearance_order", "route_planning"):
            warnings.append(f"{where}: the question text does not mention option(s) {missing}; "
                            "the judge only sees the question, so write the choices into it")
    for w in warnings:
        print("warning:", w)
    if errors:
        raise SystemExit("question file has errors:\n  " + "\n  ".join(errors))
    if len(rows) < 8:
        print(f"warning: only {len(rows)} questions; with few counted questions one judge flip moves the reward a lot")
    return rows


def check_blend_version(path: Path) -> None:
    """The verifier runs Blender 4.2, which cannot open files saved by Blender 5.x."""
    header = path.open("rb").read(12)
    if not header.startswith(b"BLENDER"):
        raise SystemExit(f"{path} is not a .blend file")
    if header[7:8] not in (b"-", b"_"):  # 5.x headers read BLENDER17-01v05xx
        raise SystemExit(f"{path} was saved by Blender 5.x; the task's Blender 4.2 cannot open it. "
                         "Re-save it with Blender 4.2, e.g. run your build script in the bvb-sandbox image.")
    version = header[9:12].decode(errors="replace")
    if version > "402":
        print(f"warning: {path.name} was saved by Blender {version[0]}.{version[1:]}; the verifier runs 4.2")


def normalize_video(src: Path, dst: Path) -> dict:
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-i", str(src), "-map", "0:v:0", "-an",
        "-vf", "scale='if(gt(iw,ih),640,-2)':'if(gt(iw,ih),-2,640)',fps=30",
        "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst),
    ], check=True)
    probe = json.loads(subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=width,height,r_frame_rate:format=duration", "-of", "json", str(dst),
    ], check=True, capture_output=True, text=True).stdout)
    stream = probe["streams"][0]
    num, den = (int(x) for x in stream["r_frame_rate"].split("/"))
    return {"width": stream["width"], "height": stream["height"], "fps": num / den,
            "duration_s": float(probe["format"]["duration"])}


def build_source_bank(video: Path, questions: list[dict], grader_dir: Path, config: dict) -> list[dict]:
    sys.path.insert(0, str(grader_dir))
    from dual_vqa_metric import sample_frames_b64  # noqa: E402
    from grade import judge_all  # noqa: E402

    frames = sample_frames_b64(video, int(config["n_frames"]))
    verdicts = judge_all(questions, frames, config["judge_model"], int(config["votes"]))
    rows = []
    for q in questions:
        v = verdicts[str(q["id"])]
        rows.append({"qa_id": str(q["id"]), "answers": v["answers"], "correct_votes": v["correct_votes"],
                     "votes": v["votes"], "source_correct": v["correct"]})
    return rows


def toml_str(value: str) -> str:
    return json.dumps(value)


def write_task_toml(path: Path, args: argparse.Namespace, video: dict, n_questions: int, n_counted: int) -> None:
    path.write_text(f"""schema_version = "1.3"
artifacts = ["/app/result.blend"]

[task]
name = {toml_str("local/bvb-" + args.name)}
description = {toml_str(args.description or "Rebuild a real indoor video as an animated Blender scene from primitives; graded by a judge model answering held-back spatial questions on a render of the scene.")}
authors = [{{ name = {toml_str(args.author)} }}]
keywords = ["blender", "bpy", "video", "3d-reconstruction", "spatial-reasoning", "vision", "bvb"]

[metadata]
category = "video-to-3d"
benchmark = "BVB (Blender-VideoBench), Dual VQA retention"
difficulty_explanation = "Reconstruct a real indoor video as an animated Blender scene built from primitives, including the camera path; graded by how many held-back spatial questions a judge still answers correctly on a render of the scene."
source_video_seconds = {video['duration_s']:.2f}
questions_total = {n_questions}
questions_counted = {n_counted}
judge_model = {toml_str(args.judge_model)}
judge_votes = {args.votes}
golden_floor = {args.golden_floor}

[verifier]
timeout_sec = 7200.0
environment_mode = "separate"
# The judge is an API model: the verifier may reach only the OpenAI API.
network_mode = "allowlist"
allowed_hosts = ["api.openai.com"]

[verifier.env]
OPENAI_API_KEY = "${{OPENAI_API_KEY}}"

[agent]
timeout_sec = {args.agent_timeout_min * 60}
# Deny model-time egress unless the run config supplies the model provider via
# agent.extra_allowed_hosts (or --allow-agent-host).
network_mode = "no-network"

[environment]
build_timeout_sec = 3600.0
cpus = 2
memory_mb = 4096
storage_mb = 10240
gpus = 0
network_mode = "public"
""")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", required=True, help="Task slug, e.g. my-kitchen (lowercase, digits, dashes)")
    parser.add_argument("--video", type=Path, required=True, help="Source video (any format FFmpeg reads)")
    parser.add_argument("--questions", type=Path, required=True, help="Questions JSONL (see harbor/examples/)")
    parser.add_argument("--golden", type=Path, required=True, help="Golden reconstruction .blend")
    parser.add_argument("--out", type=Path, default=HARBOR / "tasks")
    parser.add_argument("--description", default="")
    parser.add_argument("--author", default="BVB contributor")
    parser.add_argument("--judge-model", default="gpt-5.4-mini")
    parser.add_argument("--votes", type=int, default=5, help="Judge votes per question (odd; majority decides)")
    parser.add_argument("--n-frames", type=int, default=16, help="Frames shown to the judge")
    parser.add_argument("--min-meshes", type=int, default=10, help="Submissions with fewer mesh objects score 0")
    parser.add_argument("--agent-timeout-min", type=int, default=60)
    parser.add_argument("--golden-floor", type=float, default=0.8, help="Minimum oracle reward the golden must reach")
    parser.add_argument("--source-answers", type=Path, help="Reuse an existing source_answers.jsonl instead of calling the judge")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing task directory")
    args = parser.parse_args()

    if not NAME_RE.match(args.name):
        raise SystemExit("--name must be lowercase letters, digits, and dashes")
    if args.votes < 1 or args.votes % 2 == 0:
        raise SystemExit("--votes must be odd")
    for p in (args.video, args.questions, args.golden):
        if not p.is_file():
            raise SystemExit(f"not found: {p}")
    task = args.out / f"bvb-{args.name}"
    if task.exists():
        if not args.force:
            raise SystemExit(f"{task} exists; pass --force to overwrite")
        shutil.rmtree(task)
    load_dotenv()

    check_blend_version(args.golden)
    questions = validate_questions(args.questions)
    print(f"questions: {len(questions)} ok")

    # agent side: instruction + environment with the normalized video
    video = normalize_video(args.video, task / "environment" / "video.mp4")
    print(f"video: {video['width']}x{video['height']}, {video['fps']:g} fps, {video['duration_s']:.1f} s")
    shutil.copy(TEMPLATE / "environment" / "Dockerfile", task / "environment" / "Dockerfile")
    (task / "instruction.md").write_text(
        (TEMPLATE / "instruction.md").read_text().format(agent_timeout_min=args.agent_timeout_min, **video))

    # verifier side: grader, vendored BVB scoring code, questions, config, source answers
    grader = task / "tests" / "grader"
    grader.mkdir(parents=True)
    shutil.copy(TEMPLATE / "tests" / "Dockerfile", task / "tests" / "Dockerfile")
    shutil.copy(TEMPLATE / "tests" / "test.sh", task / "tests" / "test.sh")
    shutil.copy(TEMPLATE / "tests" / "grader" / "grade.py", grader / "grade.py")
    for name in VENDORED:
        shutil.copy(REPO / "eval" / name, grader / name)
    shutil.copy(args.questions, grader / "questions.jsonl")
    config = {"judge_model": args.judge_model, "n_frames": args.n_frames, "votes": args.votes,
              "render_frames": args.n_frames, "resolution": 512, "render_timeout_sec": 4800, "min_meshes": args.min_meshes}
    (grader / "config.json").write_text(json.dumps(config, indent=2) + "\n")

    if args.source_answers:
        bank = [json.loads(line) for line in args.source_answers.open() if line.strip()]
        print(f"source answers: reused {args.source_answers}")
    else:
        if not os.environ.get("OPENAI_API_KEY"):
            raise SystemExit("OPENAI_API_KEY is needed to build the source answers (or pass --source-answers)")
        print(f"source answers: asking {args.judge_model} each question {args.votes}x on the source video ...")
        bank = build_source_bank(task / "environment" / "video.mp4", questions, grader, config)
    with (grader / "source_answers.jsonl").open("w") as f:
        for row in bank:
            f.write(json.dumps(row) + "\n")

    # oracle
    (task / "solution").mkdir()
    shutil.copy(TEMPLATE / "solution" / "solve.sh", task / "solution" / "solve.sh")
    shutil.copy(args.golden, task / "solution" / "golden.blend")
    for script in (task / "tests" / "test.sh", task / "solution" / "solve.sh"):
        script.chmod(0o755)

    counted = [r for r in bank if r["source_correct"]]
    write_task_toml(task / "task.toml", args, video, len(questions), len(counted))

    by_id = {str(q["id"]): q for q in questions}
    print(f"\ncounted questions: {len(counted)} of {len(questions)} (the judge must answer them right on the source)")
    for r in bank:
        mark = "counts" if r["source_correct"] else "DROPPED"
        print(f"  {mark:<7} {r['qa_id']}  {r['correct_votes']}/{r['votes']} votes  {by_id[r['qa_id']]['question'][:70]}")
    if len(counted) < 8:
        print("warning: fewer than 8 counted questions; reword the dropped ones so the judge can answer them from the video")
    print(f"\nwrote {task}\nnext:\n  harbor run -y -p {task} -a oracle   # golden must reach {args.golden_floor}"
          f"\n  harbor run -y -p {task} -a nop      # empty submission must score 0")


if __name__ == "__main__":
    main()
