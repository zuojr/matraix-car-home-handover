#!/usr/bin/env bash
# Generic web experiment verifier entrypoint.
#
# Behavioral by default: the verifier reads experiment.json (outputArtifact +
# signals) from the task dir and reflects the persona's choice/feedback. No
# per-level ground truth is required.
#
# Verifier location resolves in order:
#   1) $EXPERIMENTS_VERIFIERS (explicit, e.g. mounted into the trial image)
#   2) sibling task-spec/verifiers relative to this repo checkout
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TASK_DIR="$(dirname "$HERE")"

VERIFIERS="${EXPERIMENTS_VERIFIERS:-}"
if [[ -z "$VERIFIERS" ]]; then
  VERIFIERS="$(cd "$TASK_DIR/../.." && pwd)/task-spec/verifiers"
fi

export EXPERIMENTS_TASK_DIR="$TASK_DIR"
export PYTHONPATH="$VERIFIERS:${PYTHONPATH:-}"

python3 "$VERIFIERS/web_generic.py"
