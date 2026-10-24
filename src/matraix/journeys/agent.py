"""Harbor API persona adapter using native persona identity and standard chat I/O.

The shared persona container and HTTP schema are unchanged. A small adapter is
needed because the generic chat controller retries POSTs and generates free text;
this benchmark requires single attempts and a strict finite set of user acts.
"""

import asyncio
import base64
import json
from pathlib import Path
import shlex
import tempfile

from harbor.agents.base import BaseAgent
from matraix.agents.persona.mixin import PersonaMixin

from .api import APIClient, ModelConfig
from .chat import parse_act
from .cohort import code_contract, digest, load_plan, write_new
from .prompts import compact, put_messages, public_view


async def request(environment, method, path, body=None):
    if method not in {"GET", "POST"} or not path.startswith(("/ready", "/v1/")):
        raise ValueError("Unexpected public chat operation")
    payload = base64.b64encode(
        json.dumps(body or {}, ensure_ascii=False).encode()
    ).decode()
    script = f"""import base64,urllib.request
req=urllib.request.Request({"http://assistant:8000" + path!r},data=base64.b64decode({payload!r}) if {method!r}=="POST" else None,headers={{"Content-Type":"application/json"}},method={method!r})
with urllib.request.urlopen(req,timeout=1200) as r: print(r.read().decode("utf-8"))
"""
    result = await environment.exec(
        "python3 -c " + shlex.quote(script), timeout_sec=1230
    )
    if result.return_code:
        raise RuntimeError("Chat request failed; no retry; inspect sidecar receipts")
    return json.loads(result.stdout)


class JourneyPersonaAPI(PersonaMixin, BaseAgent):
    @staticmethod
    def name():
        return "persona-journey-api"

    def version(self):
        return "3.0.0"

    def __init__(
        self,
        logs_dir,
        persona_path,
        plan_path,
        case_id,
        max_turns=64,
        ledger_path=None,
        request_limit=None,
        **kwargs,
    ):
        self._init_persona(persona_path, self.name())
        super().__init__(logs_dir=logs_dir, **kwargs)
        self.plan = load_plan(plan_path)
        if self.plan["purpose"] == "formal":
            raise ValueError(
                "Use the shared-ledger execute coordinator for formal collection; Harbor is pilot-only"
            )
        self.plan_path = Path(plan_path)
        self.ledger_path, self.request_limit = ledger_path, request_limit
        self.case = next(c for c in self.plan["cases"] if c["id"] == case_id)
        if (
            self.plan["fixture_only"]
            or self.plan["purpose"] == "offline"
            or self.plan["purpose"] == "formal"
            and not self.plan["formal_spec_frozen"]
        ):
            raise ValueError(
                "Only an eligible real native-persona API plan is executable"
            )
        if (
            self._persona.persona_id != self.case["source_persona_id"]
            or self._persona.dimensions != self.case["native_persona"]["dimensions"]
        ):
            raise ValueError("Harbor persona differs from bound original persona")
        self.config = ModelConfig.from_env("put")
        if self.model_name != self.config.model:
            raise ValueError(
                "Harbor model metadata must equal configured PUT API model"
            )
        self.max_turns = max_turns

    async def setup(self, environment):
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        await self._prepare_persona_trial(environment)

    async def run(self, instruction, environment, context):
        identity = await request(environment, "GET", "/ready")
        if (
            identity.get("mode") != "model"
            or identity.get("plan_sha256") != digest(self.plan)
            or identity.get("source_contract_sha256") != digest(code_contract())
            or not identity.get("sut_config")
        ):
            raise ValueError(
                "Assistant/plan/source identity mismatch before model calls"
            )
        c = self.case
        if self.plan["purpose"] == "harbor" and (
            identity["sut_config"] != self.plan["native_models"]["sut"]
            or self.config.public() != self.plan["native_models"]["put"]
        ):
            raise ValueError(
                "Harbor SUT/PUT configuration changed after arm preparation"
            )
        if self.plan["purpose"] == "formal":
            frozen = self.plan["freeze"]
            if (
                identity["sut_config"] != frozen["sut_config"]
                or self.config.public() != frozen["put_config"]
            ):
                raise ValueError(
                    "Harbor SUT/PUT configuration differs from formal freeze"
                )
        write_new(
            self.logs_dir / "run.json",
            {
                "protocol": self.plan["protocol"],
                "plan_sha256": digest(self.plan),
                "case_id": c["id"],
                "source_persona_id": c["source_persona_id"],
                "sut_identity": identity,
                "put_config": self.config.public(),
                "automatic_retry": False,
            },
        )
        client = APIClient(
            self.config,
            self.logs_dir / "put",
            cap=self.max_turns,
            ledger_path=self.ledger_path,
            request_limit=self.request_limit,
        )
        messages, audit = put_messages(c, self.plan, self.plan_path)
        write_new(self.logs_dir / "prompt-audit.json", audit)
        sid = ""
        turns = []
        try:
            for _ in range(self.max_turns):
                raw = (await asyncio.to_thread(client.call, messages))["content"]
                parse_act(raw)
                messages.append({"role": "assistant", "content": raw})
                view = await request(
                    environment,
                    "POST",
                    "/v1/messages",
                    {"message": raw, "sessionId": sid, "applicationContext": c["id"]},
                )
                if sid and sid != view["sessionId"]:
                    raise ValueError("Changed session")
                sid = view["sessionId"]
                turns.append(view["turn"])
                write_new(self.logs_dir / f"turn-{len(turns):03d}.json", view)
                if view["terminal"]:
                    break
                messages.append({"role": "user", "content": compact(public_view(view))})
            else:
                view = await request(
                    environment,
                    "POST",
                    "/v1/messages",
                    {
                        "message": '{"act":"stop"}',
                        "sessionId": sid,
                        "applicationContext": c["id"],
                    },
                )
                turns.append(view["turn"])
            artifacts = {
                "transcript.json": {"sessionId": sid, "turns": turns},
                "application_result.json": {
                    "sessionId": sid,
                    "applicationId": "journeys",
                    "applicationContext": c["id"],
                    "turnCount": len(turns),
                },
                "user_feedback.json": {
                    "status": "not_collected",
                    "reason": "No extra model-based feedback in primary objective benchmark",
                },
            }
            with tempfile.TemporaryDirectory() as folder:
                for name, value in artifacts.items():
                    local = Path(folder) / name
                    local.write_text(
                        json.dumps(value, ensure_ascii=False), encoding="utf-8"
                    )
                    await environment.upload_file(local, "/app/output/" + name)
            context.metadata = {
                "source_persona_id": c["source_persona_id"],
                "sessionId": sid,
                "model_requests": client.calls,
                "cost_measured": False,
            }
        except Exception as exc:
            write_new(
                self.logs_dir / "STOP.json",
                {
                    "case_id": c["id"],
                    "sessionId": sid,
                    "error_type": type(exc).__name__,
                    "automatic_retry": False,
                },
            )
            raise
        finally:
            client.close()
            receipts = [
                json.loads(p.read_text(encoding="utf-8"))
                for p in (self.logs_dir / "put").glob("*/receipt.json")
            ]
            usage = [r.get("usage") for r in receipts]
            # Native Harbor token fields are PUT-only; SUT receipts remain a
            # separate role, never summed twice or priced from guessed rates.
            known = bool(usage) and all(
                isinstance(u, dict)
                and "prompt_tokens" in u
                and "completion_tokens" in u
                for u in usage
            )
            context.n_input_tokens = (
                sum(u["prompt_tokens"] for u in usage) if known else None
            )
            context.n_output_tokens = (
                sum(u["completion_tokens"] for u in usage) if known else None
            )
            context.cost_usd = None
            context.metadata = {
                **(context.metadata or {}),
                "usage_role": "put",
                "usage_unknown": not known,
                "sut_usage_artifact": "sut-api-records",
                "currency_cost_measured": False,
            }
