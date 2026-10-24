"""Loopback-only scripted API for full-stack offline tests, never an AI result."""

import argparse
import json
from pathlib import Path
import sys
import threading
import time

from fastapi import FastAPI, Request
import uvicorn


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--records", type=Path)
    parser.add_argument("--fail-at", type=int, default=0)
    args = parser.parse_args()
    plan = json.loads((args.plan / "plan.json").read_text(encoding="utf-8"))
    state = {"events": {}, "calls": 0, "active": 0, "peak": 0}
    lock = threading.Lock()
    records = args.records or args.plan.parent / "run/records"
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"offline_stub": True, "calls": state["calls"], "peak": state["peak"]}

    @app.post("/chat/completions")
    def completion(body: dict, request: Request):
        from matraix.journeys.programmatic import reference_trial

        with lock:
            state["calls"] += 1
            call_number = state["calls"]
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        time.sleep(0.03)  # Deterministic overlap probe, not a model speed estimate.
        with lock:
            state["active"] -= 1
        if args.fail_at and call_number >= args.fail_at:
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=429, content={"error": "offline injected stop"}
            )
        if body["model"] == "offline-put":
            card = json.loads(body["messages"][2]["content"])
            assert card["case_id"] in {c["id"] for c in plan["cases"]}
            message = {
                "role": "assistant",
                "content": '{"act":"continue","style":"balanced"}',
            }
            finish = "stop"
        elif body["model"] == "offline-sut":
            session, index = request.headers["X-Client-Request-Id"].rsplit("-", 1)
            with lock:
                if session not in state["events"]:
                    case = json.loads(
                        (records / session / "binding.json").read_text(encoding="utf-8")
                    )["case"]
                    state["events"][session] = reference_trial(case)["events"]
                event = state["events"][session][int(index) - 1]
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "event-" + str(call_number),
                        "type": "function",
                        "function": {
                            "name": event["name"],
                            "arguments": json.dumps(event["arguments"]),
                        },
                    }
                ],
            }
            finish = "tool_calls"
        else:
            raise ValueError("Only explicitly offline models accepted")
        return {
            "id": "offline-" + str(call_number),
            "model": body["model"],
            "choices": [{"finish_reason": finish, "message": message}],
            "usage": {"total_tokens": 0},
            "offline_stub": True,
        }

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
