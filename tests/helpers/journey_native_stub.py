"""Loopback-only Chat Completions fixture for actual Harbor acceptance.

No model, stored answer, credentials, or historical experiment is involved.
"""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading

FAIL_REQUESTS = False


def completion(body):
    if not body.get("tools"):
        return {
            "role": "assistant",
            "content": '{"act":"continue","style":"balanced"}',
        }, "stop"
    messages = body["messages"]
    observed = [m for m in messages if m["role"] == "tool"]
    calls = []

    def add(name, args):
        calls.append(
            {
                "id": f"t{len(messages)}-{len(calls)}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
        )

    if not observed:
        start = json.loads(next(m["content"] for m in messages if m["role"] == "user"))
        add("ask_user", {"topics": start["fact_topics"]})
    else:
        facts = json.loads(observed[0]["content"])["facts"]
        if len(observed) == 1:
            add(
                "set_climate_temperature",
                {"seat_zone": "DRIVER", "temperature": facts["driver_c"]},
            )
            add(
                "set_climate_temperature",
                {"seat_zone": "PASSENGER", "temperature": facts["passenger_c"]},
            )
        else:
            add("submit_plan", {"outcome": "complete"})
    return {"role": "assistant", "content": None, "tool_calls": calls}, "tool_calls"


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/chat/completions":
            self.send_error(404)
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if FAIL_REQUESTS:
            data = b'{"error":"scripted acceptance 429"}'
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        message, finish = completion(body)
        result = {
            "id": "scripted-acceptance",
            "model": "scripted-journey-test",
            "choices": [{"message": message, "finish_reason": finish}],
            "usage": {
                "prompt_tokens": 17,
                "completion_tokens": 9,
                "total_tokens": 26,
                "prompt_tokens_details": {"cached_tokens": 0},
            },
        }
        data = json.dumps(result).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def server(port):
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


if __name__ == "__main__":
    os.umask(0o002)
    p = argparse.ArgumentParser()
    p.add_argument("--sidecar", action="store_true")
    p.add_argument("--fail", action="store_true")
    args = p.parse_args()
    FAIL_REQUESTS = args.fail
    http = server(9011)
    if args.sidecar:
        threading.Thread(target=http.serve_forever, daemon=True).start()
        import uvicorn

        uvicorn.run(
            "matraix.journeys.chat:factory", factory=True, host="0.0.0.0", port=8000
        )
    else:
        http.serve_forever()
