"""Bounded independent API episodes; shared stop/ledger, no retries or answer cache."""

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED, CancelledError
from datetime import datetime, timezone
import os
from pathlib import Path
import threading
import time

import httpx

from .api import APIClient, ModelConfig
from .cohort import code_contract, digest, load_plan, write_new
from .prompts import PUT_SYSTEM, compact, put_messages, public_view

__all__ = ["PUT_SYSTEM", "run_api"]


def _case(
    case,
    index,
    plan,
    plan_path,
    chat_url,
    out,
    config,
    max_turns,
    chat_timeout,
    transport,
    actor_factory,
    cancelled,
    fail,
):
    if cancelled.is_set():
        raise CancelledError()
    started = time.monotonic()
    completed = False
    sid = ""
    client = None
    folder = out / case["id"]
    try:
        dialogue, audit = put_messages(case, plan, plan_path)
        if cancelled.is_set():
            raise CancelledError()
        write_new(
            folder / "attempt.json",
            {
                "case_id": case["id"],
                "dispatch_index": index,
                "started": True,
                "automatic_retry": False,
                "started_utc": datetime.now(timezone.utc).isoformat(),
            },
        )
        write_new(folder / "prompt-audit.json", audit)
        client = (
            actor_factory(case)
            if actor_factory
            else APIClient(config, folder / "put", cap=max_turns)
        )
        turns = []
        with httpx.Client(
            base_url=chat_url,
            timeout=chat_timeout,
            transport=transport,
            trust_env=False,
        ) as chat:
            for turn in range(max_turns):
                if cancelled.is_set():
                    raise CancelledError()
                response = client.call(dialogue)
                raw = response.get("content", "")
                from .chat import parse_act

                parse_act(raw)
                dialogue.append({"role": "assistant", "content": raw})
                if cancelled.is_set():
                    raise CancelledError()
                body = {
                    "message": raw,
                    "sessionId": sid,
                    "applicationContext": case["id"],
                }
                write_new(folder / f"{turn:03d}-request.json", body)
                r = chat.post("/v1/messages", json=body)
                r.raise_for_status()
                view = r.json()
                if sid and view["sessionId"] != sid:
                    raise ValueError("Server changed trial session")
                sid = view["sessionId"]
                turns.append(view["turn"])
                write_new(folder / f"{turn:03d}-response.json", view)
                if view["terminal"]:
                    break
                dialogue.append({"role": "user", "content": compact(public_view(view))})
            else:
                if cancelled.is_set():
                    raise CancelledError()
                r = chat.post(
                    "/v1/messages",
                    json={
                        "message": '{"act":"stop"}',
                        "sessionId": sid,
                        "applicationContext": case["id"],
                    },
                )
                r.raise_for_status()
                view = r.json()
                turns.append(view["turn"])
                write_new(
                    folder / "controller-stop.json",
                    {"reason": "persona_turn_budget", "response": view},
                )
        write_new(
            folder / "session.json",
            {
                "sessionId": sid,
                "case_id": case["id"],
                "source_persona_id": case["source_persona_id"],
            },
        )
        messages = []
        for turn in turns:
            messages.extend(
                [
                    {"role": "user", "content": turn["userMessage"]},
                    {"role": "assistant", "content": turn["assistantReply"]},
                ]
            )
        for name, value in {
            "transcript.json": {"sessionId": sid, "messages": messages, "turns": turns},
            "application_result.json": {
                "sessionId": sid,
                "applicationId": "journeys",
                "applicationContext": case["id"],
                "turnCount": len(turns),
            },
            "user_feedback.json": {
                "status": "not_collected",
                "reason": "Objective task benchmark; no extra feedback-model call",
            },
            "persona_meta.json": {
                "source_persona_id": case["source_persona_id"],
                "source_yaml_sha256": case["native_persona"]["source_yaml_sha256"],
                "persona_binding": case["persona_binding"],
            },
        }.items():
            write_new(folder / name, value)
        completed = True
        return case["id"]
    except CancelledError:
        raise
    except BaseException as exc:
        fail(case["id"], sid, exc)
        raise
    finally:
        if client is not None:
            client.close()
        if (folder / "attempt.json").exists():
            write_new(
                folder / "timing.json",
                {
                    "case_id": case["id"],
                    "duration_seconds": time.monotonic() - started,
                    "completed": completed,
                    "finished_utc": datetime.now(timezone.utc).isoformat(),
                },
            )


def run_api(
    plan_path,
    chat_url,
    out,
    *,
    execute=False,
    max_turns=64,
    transport=None,
    actor_factory=None,
    validation=False,
    expected_sut=None,
    chat_timeout=1200,
    concurrency=1,
):
    from .cohort import CONCURRENCY_VALUES

    if type(concurrency) is not int or concurrency not in CONCURRENCY_VALUES:
        raise ValueError("Validated concurrency values are 1, 2, 4 and 8")
    plan = load_plan(plan_path)
    if validation:
        if not execute or plan["purpose"] != "validation":
            raise ValueError("Explicit integration validation plan required")
    elif (
        not execute
        or plan["fixture_only"]
        or plan["purpose"] in {"offline", "validation"}
    ):
        raise ValueError("Explicit execution and real native personas required")
    if plan["purpose"] == "formal" and not plan["formal_spec_frozen"]:
        raise ValueError("Formal sample size and statistical spec are not frozen")
    out = Path(out)
    if out.exists():
        raise ValueError("Never overwrite, resume or retry a partial run")
    config = ModelConfig.from_env("put").validate()
    ledger = os.getenv("JOURNEY_REQUEST_LEDGER")
    if concurrency > 1 and not ledger:
        raise ValueError("Parallel episodes require shared request accounting")
    with httpx.Client(
        base_url=chat_url, timeout=chat_timeout, transport=transport, trust_env=False
    ) as chat:
        r = chat.get("/ready")
        r.raise_for_status()
        identity = r.json()
    if (
        identity.get("mode") != ("validation" if validation else "model")
        or identity.get("plan_sha256") != digest(plan)
        or identity.get("source_contract_sha256") != digest(code_contract())
        or not identity.get("sut_config")
    ):
        raise ValueError(
            "SUT, plan and source contracts must match before any model call"
        )
    if expected_sut is not None and identity["sut_config"] != expected_sut:
        raise ValueError("SUT configuration differs from the approved baseline")
    if plan["purpose"] == "formal":
        frozen = plan["freeze"]
        if (
            identity["sut_config"] != frozen["sut_config"]
            or config.public() != frozen["put_config"]
            or max_turns != frozen["limits"]["max_persona_turns"]
            or chat_timeout != frozen["limits"]["chat_timeout"]
            or concurrency != frozen["limits"].get("concurrency", 1)
            or identity.get("max_sut_calls_per_case")
            != frozen["limits"]["max_sut_calls_per_case"]
        ):
            raise ValueError(
                "Runtime models or interaction limits differ from formal freeze"
            )
        from .ledger import binding, summary

        if (
            not ledger
            or int(os.getenv("JOURNEY_REQUEST_LIMIT", "0"))
            != frozen["limits"]["max_total_api_requests"]
            or identity.get("request_accounting")
            != binding(ledger, frozen["limits"]["max_total_api_requests"])
            or summary(ledger)["requests"]
        ):
            raise ValueError(
                "Formal execution needs the coordinator's fresh shared request ledger"
            )
    write_new(
        out / "run.json",
        {
            "protocol": plan["protocol"],
            "plan_sha256": digest(plan),
            "put_config": config.public(),
            "sut_identity": identity,
            "planned_case_ids": [c["id"] for c in plan["cases"]],
            "automatic_retry": False,
            "sut": "fixed baseline API",
            "concurrency": concurrency,
            "evidence_type": "api_validation" if validation else "model",
        },
    )
    cancelled = threading.Event()
    lock = threading.Lock()

    def fail(cid, sid, exc):
        cancelled.set()
        if ledger:
            from .ledger import stop

            stop(ledger, type(exc).__name__)
        with lock:
            if not (out / "STOP.json").exists():
                write_new(
                    out / "STOP.json",
                    {
                        "case_id": cid,
                        "sessionId": sid,
                        "error_type": type(exc).__name__,
                        "automatic_retry": False,
                    },
                )

    cases = iter(enumerate(plan["cases"]))
    completed, dispatched, peak = [], [], 0
    failure = None
    started = time.monotonic()
    pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="journey")
    pending = {}
    try:
        while True:
            while not cancelled.is_set() and len(pending) < concurrency:
                try:
                    index, case = next(cases)
                except StopIteration:
                    break
                future = pool.submit(
                    _case,
                    case,
                    index,
                    plan,
                    plan_path,
                    chat_url,
                    out,
                    config,
                    max_turns,
                    chat_timeout,
                    transport,
                    actor_factory,
                    cancelled,
                    fail,
                )
                pending[future] = case["id"]
                dispatched.append(case["id"])
                peak = max(peak, len(pending))
            if not pending:
                break
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                pending.pop(future)
                try:
                    completed.append(future.result())
                except CancelledError:
                    pass
                except BaseException as exc:
                    failure = failure or exc
                    cancelled.set()
            if cancelled.is_set():
                for future in pending:
                    future.cancel()
        if cancelled.is_set() and failure is None:
            failure = RuntimeError("Study stopped by shared request controller")
    except BaseException as exc:
        failure = exc
        fail(None, None, exc)
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        write_new(
            out / "scheduler.json",
            {
                "concurrency": concurrency,
                "peak_submitted_unfinished": peak,
                "dispatched_case_ids": dispatched,
                "completed_case_ids": completed,
                "wall_seconds": time.monotonic() - started,
                "stopped": cancelled.is_set(),
                "automatic_retry": False,
            },
        )
    if failure is not None:
        raise failure
    return {
        "completed_case_count": len(completed),
        "automatic_retry": False,
        "concurrency": concurrency,
    }
