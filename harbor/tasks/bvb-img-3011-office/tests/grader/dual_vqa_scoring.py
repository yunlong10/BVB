#!/usr/bin/env python3
"""Shared Dual VQA scoring helpers (semantic match + summary aggregation).

Used by ``dual_vqa_metric.py`` (live runner) and ``import_dual_vqa_from_pilot.py``.
Keeps answer-matching rules in one place so paper tables and HF artifacts agree.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

NUMERIC_TYPES = {
    "object_counting",
    "object_size_estimation",
    "room_size_estimation",
    "object_abs_distance",
}

PROTOCOL = "dual_vqa_v1"
SHARED_DIRNAME = "_dual_vqa_shared"
ORIGINAL_ANSWERS = "original_answers.jsonl"
TEXT_ONLY_ANSWERS = "text_only_answers.jsonl"
DUAL_VQA_JSONL = "dual_vqa.jsonl"
DUAL_VQA_SUMMARY = "dual_vqa_summary.json"


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on {path}:{line_number}") from exc


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def load_qa_metadata(path: Path) -> dict[str, dict[str, Any]]:
    return {str(row["id"]): row for row in read_jsonl(path)}


def normalize_text(value: Any) -> str:
    text = str(value).lower().strip()
    text = re.sub(r"^[a-d][\).:\-]\s*", "", text)
    text = re.sub(r"[^a-z0-9.\s,\-]", " ", text)
    return re.sub(r"\s+", " ", text).strip(" .,")


def extract_number(value: Any) -> float | None:
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group(0)) if match else None


def semantic_correct(answer: Any, qa: dict[str, Any]) -> bool:
    """Match a model answer against VSI-Bench ground truth (pilot rules)."""
    ground_truth = str(qa["ground_truth"]).strip()
    question_type = str(qa["question_type"])
    if question_type in NUMERIC_TYPES:
        predicted = extract_number(answer)
        expected = extract_number(ground_truth)
        if predicted is None or expected is None:
            return False
        if question_type == "object_counting":
            return abs(predicted - expected) < 0.5
        if expected == 0:
            return abs(predicted) < 1e-6
        return abs(predicted - expected) / abs(expected) <= 0.20
    letter = re.search(
        r"(?:^|\b)(?:option\s*)?([A-Da-d])(?:\b|$)", str(answer).strip()
    )
    if letter and len(str(answer)) < 40:
        return letter.group(1).upper() == ground_truth.upper()
    target = None
    for option in qa.get("options", []):
        match = re.match(r"([A-D])\.\s*(.*)", str(option), re.I)
        if match and match.group(1).upper() == ground_truth.upper():
            target = normalize_text(match.group(2))
            break
    if not target:
        return False
    predicted_text = normalize_text(answer)
    if predicted_text == target or target in predicted_text or predicted_text in target:
        return True
    return SequenceMatcher(None, predicted_text, target).ratio() >= 0.88


def shared_dir(results_dir: Path) -> Path:
    return results_dir / SHARED_DIRNAME


def make_answer_row(
    *,
    qa_id: str,
    qa: dict[str, Any],
    answer: str,
    view: str,
    model: str,
    n_frames: int | None,
    correct: bool,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {
        "qa_id": str(qa_id),
        "scene_name": str(qa.get("scene_name", "")),
        "question_type": str(qa.get("question_type", "")),
        "view": view,
        "answer": answer,
        "correct": bool(correct),
        "model": model,
        "n_frames": n_frames,
        "protocol": PROTOCOL,
    }
    if extra:
        row.update(extra)
    return row


def make_dual_vqa_row(
    *,
    qa_id: str,
    qa: dict[str, Any],
    rendered_answer: str,
    rendered_correct: bool,
    original_correct: bool | None,
    judge_model: str,
    n_frames: int | None,
    status: str = "ok",
) -> dict[str, Any]:
    retained: bool | None
    if original_correct is None:
        retained = None
    else:
        retained = bool(original_correct and rendered_correct)
    return {
        "qa_id": str(qa_id),
        "scene_name": str(qa.get("scene_name", "")),
        "question_type": str(qa.get("question_type", "")),
        "status": status,
        "rendered_answer": rendered_answer,
        "rendered_correct": bool(rendered_correct),
        "original_correct": original_correct,
        "retained": retained,
        "judge_model": judge_model,
        "n_frames": n_frames,
        "protocol": PROTOCOL,
    }


def summarize_dual_vqa_rows(
    rows: list[dict[str, Any]],
    *,
    judge_model: str | None = None,
    n_frames: int | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    ok_rows = [row for row in rows if row.get("status", "ok") == "ok"]
    n_rendered_correct = sum(1 for row in ok_rows if row.get("rendered_correct"))
    joinable = [row for row in ok_rows if row.get("original_correct") is not None]
    n_original_correct = sum(1 for row in joinable if row.get("original_correct"))
    n_retained = sum(1 for row in joinable if row.get("retained"))
    retention_rate = (
        n_retained / n_original_correct if n_original_correct else None
    )
    rendered_accuracy = (
        n_rendered_correct / len(ok_rows) if ok_rows else None
    )
    original_accuracy = (
        n_original_correct / len(joinable) if joinable else None
    )

    by_type: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in ok_rows:
        grouped[str(row.get("question_type") or "unknown")].append(row)
    for qtype, group in sorted(grouped.items()):
        g_join = [row for row in group if row.get("original_correct") is not None]
        g_orig = sum(1 for row in g_join if row.get("original_correct"))
        g_ret = sum(1 for row in g_join if row.get("retained"))
        g_rend = sum(1 for row in group if row.get("rendered_correct"))
        by_type[qtype] = {
            "n": len(group),
            "n_joinable": len(g_join),
            "n_original_correct": g_orig,
            "n_retained": g_ret,
            "retention_rate": (g_ret / g_orig) if g_orig else None,
            "rendered_accuracy": (g_rend / len(group)) if group else None,
        }

    models = {
        str(row.get("judge_model"))
        for row in ok_rows
        if row.get("judge_model")
    }
    frames = {
        int(row["n_frames"])
        for row in ok_rows
        if row.get("n_frames") is not None
    }
    summary: dict[str, Any] = {
        "protocol": PROTOCOL,
        "num_qa": len(rows),
        "num_ok": len(ok_rows),
        "num_error": sum(1 for row in rows if row.get("status") not in {None, "ok"}),
        "num_joinable": len(joinable),
        "num_original_correct": n_original_correct,
        "num_retained": n_retained,
        "num_rendered_correct": n_rendered_correct,
        "retention_rate": retention_rate,
        "rendered_accuracy": rendered_accuracy,
        "original_accuracy": original_accuracy,
        "by_question_type": by_type,
        "judge_model": judge_model
        or (next(iter(models)) if len(models) == 1 else sorted(models)),
        "n_frames": n_frames
        if n_frames is not None
        else (next(iter(frames)) if len(frames) == 1 else sorted(frames)),
        "num_scenes": len({str(row.get("scene_name")) for row in ok_rows}),
    }
    if source:
        summary["source"] = source
    return summary


def load_answer_bank(path: Path) -> dict[str, dict[str, Any]]:
    """Load qa_id → answer row from a shared *.jsonl bank."""
    if not path.is_file():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(path):
        out[str(row["qa_id"])] = row
    return out
