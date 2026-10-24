#!/bin/bash
# Verifier for BVB video-reconstruction tasks. Grades the declared artifact
# /app/result.blend against the held-back questions in /opt/grader (see grade.py):
# render the scene camera, ask the judge each question on the render, and write
# the Dual VQA retention to /logs/verifier/reward.txt.
set -uo pipefail

mkdir -p /logs/verifier

# A missing key is a verifier misconfiguration, not a failed submission: fail the
# run loudly instead of writing reward 0.
if [ -z "${OPENAI_API_KEY:-}" ]; then
    echo "verifier misconfigured: OPENAI_API_KEY is not set (export it before harbor run)" >&2
    exit 1
fi
for f in grade.py config.json questions.jsonl source_answers.jsonl dual_vqa_metric.py dual_vqa_scoring.py render_blend_video.py; do
    [ -f "/opt/grader/$f" ] || { echo "verifier misconfigured: missing /opt/grader/$f" >&2; exit 1; }
done

python3 /opt/grader/grade.py --candidate /app/result.blend --grader-dir /opt/grader --logs /logs/verifier
