#!/bin/bash
# Oracle for BVB video-reconstruction tasks: the reference scene is the authored
# golden.blend, so the oracle copies it to the declared artifact path. This
# exercises the grader alone; the task's golden floor is checked against it.
set -euo pipefail

cp /solution/golden.blend /app/result.blend
test -f /app/result.blend
