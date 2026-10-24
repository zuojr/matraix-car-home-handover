"""Standard HTTP chatbot sidecar over a private simulator and model API."""

from copy import deepcopy
import json
import os
from pathlib import Path
import threading

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict
import httpx

from .api import APIClient, ModelConfig
from .programmatic import SYSTEM
from .cohort import write_new
from .put_protocol import parse_act


class SimulatorClient:
    def __init__(self, base_url, token, transport=None):
        self.http = httpx.Client(
            base_url=base_url,
            timeout=150,
            transport=transport,
            headers={"X-Journey-Control": token},
            trust_env=False,
        )

    def request(self, method, path, body=None):
        r = self.http.request(method, path, json=body)
        r.raise_for_status()
        return r.json()

    def create(self, scenario):
        return self.request("POST", "/internal/sessions", {"scenarioId": scenario})

    def contract(self):
        return self.request("GET", "/internal/contract")

    def schemas(self, sid):
        return self.request("GET", f"/internal/sessions/{sid}/schemas")

    def execute(self, sid, name, args):
        return self.request(
            "POST",
            f"/internal/sessions/{sid}/actions",
            {"name": name, "arguments": args},
        )

    def finish(self, sid):
        return self.request("POST", f"/internal/sessions/{sid}/finish")

    def reference(self, sid):
        return self.request("POST", f"/internal/sessions/{sid}/reference")


class Gateway:
    def __init__(
        self,
        simulator,
        directory,
        *,
        mode="reference",
        client_factory=None,
        max_sut_calls=160,
        sut_config=None,
    ):
        self.simulator, self.directory, self.mode = simulator, Path(directory), mode
        self.client_factory = client_factory
        self.max_sut_calls = max_sut_calls
        self.sessions, self.guard = {}, threading.Lock()
        self.stopped = False
        self.sut_config = sut_config

    def turn(self, text, scenario, sid=""):
        act = parse_act(text)
        with self.guard:
            if self.stopped:
                raise RuntimeError("Study stopped after an infrastructure/model error")
            if sid:
                if (
                    sid not in self.sessions
                    or self.sessions[sid]["scenario"] != scenario
                ):
                    raise ValueError("Session/scenario mismatch")
                state = self.sessions[sid]
            else:
                opened = self.simulator.create(scenario)
                sid = opened["sessionId"]
                state = {
                    "scenario": scenario,
                    "messages": [
                        {"role": "system", "content": SYSTEM},
                        {
                            "role": "user",
                            "content": json.dumps(
                                opened["start"],
                                ensure_ascii=False,
                                separators=(",", ":"),
                                sort_keys=True,
                            ),
                        },
                    ],
                    "pending": None,
                    "terminal": False,
                    "turns": [],
                    "calls": 0,
                    "lock": threading.Lock(),
                }
                self.sessions[sid] = state
        with state["lock"]:
            if state["terminal"]:
                raise ValueError("No replay or extra operation after terminal state")
            if self.mode == "reference":
                self.simulator.reference(sid)
                reply, pending, terminal = (
                    "Offline reference only; not measured AI or persona behavior.",
                    None,
                    True,
                )
            elif act["act"] == "stop":
                self.simulator.finish(sid)
                if "client" in state:
                    state["client"].close()
                reply, pending, terminal = "已结束本次交互。", None, True
            else:
                try:
                    if state["pending"]:
                        old = state.pop("pending")
                        response = deepcopy(old["result"])
                        response["user_act"] = act["act"]
                        response["style"] = act.get("style", "balanced")
                        state["messages"].append(
                            {
                                "role": "tool",
                                "tool_call_id": old["call_id"],
                                "content": json.dumps(response, ensure_ascii=False),
                            }
                        )
                        state["messages"].extend(old.get("deferred", []))
                        state["pending"] = None
                    else:
                        state["messages"].append(
                            {
                                "role": "user",
                                "content": "请澄清当前安排。"
                                if act["act"] == "clarify"
                                else "请继续按本次要求处理。",
                            }
                        )
                    reply, pending, terminal = self._drive(sid, state)
                except Exception:
                    if "client" in state:
                        state["client"].close()
                    self.stopped = True
                    from .cohort import write_new

                    stop = self.directory / "STOP.json"
                    if not stop.exists():
                        write_new(
                            stop,
                            {
                                "sessionId": sid,
                                "automatic_retry": False,
                                "reason": "model_or_transport_failure",
                            },
                        )
                    raise
            state["terminal"] = terminal
            if terminal:
                # Keep public turns and durable API artifacts, release large
                # private prompt histories/closed clients between episodes.
                state["messages"] = []
                state.pop("client", None)
            turn = {
                "index": len(state["turns"]) + 1,
                "userMessage": text,
                "assistantReply": reply,
                "pendingUserRequest": pending,
                "terminal": terminal,
            }
            state["turns"].append(turn)
            return {
                "sessionId": sid,
                "reply": reply,
                "turn": turn,
                "pendingUserRequest": pending,
                "terminal": terminal,
            }

    def _drive(self, sid, state):
        if "client" not in state:
            state["client"] = self.client_factory(sid)
        tools = self.simulator.schemas(sid)
        while state["calls"] < self.max_sut_calls:
            if self.stopped:
                raise RuntimeError(
                    "Coordinator requested a drain; no additional API call"
                )
            state["calls"] += 1
            msg = state["client"].call(state["messages"], tools=tools)
            state["messages"].append(
                {k: v for k, v in msg.items() if k in {"role", "content", "tool_calls"}}
            )
            calls = msg.get("tool_calls") or []
            parsed = []
            try:
                if not isinstance(calls, list) or not 1 <= len(calls) <= 32:
                    raise ValueError("Expected 1-32 tool calls")
                ids = set()
                for call in calls:
                    name = call["function"]["name"]
                    args = json.loads(call["function"]["arguments"])
                    call_id = call["id"]
                    if (
                        not isinstance(name, str)
                        or not isinstance(args, dict)
                        or not isinstance(call_id, str)
                        or not call_id
                        or call_id in ids
                        or call.get("type", "function") != "function"
                    ):
                        raise ValueError("Malformed or duplicate tool call")
                    ids.add(call_id)
                    parsed.append((call_id, name, args))
            except (ValueError, KeyError, TypeError):
                # Malformed protocol is a SUT failure, not a hidden execution.
                # No operations from a batch are performed.
                operations = []
                for call in calls if isinstance(calls, list) else []:
                    try:
                        operations.append(
                            {
                                "tool": call["function"]["name"],
                                "arguments": json.loads(call["function"]["arguments"]),
                            }
                        )
                    except (ValueError, KeyError, TypeError):
                        operations.append({"tool": "malformed", "arguments": {}})
                self.simulator.execute(
                    sid, "__rejected_batch__", {"operations": operations}
                )
                self.simulator.finish(sid)
                state["client"].close()
                return "本次响应未满足结构化操作协议。", None, True
            batch = self.directory / sid / "tool-batches" / f"{state['calls']:04d}"
            write_new(
                batch / "order.json",
                {"calls": calls, "execution": "ordered_with_barriers"},
            )
            for position, (call_id, name, args) in enumerate(parsed):
                if state.get("tool_operations", 0) >= self.max_sut_calls:
                    self._defer(batch, parsed, position, "operation_budget_exhausted")
                    self.simulator.finish(sid)
                    state["client"].close()
                    return "操作预算已用完。", None, True
                state["tool_operations"] = state.get("tool_operations", 0) + 1
                result = self.simulator.execute(sid, name, args)
                write_new(
                    batch / f"{position:03d}.json",
                    {
                        "tool_call_id": call_id,
                        "tool": name,
                        "arguments": args,
                        "executed": True,
                        "result": result,
                    },
                )
                failure = result.get("status") == "FAILURE"
                barrier = failure or name in {
                    "ask_user",
                    "confirm_operation",
                    "respond_to_user",
                    "submit_plan",
                }
                deferred = (
                    self._defer(
                        batch,
                        parsed,
                        position + 1,
                        "previous_tool_failed" if failure else "interaction_boundary",
                    )
                    if barrier
                    else []
                )
                if (
                    name in {"ask_user", "confirm_operation"}
                    and result.get("status") == "SUCCESS"
                ):
                    pending = {
                        "request": name,
                        "arguments": args,
                        "authoritativeResult": result,
                    }
                    state["pending"] = {
                        "call_id": call_id,
                        "result": result,
                        "deferred": deferred,
                    }
                    return "请确认以下本次信息。", pending, False
                state["messages"].append(self._tool_message(call_id, result))
                state["messages"].extend(deferred)
                if name == "respond_to_user" and result.get("status") == "SUCCESS":
                    return args["message"], None, False
                if name == "submit_plan" and result.get("submitted"):
                    self.simulator.finish(sid)
                    state["client"].close()
                    return "本次操作已提交。", None, True
                if barrier:
                    break
        self.simulator.finish(sid)
        state["client"].close()
        return "交互预算已用完。", None, True

    @staticmethod
    def _tool_message(call_id, result):
        return {
            "role": "tool",
            "tool_call_id": call_id,
            "content": json.dumps(result, ensure_ascii=False),
        }

    def _defer(self, batch, parsed, start, reason):
        messages = []
        for position in range(start, len(parsed)):
            call_id, name, args = parsed[position]
            result = {
                "status": "NOT_EXECUTED",
                "reason": reason,
                "instruction": "Read actual results/user feedback before issuing a new operation.",
            }
            write_new(
                batch / f"{position:03d}.json",
                {
                    "tool_call_id": call_id,
                    "tool": name,
                    "arguments": args,
                    "executed": False,
                    "result": result,
                },
            )
            messages.append(self._tool_message(call_id, result))
        return messages


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str
    sessionId: str = ""
    applicationContext: str


def create_app(gateway):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app):
        yield
        for state in gateway.sessions.values():
            if "client" in state:
                state["client"].close()
        if hasattr(gateway.simulator, "http"):
            gateway.simulator.http.close()

    app = FastAPI(lifespan=lifespan)

    from fastapi import Header
    import secrets

    def control(x_journey_control):
        expected = os.getenv("JOURNEY_CONTROL_TOKEN", "")
        if not expected or not secrets.compare_digest(expected, x_journey_control):
            raise HTTPException(403, "Private controller interface")

    @app.post("/internal/drain")
    def drain(x_journey_control: str = Header(default="")):
        control(x_journey_control)
        gateway.stopped = True
        return {
            "active_turns": sum(s["lock"].locked() for s in gateway.sessions.values())
        }

    @app.get("/internal/status")
    def status(x_journey_control: str = Header(default="")):
        control(x_journey_control)
        return {
            "active_turns": sum(s["lock"].locked() for s in gateway.sessions.values())
        }

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": gateway.mode}

    @app.get("/ready")
    def ready():
        from .cohort import code_contract, digest
        from .ledger import binding

        private = gateway.simulator.contract()
        if private["mode"] != gateway.mode or gateway.stopped:
            raise HTTPException(503, "Sidecar contract mismatch or stopped")
        return {
            "status": "ready",
            "mode": gateway.mode,
            "plan_sha256": private["plan_sha256"],
            "source_contract_sha256": digest(code_contract()),
            "sut_config": gateway.sut_config,
            "max_sut_calls_per_case": gateway.max_sut_calls,
            "request_accounting": binding(
                os.environ["JOURNEY_REQUEST_LEDGER"],
                os.getenv("JOURNEY_REQUEST_LIMIT", "0"),
            )
            if os.getenv("JOURNEY_REQUEST_LEDGER")
            else None,
            "capabilities": ["text_chat", "structured_user_acts"],
        }

    @app.post("/v1/messages")
    def messages(body: Message):
        try:
            return gateway.turn(body.message, body.applicationContext, body.sessionId)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            raise HTTPException(400, str(exc)) from None
        except Exception:
            raise HTTPException(
                503, "Study stopped; inspect private receipts; no automatic retry"
            ) from None

    @app.get("/v1/conversation")
    def conversation(sessionId: str):
        if sessionId not in gateway.sessions:
            raise HTTPException(404, "Unknown session")
        state = gateway.sessions[sessionId]
        messages = []
        for turn in state["turns"]:
            messages.extend(
                [
                    {"role": "user", "content": turn["userMessage"]},
                    {"role": "assistant", "content": turn["assistantReply"]},
                ]
            )
        return {"sessionId": sessionId, "messages": messages, "turns": state["turns"]}

    return app


def factory():
    mode = os.getenv("JOURNEY_MODE", "reference")
    config = (
        ModelConfig.from_env("sut").validate()
        if mode in {"model", "validation"}
        else None
    )
    if config and not os.getenv(config.key_env):
        raise ValueError("Configured SUT API credential is missing")
    root = Path(os.getenv("JOURNEY_API_RECORDS", "/api-records"))
    simulator = SimulatorClient(
        os.getenv("JOURNEY_SIMULATOR_URL", "http://simulator:8001"),
        os.environ["JOURNEY_CONTROL_TOKEN"],
    )
    return create_app(
        Gateway(
            simulator,
            root,
            mode=mode,
            client_factory=(lambda sid: APIClient(config, root / sid))
            if config
            else None,
            sut_config=config.public() if config else None,
            max_sut_calls=int(os.getenv("JOURNEY_MAX_SUT_CALLS", "160")),
        )
    )
