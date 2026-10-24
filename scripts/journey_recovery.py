"""Explicit continuation of never-attempted cases; original frozen runtime is intact.

This host coordinator is outside the bound journeys package. It reuses the exact
original case actor, sidecars, replay and analysis functions. It never retries an
episode/request or edits an old run. Prior request rows are carried into a new
ledger and protected by SQL triggers, preserving the original global cap.
"""

from concurrent.futures import CancelledError, FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import closing
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import threading
import time

REPO = Path(__file__).resolve().parents[1]
for component in ("src", "environment/runtime", "environment/agents"):
    sys.path.insert(0, str(REPO / component))

import httpx  # noqa: E402

from matraix.journeys.cohort import code_contract, digest, load_plan, write_new  # noqa: E402
from matraix.journeys.launch import (  # noqa: E402
    LocalStack,
    configure,
    request_accounting,
)
from matraix.journeys.ledger import binding, stop, summary  # noqa: E402
from matraix.journeys.run import _case  # noqa: E402
from matraix.journeys.telemetry import MemorySampler  # noqa: E402

RECOVERY_VERSION = "never-attempted-continuation-v1"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


def read_only(path):
    return sqlite3.connect(
        Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=30
    )


def ledger_fingerprint(path, upper_id=None):
    with closing(read_only(path)) as connection:
        sql = "SELECT id,role,request_hash,status,receipt,created FROM requests"
        params = ()
        if upper_id is not None:
            sql += " WHERE id<=?"
            params = (upper_id,)
        rows = list(connection.execute(sql + " ORDER BY id", params))
        control = list(
            connection.execute(
                "SELECT stopped,reason FROM control WHERE id=1"
            ).fetchone()
        )
    return {
        "rows": len(rows),
        "max_id": max((row[0] for row in rows), default=0),
        "rows_sha256": digest(rows),
        "reserved": sum(row[3] == "reserved" for row in rows),
        "failed": sum(row[3] == "failed" for row in rows),
        "control": control,
    }


def copy_ledger(source, destination, expected, *, authorize_continuation=False):
    destination = Path(destination)
    if destination.exists():
        raise ValueError(
            "Continuation always needs a new ledger; never reset an old one"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    before = ledger_fingerprint(source)
    if before != expected or before["reserved"]:
        raise ValueError("Prior ledger changed or still has in-flight requests")
    with (
        closing(read_only(source)) as previous,
        closing(sqlite3.connect(destination)) as new,
    ):
        previous.backup(new)
        if authorize_continuation:
            # Only the derived ledger's dispatch gate is opened by fresh user
            # authorization. No old request status, usage or real quota resets.
            with new:
                new.execute("UPDATE control SET stopped=0,reason=NULL WHERE id=1")
                maximum = int(expected["max_id"])
                for action in ("UPDATE", "DELETE"):
                    new.execute(
                        f"CREATE TRIGGER preserve_prior_{action.lower()} BEFORE {action} ON requests "
                        f"WHEN OLD.id<={maximum} BEGIN SELECT RAISE(ABORT,'prior request is immutable'); END"
                    )
                new.execute(
                    "CREATE TABLE continuation_origin (prior_count INTEGER, prior_max_id INTEGER, prior_rows_sha256 TEXT)"
                )
                new.execute(
                    "INSERT INTO continuation_origin VALUES(?,?,?)",
                    (expected["rows"], maximum, expected["rows_sha256"]),
                )
    after = ledger_fingerprint(destination, expected["max_id"])
    if after["rows_sha256"] != expected["rows_sha256"]:
        raise ValueError("Copied prior requests differ")
    if ledger_fingerprint(source) != before:
        raise ValueError("Prior ledger must remain unchanged")


def partition_cases(plan, attempted_ids):
    ids = [case["id"] for case in plan["cases"]]
    if len(ids) != len(set(ids)) or not set(attempted_ids) <= set(ids):
        raise ValueError("Duplicate or unplanned case IDs")
    if len(attempted_ids) != len(set(attempted_ids)):
        raise ValueError("Duplicate prior attempts")
    excluded = set(attempted_ids)
    return [case for case in plan["cases"] if case["id"] not in excluded]


def prior_index(plan, prior):
    prior = Path(prior)
    if read(prior / "completion.json")["status"] != "stopped":
        raise ValueError(
            "Only an explicitly inspected stopped segment may be continued"
        )
    lifecycle = read(prior / "service_lifecycle.json")
    if lifecycle["live_children"] or any(
        service["exit_code"] is None for service in lifecycle["services"]
    ):
        raise ValueError("Prior services must be fully drained")
    expected = {case["id"]: case for case in plan["cases"]}
    attempts = []
    for path in (prior / "actor").glob("*/attempt.json"):
        row = read(path)
        if row["case_id"] != path.parent.name or row["case_id"] not in expected:
            raise ValueError("Prior attempt attribution mismatch")
        attempts.append(row["case_id"])
    attempted = set(attempts)
    bindings, terminal = set(), set()
    for path in (prior / "records").glob("*/binding.json"):
        row = read(path)
        cid = row["case"]["id"]
        if (
            cid not in attempted
            or cid in bindings
            or digest(row["case"]) != digest(expected[cid])
        ):
            raise ValueError("Prior native binding differs from the frozen plan")
        bindings.add(cid)
        if (path.parent / "record.json").exists():
            terminal.add(cid)
    put_ids = {
        p.parents[2].name for p in (prior / "actor").glob("*/put/*/request.json")
    }
    if not put_ids <= attempted or not bindings <= attempted:
        raise ValueError("Model/native work exists without a recorded attempt")
    scheduler = read(prior / "actor/scheduler.json")
    if not attempted <= set(scheduler["dispatched_case_ids"]):
        raise ValueError("Prior attempt missing from scheduler metadata")
    ledger = ledger_fingerprint(prior / "requests.sqlite3")
    if ledger["reserved"] or not ledger["control"][0]:
        raise ValueError("Prior ledger is not stopped and drained")
    return {
        "attempted_case_ids": sorted(attempted),
        "terminal_case_ids": sorted(terminal),
        "attempted_without_terminal_ids": sorted(attempted - terminal),
        "attempted": len(attempted),
        "terminal": len(terminal),
        "ledger": ledger,
    }


def verify_hash_manifest(root, manifest_path):
    for name, expected in read(manifest_path)["files"].items():
        path = (Path(root) / name).resolve()
        if not path.is_relative_to(Path(root).resolve()) or file_hash(path) != expected:
            raise ValueError("Preserved prior artifact changed: " + name)


def prepare(plan_path, prior, config, amendment, out):
    out, prior, plan_path = (
        Path(out).resolve(),
        Path(prior).resolve(),
        Path(plan_path).resolve(),
    )
    if out.exists() or out.is_relative_to(prior):
        raise ValueError("New recovery root outside the original run required")
    plan = load_plan(plan_path)
    if plan["purpose"] != "formal" or not plan["formal_spec_frozen"]:
        raise ValueError("Original frozen formal plan required")
    approval = read(amendment)
    if (
        approval.get("authorized") is not True
        or approval.get("scope") != "never_attempted_only"
    ):
        raise ValueError("Explicit user continuation amendment required")
    if approval.get("plan_sha256") != digest(plan):
        raise ValueError("Amendment bound to another plan")
    if (
        approval.get("statistics_unchanged") is not True
        or approval.get("retry") is not False
    ):
        raise ValueError("Do not silently change inference or retry rules")
    configs, limits = configure(config, need_credentials=False)
    if limits != plan["freeze"]["limits"] or any(
        configs[role].public() != plan["freeze"][role + "_config"]
        for role in ("sut", "put")
    ):
        raise ValueError("Frozen model/resource settings changed")
    if read(prior / "completion.json")["plan_sha256"] != digest(plan):
        raise ValueError("Prior run belongs to another formal plan")
    preservation = prior.parent / "STOPPED_RAW_PRESERVATION_MANIFEST.json"
    if approval.get("preservation_manifest_sha256") != file_hash(preservation):
        raise ValueError("Prior preservation seal differs")
    verify_hash_manifest(prior, preservation)
    index = prior_index(plan, prior)
    candidates = partition_cases(plan, index["attempted_case_ids"])
    if len(candidates) != approval["expected_unattempted"]:
        raise ValueError("Never-attempted count differs from user authorization")
    if index["ledger"]["rows"] >= limits["max_total_api_requests"]:
        raise ValueError("Original global request cap is exhausted")
    out.mkdir(parents=True)
    shutil.copyfile(amendment, out / "AMENDMENT.json")
    shutil.copyfile(config, out / "settings.json")
    copy_ledger(
        prior / "requests.sqlite3", out / "baseline-requests.sqlite3", index["ledger"]
    )
    manifest = {
        "version": RECOVERY_VERSION,
        "prepared_utc": datetime.now(timezone.utc).isoformat(),
        "plan_path": str(plan_path),
        "plan_sha256": digest(plan),
        "spec_sha256": plan["freeze"]["spec_sha256"],
        "code_contract_sha256": digest(code_contract()),
        "prior_run": str(prior),
        "prior_preservation_manifest": str(preservation),
        "prior_preservation_sha256": file_hash(preservation),
        "prior_index": index,
        "never_attempted_case_ids": [case["id"] for case in candidates],
        "never_attempted_cases_sha256": digest(candidates),
        "planned_total": len(plan["cases"]),
        "continuation_count": len(candidates),
        "original_global_request_cap": limits["max_total_api_requests"],
        "previous_requests_counted": index["ledger"]["rows"],
        "new_requests_remaining": limits["max_total_api_requests"]
        - index["ledger"]["rows"],
        "settings_sha256": file_hash(out / "settings.json"),
        "amendment_sha256": file_hash(out / "AMENDMENT.json"),
        "baseline_ledger_sha256": file_hash(out / "baseline-requests.sqlite3"),
        "inference_completion_rule_unchanged": True,
        "automatic_restart": False,
        "retry": False,
        "model_api_calls": 0,
    }
    write_new(out / "CONTINUATION_MANIFEST.json", manifest)
    write_new(out / "CONTINUATION_SEAL.json", {"manifest_sha256": digest(manifest)})
    return {
        "prepared": str(out),
        "never_attempted": len(candidates),
        "excluded_prior_attempts": index["attempted"],
        "model_api_calls": 0,
    }


def validate_recovery(root, settings):
    root = Path(root)
    manifest = read(root / "CONTINUATION_MANIFEST.json")
    if (
        manifest["version"] != RECOVERY_VERSION
        or digest(manifest) != read(root / "CONTINUATION_SEAL.json")["manifest_sha256"]
    ):
        raise ValueError("Continuation manifest changed")
    if (
        file_hash(settings) != manifest["settings_sha256"]
        or file_hash(root / "AMENDMENT.json") != manifest["amendment_sha256"]
    ):
        raise ValueError("Settings or amendment changed")
    if (
        file_hash(root / "baseline-requests.sqlite3")
        != manifest["baseline_ledger_sha256"]
    ):
        raise ValueError("Baseline ledger snapshot changed")
    plan = load_plan(manifest["plan_path"])
    if (
        digest(plan) != manifest["plan_sha256"]
        or plan["freeze"]["spec_sha256"] != manifest["spec_sha256"]
    ):
        raise ValueError("Original formal plan/statistics changed")
    candidates = partition_cases(plan, manifest["prior_index"]["attempted_case_ids"])
    if [c["id"] for c in candidates] != manifest["never_attempted_case_ids"] or digest(
        candidates
    ) != manifest["never_attempted_cases_sha256"]:
        raise ValueError("Continuation selection changed")
    if prior_index(plan, manifest["prior_run"]) != manifest["prior_index"]:
        raise ValueError("Prior attempts or request ledger changed")
    return manifest, plan, candidates


def check_ready(identity, plan, configs, limits, ledger, baseline):
    if (
        identity.get("mode") != "model"
        or identity.get("plan_sha256") != digest(plan)
        or identity.get("source_contract_sha256") != digest(code_contract())
        or identity.get("sut_config") != configs["sut"].public()
        or identity.get("max_sut_calls_per_case") != limits["max_sut_calls_per_case"]
        or identity.get("request_accounting")
        != binding(ledger, limits["max_total_api_requests"])
    ):
        raise ValueError("Continuation sidecar/runtime contract mismatch")
    copied = ledger_fingerprint(ledger, baseline["max_id"])
    total = ledger_fingerprint(ledger)
    if (
        copied["rows_sha256"] != baseline["rows_sha256"]
        or total["rows"] != baseline["rows"]
        or total["control"][0]
    ):
        raise ValueError(
            "Initial continuation ledger is not the exact preserved baseline"
        )


def dispatch(
    candidates, plan, plan_path, chat_url, out, config, limits, ledger, *, case_fn=_case
):
    out = Path(out)
    if out.exists():
        raise ValueError("Never overwrite or restart an actor segment")
    cancelled, lock = threading.Event(), threading.Lock()
    completed, dispatched, peak = [], [], 0
    failure = None
    started = time.monotonic()
    ids = [case["id"] for case in candidates]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate dispatch candidate")
    expected_cases = {case["id"]: case for case in plan["cases"]}
    if not ids or any(
        cid not in expected_cases or digest(case) != digest(expected_cases[cid])
        for cid, case in zip(ids, candidates, strict=True)
    ):
        raise ValueError("Dispatch candidates must match the frozen plan exactly")
    allowed = set(ids)
    write_new(
        out / "run.json",
        {
            "protocol": plan["protocol"],
            "plan_sha256": digest(plan),
            "put_config": config.public(),
            "planned_case_ids": ids,
            "automatic_retry": False,
            "concurrency": limits["concurrency"],
            "evidence_type": "model_continuation",
        },
    )

    def fail(cid, sid, exc):
        cancelled.set()
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

    cases = iter((i, c) for i, c in enumerate(plan["cases"]) if c["id"] in allowed)
    pending = {}
    pool = ThreadPoolExecutor(
        max_workers=limits["concurrency"], thread_name_prefix="remaining-journey"
    )
    try:
        while True:
            while not cancelled.is_set() and len(pending) < limits["concurrency"]:
                try:
                    index, case = next(cases)
                except StopIteration:
                    break
                future = pool.submit(
                    case_fn,
                    case,
                    index,
                    plan,
                    plan_path,
                    chat_url,
                    out,
                    config,
                    limits["max_persona_turns"],
                    limits["chat_timeout"],
                    None,
                    None,
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
    except BaseException as exc:
        failure = exc
        fail(None, None, exc)
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        write_new(
            out / "scheduler.json",
            {
                "concurrency": limits["concurrency"],
                "peak_submitted_unfinished": peak,
                "dispatched_case_ids": dispatched,
                "completed_case_ids": completed,
                "wall_seconds": time.monotonic() - started,
                "stopped": cancelled.is_set(),
                "automatic_retry": False,
            },
        )
    if failure is not None or cancelled.is_set():
        raise RuntimeError(
            "Continuation segment stopped; no request/episode retries"
        ) from failure
    return completed


def original_inference_eligible(plan, rows, ledger, segment_complete, previous):
    # Preserve the signed original completeness gate as well as its estimator.
    return bool(
        segment_complete
        and len(rows) == len(plan["cases"])
        and not ledger["inflight_or_unknown"]
        and not ledger["usage_unknown_requests"]
        and not ledger["failed"]
        and not previous["attempted_without_terminal_ids"]
    )


def finalize(root, segment, manifest, plan, failure):
    from matraix.journeys.analysis import summarize
    from matraix.journeys.design import infer
    from matraix.journeys.verify import verify_trial

    segment = Path(segment)
    rows, seen, replay_error = {}, set(), None
    provenance = []
    attempts = set(manifest["prior_index"]["attempted_case_ids"])
    expected = {c["id"]: c for c in plan["cases"]}
    new_attempts = {
        read(p)["case_id"] for p in (segment / "actor").glob("*/attempt.json")
    }
    if new_attempts & attempts or not new_attempts <= set(
        manifest["never_attempted_case_ids"]
    ):
        raise ValueError("A prior/unplanned case was dispatched")
    try:
        for label, bundle in (
            ("original", Path(manifest["prior_run"])),
            ("continuation", segment),
        ):
            for path in (bundle / "records").glob("*/binding.json"):
                bound, row = verify_trial(path.parent)
                cid = bound["case"]["id"]
                if (
                    bound["mode"] != "model"
                    or cid not in (attempts if label == "original" else new_attempts)
                    or cid in seen
                    or cid not in expected
                    or digest(bound["case"]) != digest(expected[cid])
                ):
                    raise ValueError(
                        "Duplicate or changed source case in combined evidence"
                    )
                seen.add(cid)
                if row is not None:
                    rows[cid] = row
                    provenance.append(
                        {
                            "case_id": cid,
                            "segment": label,
                            "record": str(path.parent / "record.json"),
                            "record_sha256": file_hash(path.parent / "record.json"),
                        }
                    )
    except Exception as exc:
        replay_error = type(exc).__name__
    ledger = summary(segment / "requests.sqlite3")
    all_attempts = attempts | new_attempts
    full_remaining_complete = (
        failure is None
        and len(new_attempts) == manifest["continuation_count"]
        and all(cid in rows for cid in manifest["never_attempted_case_ids"])
        and replay_error is None
    )
    eligibility = original_inference_eligible(
        plan, rows, ledger, full_remaining_complete, manifest["prior_index"]
    )
    prior_rows = ledger_fingerprint(
        segment / "requests.sqlite3", manifest["prior_index"]["ledger"]["max_id"]
    )
    if prior_rows["rows_sha256"] != manifest["prior_index"]["ledger"]["rows_sha256"]:
        raise ValueError("Preserved prior request rows changed during execution")
    if (
        ledger_fingerprint(Path(manifest["prior_run"]) / "requests.sqlite3")
        != manifest["prior_index"]["ledger"]
    ):
        raise ValueError("Original request ledger was modified")
    verify_hash_manifest(manifest["prior_run"], manifest["prior_preservation_manifest"])
    completion = {
        "status": "remaining_collection_complete_with_retained_missing"
        if full_remaining_complete
        else "stopped",
        "purpose": "formal",
        "protocol": plan["protocol"],
        "plan_sha256": digest(plan),
        "concurrency": plan["freeze"]["limits"]["concurrency"],
        "planned": len(plan["cases"]),
        "attempted": len(all_attempts),
        "terminal_records": len(rows),
        "missing_or_unresolved": len(plan["cases"]) - len(rows),
        "unattempted": len(plan["cases"]) - len(all_attempts),
        "continuation_attempted": len(new_attempts),
        "continuation_planned": manifest["continuation_count"],
        "native_replay_error": replay_error,
        "ledger": ledger,
        "old_request_rows_included_once": True,
        "formal_inference_eligible": eligibility,
        "statistical_spec_sha256": manifest["spec_sha256"],
        "automatic_retry": False,
        "finished_utc": datetime.now(timezone.utc).isoformat(),
    }
    final = Path(root) / "combined-final"
    write_new(final / "completion.json", completion)
    write_new(final / "record-provenance.json", provenance)
    analysis = summarize(plan, rows)
    analysis.update(
        inference_enabled=eligibility,
        plan_sha256=manifest["plan_sha256"],
        attempted=len(all_attempts),
        unattempted=completion["unattempted"],
    )
    if eligibility:
        analysis["inference"] = infer(analysis, plan)
    else:
        analysis["note"] = (
            "Original fixed-final completeness/known-usage gate not satisfied. Retained missing cases use[0,1]; no formal significance or equivalence claim. Statistical specification unchanged."
        )
    write_new(final / "analysis/descriptive.json", analysis)
    write_new(final / "prior-request-integrity.json", prior_rows)
    lines = [
        "# Car / Home 原计划分段采集汇总",
        "",
        f"状态：{completion['status']}。原计划4800；已尝试{len(all_attempts)}；有可回放终态{len(rows)}；缺失/未决{completion['missing_or_unresolved']}；未尝试{completion['unattempted']}。",
        "",
        "保留原始结果与失败，不重试已尝试案例。成功率分母始终为原计划数，部分完成另列；缺失取[0,1]。",
        "",
        "| 场景 | 任务 | 已确认成功率 | 计划数 | 缺失/未决 | 可行部分完成 |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for group in analysis["groups"]:
        lines.append(
            f"| {group['domain']} | {group['task']} | {group['success_rate']:.1%} | {group['planned']} | {group['missing_or_unresolved']} | {group['partial']} |"
        )
    lines += [
        "",
        "## 原定总体对照（描述）",
        "",
        "| 对照 | 包含缺失的识别范围（百分点） |",
        "|---|---:|",
    ]
    for comparison in analysis["overall_comparisons"]:
        lines.append(
            f"| {comparison['domain']} / {comparison['comparison']} | [{100 * comparison['difference_lower']:+.1f}, {100 * comparison['difference_upper']:+.1f}] |"
        )
    lines += [
        "",
        "以上是缺失识别范围，不是置信区间。",
        "原始统计方法、样本、模型与阈值未修改。原定完整性/已知用量门槛未满足时，不输出正式显著或等效结论。",
        "",
        "原始证据不复制改写；逐案例原始位置与哈希见record-provenance.json。全部已知及未知用量见completion.json中的累计ledger。",
        "合成原生persona不代表真人或完整混合来源库；本轮只有固定基线助手。",
    ]
    (final / "REPORT_CN.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return completion


def execute(root, settings, *, authorized=False, key_file=None):
    if not authorized:
        raise ValueError("Explicit --execute is required for paid continuation")
    root = Path(root).resolve()
    manifest, plan, candidates = validate_recovery(root, settings)
    segment = root / "segment"
    if segment.exists() or (root / "EXECUTION.lock").exists():
        raise ValueError("Continuation may execute once only; no implicit restart")
    configs, limits = configure(settings, key_file=key_file)
    if limits != plan["freeze"]["limits"] or any(
        configs[r].public() != plan["freeze"][r + "_config"] for r in ("sut", "put")
    ):
        raise ValueError("Frozen roles/resource limits changed")
    from matraix.journeys.home.native import load_source as load_home
    from matraix.journeys.car.native import load_source as load_car

    load_home()
    load_car()
    write_new(
        root / "EXECUTION.lock",
        {
            "pid": os.getpid(),
            "started_utc": datetime.now(timezone.utc).isoformat(),
            "remaining": len(candidates),
            "plan_sha256": manifest["plan_sha256"],
            "automatic_restart": False,
        },
    )
    print(
        json.dumps(
            {
                "status": "starting",
                "pid": os.getpid(),
                "remaining": len(candidates),
                "excluded_prior_attempts": manifest["prior_index"]["attempted"],
                "preserved_requests": manifest["previous_requests_counted"],
            }
        ),
        flush=True,
    )
    failure = None
    with MemorySampler(segment):
        segment.mkdir()
        shutil.copytree(manifest["plan_path"], segment / "plan")
        copy_ledger(
            root / "baseline-requests.sqlite3",
            segment / "requests.sqlite3",
            manifest["prior_index"]["ledger"],
            authorize_continuation=True,
        )
        write_new(
            segment / "environment.json",
            {
                "version": RECOVERY_VERSION,
                "plan_sha256": manifest["plan_sha256"],
                "source_contract": code_contract(),
                "concurrency": limits["concurrency"],
                "started_utc": datetime.now(timezone.utc).isoformat(),
            },
        )
        write_new(
            segment / "settings.json",
            {
                "sut": configs["sut"].public(),
                "put": configs["put"].public(),
                "limits": limits,
            },
        )
        write_new(
            segment / "continuation.json",
            {
                "manifest_sha256": digest(manifest),
                "allow_case_ids": manifest["never_attempted_case_ids"],
                "excluded_case_ids": manifest["prior_index"]["attempted_case_ids"],
                "prior_requests": manifest["previous_requests_counted"],
                "original_global_request_limit": limits["max_total_api_requests"],
            },
        )
        try:
            with request_accounting(
                segment / "requests.sqlite3", limits["max_total_api_requests"]
            ):
                with LocalStack(
                    segment / "plan", segment, configs, limits, "model"
                ) as stack:
                    with httpx.Client(
                        base_url=stack.chat_url, timeout=30, trust_env=False
                    ) as client:
                        response = client.get("/ready")
                        response.raise_for_status()
                        check_ready(
                            response.json(),
                            plan,
                            configs,
                            limits,
                            segment / "requests.sqlite3",
                            manifest["prior_index"]["ledger"],
                        )
                    write_new(segment / "ready.json", response.json())
                    actor = segment / "actor"
                    dispatch(
                        candidates,
                        plan,
                        segment / "plan",
                        stack.chat_url,
                        actor,
                        configs["put"],
                        limits,
                        segment / "requests.sqlite3",
                    )
        except BaseException as exc:
            failure = type(exc).__name__
            write_new(
                segment / "STOP.json",
                {
                    "error_type": failure,
                    "automatic_retry": False,
                    "automatic_restart": False,
                },
            )
        attempts = list((segment / "actor").glob("*/attempt.json"))
        new_index = {read(p)["case_id"] for p in attempts}
        ledger = summary(segment / "requests.sqlite3")
        write_new(
            segment / "completion.json",
            {
                "status": "complete"
                if failure is None and len(new_index) == len(candidates)
                else "stopped",
                "planned": len(candidates),
                "attempted": len(new_index),
                "ledger": ledger,
                "finished_utc": datetime.now(timezone.utc).isoformat(),
                "automatic_retry": False,
            },
        )
    completion = finalize(root, segment, manifest, plan, failure)
    write_new(
        root / "COORDINATOR_EXIT.json",
        {
            "status": completion["status"],
            "pid": os.getpid(),
            "finished_utc": datetime.now(timezone.utc).isoformat(),
            "automatic_restart": False,
        },
    )
    return completion


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare")
    for name in ("plan", "prior", "config", "amendment", "out"):
        p.add_argument("--" + name, type=Path, required=True)
    r = commands.add_parser("execute")
    r.add_argument("--recovery", type=Path, required=True)
    r.add_argument("--config", type=Path, required=True)
    r.add_argument("--key-file", type=Path)
    r.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(args.plan, args.prior, args.config, args.amendment, args.out)
    else:
        try:
            result = execute(
                args.recovery,
                args.config,
                authorized=args.execute,
                key_file=args.key_file,
            )
        except BaseException as exc:
            exit_path = args.recovery / "COORDINATOR_EXIT.json"
            if (args.recovery / "EXECUTION.lock").exists() and not exit_path.exists():
                write_new(
                    exit_path,
                    {
                        "status": "raised",
                        "error_type": type(exc).__name__,
                        "pid": os.getpid(),
                        "finished_utc": datetime.now(timezone.utc).isoformat(),
                        "automatic_restart": False,
                    },
                )
            raise
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if args.command == "execute" and result["status"] == "stopped":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
