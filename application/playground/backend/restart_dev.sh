#!/usr/bin/env bash
#
# restart_dev.sh — free the port, then run the Playground backend in the
# FOREGROUND. Foreground is deliberate; it is the one design that restarts
# cleanly in BOTH contexts:
#
#   • Interactive terminal:
#       bash application/playground/backend/restart_dev.sh
#     (Ctrl+C to stop; or append ' &' to detach — nohup survives a real tty.)
#
#   • Automated / managed runner (Cursor Shell tool, CI, etc.):
#       launch this as a MANAGED background job (block_until_ms=0), which keeps
#       it alive across the caller's session. Killing the port needs elevated
#       perms, so run it OUTSIDE the sandbox.
#
# Why not self-daemonize with nohup here? When started from an ephemeral session
# a nohup child gets reaped on teardown — the server "starts", answers a couple
# of requests, then dies, leaving the port dead while /api/health briefly 200s.
# So we do NOT background inside this script; the caller owns that decision.
#
# Success is proven by listener PID + /api/preflight, NOT by health==200 alone
# (a stale old process also answers 200). Use:  make sure ``lsof -ti tcp:PORT``
# is the NEW pid and preflight shows credentials OK.
set -uo pipefail

PORT="${PORT:-8765}"
VENV="${VENV:-.venv312}"
BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${BACKEND_DIR}/../../.." && pwd)"
cd "${REPO_ROOT}"

echo "[restart] repo      : ${REPO_ROOT}"
echo "[restart] port      : ${PORT}"
echo "[restart] env.local : application/playground/.env.local $( [ -f application/playground/.env.local ] && echo '(present)' || echo '(MISSING!)')"

echo "[restart] freeing :${PORT} ..."
lsof -ti "tcp:${PORT}" 2>/dev/null | xargs -r kill -9 2>/dev/null || true
pkill -f "uvicorn backend.api.app" 2>/dev/null || true

# Wait until the port is ACTUALLY free before starting (max ~10s), so we never
# launch a doomed second copy that dies with EADDRINUSE.
for _ in $(seq 1 20); do
  lsof -ti "tcp:${PORT}" >/dev/null 2>&1 || break
  sleep 0.5
done
if lsof -ti "tcp:${PORT}" >/dev/null 2>&1; then
  echo "[restart] ERROR: :${PORT} still held by PID(s) $(lsof -ti tcp:${PORT} 2>/dev/null | tr '\n' ' ')" >&2
  echo "[restart]        the kill did not take effect (needs elevated perms). Aborting" >&2
  echo "[restart]        so we don't leave a stale backend serving the old env." >&2
  exit 1
fi
echo "[restart] :${PORT} free — starting backend in foreground (loads .env.local) ..."

# Hand off to run_dev.sh in the foreground. The caller keeps it alive.
exec env "VENV=${VENV}" bash application/playground/backend/run_dev.sh
