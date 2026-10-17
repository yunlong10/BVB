# BVB video-reconstruction tasks for Harbor

This folder turns BVB's idea, rebuilding a real video as an animated Blender scene, into
[Harbor](https://github.com/laude-institute/harbor) tasks. Anyone can make a task from their
own video: record a room, write questions about it, provide a reference scene, and run one
command.

```text
harbor/
  make_task.py            video + questions + golden .blend  ->  a complete Harbor task
  template/               files every task shares (agent image, verifier image, grader, oracle)
  examples/
    office_questions.jsonl  the 15 questions for the office sample, as a format reference
    office_make_golden.py   the hand fixes that turned GPT-6 Astra's scene into the office golden
  tasks/
    bvb-img-3011-office/  the first task: a 24-second handheld video of an open-plan office
```

## What a task asks and how it is graded

The agent gets the video at `/app/video.mp4` in a container with Blender 4.2, Python, and
FFmpeg, and must save `/app/result.blend`. The scene has to be built from Blender primitives,
with a scene camera keyed to retrace the video's camera path. The full rules are in each
task's `instruction.md`.

The verifier runs in a separate container that the agent never sees. It holds the questions,
the judge's answers on the source video, and the grader:

1. **Gate.** `/app/result.blend` must exist, not be a symlink, open in Blender, have a scene
   camera, and contain at least 10 mesh objects. Otherwise the reward is 0.
2. **Render.** The scene camera is rendered with BVB's renderer (EEVEE, 512 px) at 16 evenly
   spaced points across the timeline, exactly the frames the judge sees. BVB renders 64 and
   samples 16 of them; rendering only those 16 keeps the verifier fast on CPU.
3. **Judge.** `gpt-5.4-mini` answers each question from those 16 frames, using BVB's prompt and
   answer matching. Each question is asked 5 times and the majority decides.
4. **Reward** = Dual VQA retention: of the questions the judge answered correctly on the
   *source* video, the share it still answers correctly on the render. 0 to 1.

The source-side answers are computed once by `make_task.py` and baked into the verifier
(`tests/grader/source_answers.jsonl`). Questions the judge gets wrong on the real video can't
measure anything, so they're dropped automatically.

The render, frame sampling, prompt, and answer matching are BVB's own code
(`eval/render_blend_video.py`, `dual_vqa_metric.py`, `dual_vqa_scoring.py`), copied unchanged
into each task's `tests/grader/`.

### How this differs from the BVB paper protocol

These are Harbor tasks *based on* BVB. Their rewards aren't comparable to the BVB leaderboard.

| | BVB paper | These tasks |
|---|---|---|
| Agent | Mini-BVB harness with a `frames` tool | Any Harbor agent; it extracts frames itself with FFmpeg |
| Questions | 5,130 VSI-Bench questions over 288 videos | ~15 author-written questions per video |
| Score | Overall = sqrt-mean of Dual VQA and Latent Similarity (V-JEPA) | Dual VQA retention only |
| Judge | 1 answer per question | Majority of 5 answers per question |
| Instructions | Mini-BVB system prompt | Same scene rules, plus a note to keep camera angles continuous across ±180° |

Latent Similarity is left out on purpose. On the office video it rated two unrelated real
videos (80.9 and 86.4) above Kimi K3's reconstruction of the right room (71.1). It also needs a
7.6 GB model and ideally a GPU in the verifier.

## Make your own task

You need: Docker, [Harbor](https://github.com/laude-institute/harbor) (`harbor`), FFmpeg,
the BVB Stage-1 venv (`sandbox/.venv`, see the main README), and `OPENAI_API_KEY` in your
environment or in the repo's `.env`.

### 1. Record the video

- One indoor room, 20–60 s, in a single continuous take.
- Walk slowly with the phone and show each wall and the main furniture at least once.
  Avoid whip-pans and zooming.
- Use steady light, and keep people out of frame if you can.
- Any format FFmpeg reads works. `make_task.py` converts it to 30 fps, no audio, 640 px on the
  long side.

### 2. Write the questions

Write a JSONL file with one question per line, in BVB / VSI-Bench format.
`examples/office_questions.jsonl` is a complete example.

```json
{"id": 1, "question_type": "object_rel_direction", "question": "On the first desk shown up close, is the soda can to the left or the right of the laptop?", "ground_truth": "B", "options": ["A. left", "B. right"]}
{"id": 2, "question_type": "object_counting", "question": "How many chair(s) are in the window corner?", "ground_truth": "2", "options": null}
```

Rules that make the judge reliable:

- **Put the choices in the question text.** The judge sees only the `question` string, never
  `options`. It answers in a few words, which are matched to the option text.
- **Keep option text short**, one to four words ("left", "roller shades"), so a short answer
  matches it.
- **Numeric types** (`object_counting`, `object_size_estimation`, `room_size_estimation`,
  `object_abs_distance`) take a number as `ground_truth` and `options: null`. Counts must
  match exactly; sizes and distances within 20%.
- **Ask about things a single frame or a short stretch shows clearly.** The judge sees only
  16 frames. In the office sample it consistently failed "how many chairs", "how much of the
  office does the camera cover", and an appearance-order question on the real video, and it
  described the camera height in its own words instead of an option ("standing height"), so
  those four are dropped and 11 of 15 count.
- **Avoid wording that depends on viewpoint or sequence the judge has to infer.** "The first
  desk shown up close" and "after looking at the floor, which way does the camera turn first"
  split the judge's votes on a correct scene. "Which side of the open laptop is the red soda can
  on, as shown in the video" and "in the first few seconds, does the camera show the windows or
  the whiteboard" were answered correctly 5 of 5 times.
- **Cover the three areas a reconstruction can get wrong:** perspective and camera path (where
  the camera points first, which way it turns), objects (what is present, materials, counts),
  and positioning (left/right, next to, in rows vs. cubicles).
- Aim for 12–20 questions. With fewer than 8 counted questions, one judge flip moves the
  reward by more than 0.12.

### 3. Make the golden solution

The golden scene is the reference reconstruction that the oracle submits. Two ways to get one:

- **Build it from a strong agent's attempt.** Run a model on the task (step 5) or with the BVB
  harness, then fix what it got wrong by hand in a Blender script. The office golden is GPT-6
  Astra's scene plus [`examples/office_make_golden.py`](examples/office_make_golden.py). That script
  rotates a desk, adds a missing dual-monitor desk, lowers dividers, fixes the book's logo,
  and unwraps a camera spin.
- **Build it yourself** in Blender, following the same scene rules the agent gets.

**Save the golden with Blender 4.2.** The verifier runs Blender 4.2, which can't open files saved
by Blender 5.x (`make_task.py` refuses them). If you edit in a newer Blender, re-run your edit
script with Blender 4.2, for example in the BVB sandbox image:

```bash
docker run --rm -v "$PWD":/work bvb-sandbox:latest \
  blender -b /work/model_attempt.blend --python /work/my_fixes.py -- /work/golden.blend
```

Compare its render with the video side by side before you use it.

### 4. Generate the task

```bash
sandbox/.venv/bin/python harbor/make_task.py --name my-kitchen \
  --video ~/Desktop/kitchen.mov \
  --questions my_kitchen_questions.jsonl \
  --golden my_kitchen_golden.blend \
  --author "Your Name"
```

This writes `harbor/tasks/bvb-my-kitchen/`. It checks the question file, converts the video,
asks the judge each question 5 times on the source video, and prints which questions count.
Reword any dropped question you care about and run it again with `--force`.

Useful options: `--votes`, `--min-meshes`, `--agent-timeout-min`, `--golden-floor`, and
`--source-answers` to reuse an existing answer bank without calling the judge.

### 5. Check the task, then run models

```bash
set -a; source .env; set +a                  # the verifier reads OPENAI_API_KEY from your shell
harbor run -y -p harbor/tasks/bvb-my-kitchen -a oracle -o harbor/jobs   # golden must reach the floor (default 0.8)
harbor run -y -p harbor/tasks/bvb-my-kitchen -a nop -o harbor/jobs      # no submission must score 0
harbor run -y -p harbor/tasks/bvb-my-kitchen -a claude-code -m anthropic/claude-opus-5-5 \
  --allow-agent-host api.anthropic.com -o harbor/jobs
```

Each trial's verifier output is in `harbor/jobs/<job>/<trial>/verifier/`:

- `reward.txt`: the reward.
- `reward_details.json`: every question with the judge's answers on the source and the render,
  and whether it was kept.
- `render.mp4`: what the judge saw.

## Task layout

```text
bvb-<name>/
  instruction.md          agent prompt: video path, scene rules, camera animation
  task.toml               artifact /app/result.blend; agent offline; verifier separate,
                          allowed only api.openai.com, OPENAI_API_KEY passed from the host
  environment/            agent image: Blender 4.2 + Xvfb + FFmpeg, video at /app/video.mp4
  solution/
    solve.sh              oracle: copies golden.blend to /app/result.blend
    golden.blend
  tests/                  verifier image (never shipped to the agent)
    Dockerfile            Blender 4.2 + openai + opencv; grader baked at /opt/grader
    test.sh               entry point; a missing API key fails the run instead of scoring 0
    grader/
      grade.py            gate, render, judge, reward
      config.json         judge model, votes, frames, render settings, mesh minimum
      questions.jsonl     the held-back questions
      source_answers.jsonl  the judge's fixed answers on the source video
      render_blend_video.py, dual_vqa_metric.py, dual_vqa_scoring.py   BVB code, unchanged
```

## Known limits

- **The judge is an API model.** The verifier needs network access to `api.openai.com` and an
  API key, unlike fully offline Harbor verifiers. Grading one submission costs a few cents.
- **Votes reduce judge noise but don't remove it.** Changing a scene changes the frames the
  judge sees, and some questions are inherently borderline. Re-run marginal results before
  calling a task or a model broken.
- **Emulation on Apple Silicon.** The images are linux/amd64 (Blender's Linux build), so on a
  Mac they run under emulation with software rendering. Builds and renders work but are slow:
  a few minutes per rendered frame there, far less on an x86 machine.
- **EEVEE needs EGL.** Both images install Mesa's EGL libraries. BVB's own `sandbox/Dockerfile`
  doesn't, so an EEVEE render inside the stock BVB sandbox aborts with a missing `libEGL.so.1`.
