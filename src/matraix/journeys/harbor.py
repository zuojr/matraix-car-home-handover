"""Small standard Harbor verifier hook; persona runtime remains unchanged."""

import json

from harbor.verifier.base import BaseVerifier
from harbor.models.verifier.result import VerifierResult


class JourneyVerifier(BaseVerifier):
    async def verify(self):
        # Only the controller can exec into the private service. Persona cannot
        # access that service's network or filesystem. Replay runs on Python 3.13.
        result = await self.environment.service_exec(
            "python -m matraix.journeys.verify --records /records --out /verification",
            service="simulator",
            timeout_sec=300,
        )
        if result.return_code:
            raise RuntimeError("Native sidecar replay failed; inspect verifier logs")
        target = self.trial_paths.verifier_dir
        target.mkdir(parents=True, exist_ok=True)
        for name in ("structured_output.json", "reward.txt", "replay.json"):
            await self.environment.service_download_file(
                "/verification/" + name, target / name, service="simulator"
            )
        payload = json.loads(
            (target / "structured_output.json").read_text(encoding="utf-8")
        )
        values = {x["key"]: x["value"] for x in payload["contexts"][0]["facets"]}
        return VerifierResult(
            rewards={"reward": float(values["programmatic_task_success"])}
        )
