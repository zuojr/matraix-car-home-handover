"""Private native simulator API. One spawned process per active trial."""

from contextlib import asynccontextmanager
from copy import deepcopy
import json
import multiprocessing as mp
import os
from pathlib import Path
import threading
import uuid

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict

from .cohort import VERSION, digest, make_case, write_new


def worker(pipe, case):
    from .programmatic import Session, reference_trial

    try:
        session = Session(case)
        pipe.send({"ok": True})
        while True:
            command, data = pipe.recv()
            if command == "close":
                break
            try:
                if command == "start":
                    result = session.public_start()
                elif command == "schemas":
                    result = session.schemas()
                elif command == "execute":
                    result = (
                        session.reject_batch(data["arguments"]["operations"])
                        if data["name"] == "__rejected_batch__"
                        else session.execute(data["name"], data["arguments"])
                    )
                elif command == "record":
                    result = session.record(data.get("mode", "model"))
                elif command == "reference":
                    result = reference_trial(case)
                else:
                    raise ValueError("Unknown private operation")
                pipe.send({"ok": True, "result": result})
            except Exception as exc:
                pipe.send({"ok": False, "error": type(exc).__name__ + ": " + str(exc)})
    except Exception as exc:
        pipe.send({"ok": False, "error": type(exc).__name__ + ": " + str(exc)})
    finally:
        pipe.close()


class IsolatedTrial:
    def __init__(self, case, timeout=120):
        ctx = mp.get_context("spawn")
        self.pipe, child = ctx.Pipe()
        self.process = ctx.Process(target=worker, args=(child, case), daemon=True)
        self.lock, self.timeout = threading.Lock(), timeout
        self.process.start()
        child.close()
        try:
            self._receive()
        except Exception:
            self.close()
            raise

    def _receive(self):
        if not self.pipe.poll(self.timeout):
            self.process.terminate()
            self.process.join(5)
            raise TimeoutError("Native worker timed out; no retry")
        data = self.pipe.recv()
        if not data["ok"]:
            raise RuntimeError(data["error"])
        return data.get("result")

    def call(self, command, data=None):
        with self.lock:
            if not self.process.is_alive():
                raise RuntimeError("Native trial is no longer active")
            self.pipe.send((command, data or {}))
            return self._receive()

    def close(self):
        if self.process.is_alive():
            try:
                self.pipe.send(("close", {}))
            except (OSError, EOFError):
                # A startup failure may close the child pipe before the parent
                # drains. Preserve that original failure and still reap it.
                pass
            self.process.join(5)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(5)
        self.pipe.close()


class Manager:
    def __init__(
        self,
        root,
        scenarios,
        *,
        mode="reference",
        max_active=2,
        trial_factory=IsolatedTrial,
        plan_sha256=None,
    ):
        if mode not in {"reference", "model", "validation"}:
            raise ValueError("Explicit execution mode required")
        self.root, self.scenarios, self.mode = Path(root), deepcopy(scenarios), mode
        self.plan_sha256 = plan_sha256
        self.max_active, self.factory = max_active, trial_factory
        self.active, self.case_by_id, self.lock = {}, {}, threading.Lock()
        self.closed = False
        self.peak_active = 0
        for p in self.root.glob("*/binding.json"):
            b = json.loads(p.read_text(encoding="utf-8"))
            self.case_by_id[b["sessionId"]] = b["case"]

    def create(self, scenario):
        with self.lock:
            if self.closed:
                raise ValueError("Native manager has been drained")
            if scenario not in self.scenarios:
                raise ValueError("Scenario is not in the frozen plan")
            if len(self.active) >= self.max_active:
                raise RuntimeError("Native worker capacity reached")
            c = deepcopy(self.scenarios[scenario])
            if any(p.get("id") == c["id"] for p in self.case_by_id.values()):
                raise ValueError("Planned episode already attempted; no retries")
            sid = str(uuid.uuid4())
            # Persist the attempt before spawning: a failed worker startup is
            # missing evidence, not permission to try the same episode again.
            self.case_by_id[sid] = c
            write_new(
                self.root / sid / "binding.json",
                {
                    "protocol": VERSION,
                    "sessionId": sid,
                    "scenarioId": scenario,
                    "case_sha256": digest(c),
                    "case": c,
                    "mode": self.mode,
                },
            )
            native = self.factory(c)
            self.active[sid] = native
            self.peak_active = max(self.peak_active, len(self.active))
            return sid, native.call("start")

    def get(self, sid):
        if sid not in self.active:
            raise ValueError("Unknown or terminal session")
        return self.active[sid]

    def record(self, sid, *, reference=False, terminal=False):
        native = self.get(sid)
        if reference and self.mode != "reference":
            raise ValueError("Reference policy is never model evidence")
        row = native.call("reference" if reference else "record", {"mode": self.mode})
        c = self.case_by_id[sid]
        row.update(
            protocol=VERSION,
            evidence_type={
                "reference": "reference_only",
                "model": "model",
                "validation": "api_validation",
            }[self.mode],
            source_persona_id=c.get("source_persona_id", "offline-fixture"),
            persona_binding=c.get("persona_binding", digest(c)),
            sessionId=sid,
        )
        if terminal:
            write_new(self.root / sid / "record.json", row)
            with self.lock:
                self.active.pop(sid).close()
        return row

    def execute(self, sid, data):
        result = self.get(sid).call("execute", data)
        partial = self.record(sid)
        path = self.root / sid / "partial.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(partial, ensure_ascii=False, allow_nan=False), encoding="utf-8"
        )
        temp.replace(path)
        return result

    def close(self):
        self.closed = True
        for trial in list(self.active.values()):
            trial.close()
        self.active.clear()


def reference_scenarios():
    return {
        f"{domain}-{i}-{'boundary' if edge else 'main'}-{condition}": make_case(
            domain,
            ("J" if domain == "car" else "H") + str(i),
            condition=condition,
            boundary=edge,
        )
        for domain in ("car", "home")
        for i in range(1, 7)
        for edge in (False, True)
        for condition in ("C1", "C2", "C3", "C4")
    }


class Creation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenarioId: str


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    arguments: dict


def create_app(manager, token):
    if not token:
        raise ValueError("Private control credential required")

    @asynccontextmanager
    async def lifespan(app):
        yield
        manager.close()

    app = FastAPI(lifespan=lifespan)

    def authorize(x_journey_control: str = Header(default="")):
        import secrets

        if not secrets.compare_digest(x_journey_control, token):
            raise HTTPException(403, "Private simulator interface")

    from fastapi import Depends

    private = [Depends(authorize)]

    @app.get("/internal/contract", dependencies=private)
    def contract():
        return {"mode": manager.mode, "plan_sha256": manager.plan_sha256}

    @app.post("/internal/drain", dependencies=private)
    def drain():
        manager.close()
        return {"active_workers": len(manager.active)}

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "mode": manager.mode,
            "active_workers": len(manager.active),
            "peak_active_workers": manager.peak_active,
        }

    @app.post("/internal/sessions", dependencies=private)
    def create(body: Creation):
        try:
            sid, start = manager.create(body.scenarioId)
            return {"sessionId": sid, "start": start}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from None

    @app.get("/internal/sessions/{sid}/schemas", dependencies=private)
    def schemas(sid: str):
        return manager.get(sid).call("schemas")

    @app.post("/internal/sessions/{sid}/actions", dependencies=private)
    def execute(sid: str, body: Action):
        return manager.execute(sid, body.model_dump())

    @app.post("/internal/sessions/{sid}/finish", dependencies=private)
    def finish(sid: str):
        return manager.record(sid, terminal=True)

    @app.post("/internal/sessions/{sid}/reference", dependencies=private)
    def reference(sid: str):
        if manager.mode != "reference":
            raise HTTPException(403, "Reference policy disabled")
        return manager.record(sid, reference=True, terminal=True)

    return app


def factory():
    mode = os.getenv("JOURNEY_MODE", "reference")
    plan = None
    if mode in {"model", "validation"}:
        from .cohort import load_plan

        plan = load_plan(Path(os.environ["JOURNEY_PLAN_PATH"]))
        if mode == "model" and (
            plan["fixture_only"]
            or plan["purpose"] == "offline"
            or plan["purpose"] == "formal"
            and not plan["formal_spec_frozen"]
        ):
            raise ValueError(
                "Only a real, eligible, separately frozen run may use model mode"
            )
        if mode == "validation" and plan["purpose"] != "validation":
            raise ValueError(
                "API validation requires an explicitly separate validation plan"
            )
        scenarios = {c["id"]: c for c in plan["cases"]}
        scenario = os.getenv("JOURNEY_SCENARIO_ID")
        if scenario:
            scenarios = {scenario: scenarios[scenario]}
    else:
        scenarios = reference_scenarios()
    return create_app(
        Manager(
            os.getenv("JOURNEY_RECORDS", "/records"),
            scenarios,
            mode=mode,
            max_active=int(os.getenv("JOURNEY_MAX_WORKERS", "2")),
            plan_sha256=digest(plan) if plan else None,
        ),
        os.environ["JOURNEY_CONTROL_TOKEN"],
    )
