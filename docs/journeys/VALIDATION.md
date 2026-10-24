# Validation: native Harbor and task correctness

## Native end-to-end acceptance

Run `python scripts/validate_journey_harbor.py` in a fresh disposable checkout
with Linux Docker/Compose v2 and `pip install -e '.[journeys]'`.
This is not a mock of Harbor: the official ExperimentService launches eight
Harbor jobs, each with a real trial, persona main, assistant and simulator.
Only model endpoints are scripted, using fixed dummy credentials on loopback.
The test generates a complete 1290-attribute synthetic acceptance identity
through the repository's DAG generator; it never changes research personas.

Assertions cover all eight cells of J4, native per-trial verifier/replay and
programmatic outcome, PUT token fields, both roles' request receipts, shared
40-request ledger with no inflight/unknown requests, standard `matraix results`
JSON/CSV and `matraix experiment analyze` JSON/CSV/PDF exports, and container/server
cleanup. A second generated experiment injects one SUT HTTP 429: only the
first arm runs, the shared gate stops further API dispatch, seven arms remain
explicitly not started, one unknown-usage request remains unknown, and no
replacement/retry or fabricated job is created. `ACCEPTANCE.json`, real jobs and manifests are CI evidence. Scripted
outcomes are not measured model success. The native CI job must pass for the
exact head under review; the reference-container job below is insufficient.

Local Windows has no available Docker CLI, so no local native Docker pass is
claimed. See the PR's current Linux job `official-harbor-eight-arm-acceptance`.
Cloud/GKE/Modal and Docker Desktop/WSL are not validated by that Linux run.

## Prospective correctness regressions

`test_journeys_native_harbor.py` checks official discovery of all twelve task
contracts and their full eight-cell designs; official job-config validation;
complete persona binding; duplicate-run rejection; H4 public alternatives,
ordinary/boundary scope, exact-operation grants and denied proposals. Asking a
housemate is not consent. The v4 boundary endpoint matches the offered 0–40%
compromise; the ordinary task still evaluates its assigned preference and
protects the independent reading lamp.

H1/H5 feasibility uses the unchanged pinned native dynamics and unchanged
scoring thresholds: 50 fixture indices × two priority conditions × two variants
× two task types = 400 offline witness episodes, each independently replayed.
This demonstrates reachable goals for these fixtures, not model proficiency or
an exhaustive proof over all future seeds. Open-loop setpoints do not establish
actual temperature compliance. Averages and samples retain their existing
measurement scopes (H5's required samples are every five minutes).

The older protocol and original frozen study files are never rewritten. Current
v10/v4 plans are prospective; old plans retain their bound runtime for replay.

## Component, stop/drain and reference checks

These checks use native simulators, fixtures and scripted loopback APIs. They do
not contact a model provider or establish compatibility with every real model.
Run from the repository root with Python 3.13 and the journeys extra installed.
The pinned SimuHome source must be available at `SIMUHOME_ROOT`.

## Local setup and credential checks

Follow [the collaborator guide](COLLABORATOR_QUICKSTART_CN.md) to make a private
configuration. These commands make zero HTTP/model requests:

```sh
python scripts/check_journey_setup.py --config journey-runs/my-model.json
python scripts/check_journey_setup.py --config journey-runs/my-model.json --check-credentials
```

The second additionally checks that role credentials can be loaded locally; it
does not test remote authorization. No secrets are printed or written by the
checker. Successful output has `local_setup_valid=true` and zero request counts.
Invalid Python/native provenance/options/placeholders/credentials fail closed.

## Unit and integration suite

```sh
python -m pip install pytest pytest-asyncio ruff==0.15.20
python -m pytest tests/unit/matraix/test_journeys_*.py -q
python -m ruff check src/matraix/journeys scripts/journey_recovery.py scripts/check_journey_setup.py tests/unit/matraix/test_journeys_*.py
python -m pytest tests/environment/test_application_task_contracts.py -k journeys -q
python -m pytest tests/environment/test_persona_agents.py -q
python -m matraix.journeys materialize --repo .
```

Use a shell that expands file globs (as Linux CI does). On PowerShell, collect
the files explicitly for the first two commands:

```powershell
$journeyTests = @(Get-ChildItem tests/unit/matraix/test_journeys_*.py | ForEach-Object { $_.FullName })
python -m pytest @journeyTests -q
python -m ruff check src/matraix/journeys scripts/journey_recovery.py scripts/check_journey_setup.py @journeyTests
```

The suite checks native state replay; charging feasibility; temporal temperature
constraints; scope and consent; offline partial completion; complete source
attributes; persona prompt isolation; tool batches and call IDs; strict PUT JSON;
request accounting; bounded dispatch; stop/drain behavior; immutable recovery;
freeze/analysis gates; and local-only secret-safe preflight.

`test_full_sixteen_episode_coordinator_uses_only_local_scripted_api` runs the real
coordinator against the loopback scripted server. Its collaborator case exercises
the documented preflight and CLI execute path with separate credential files,
16 terminal records, native replay, zero live children and no secret leakage.
Other parameterizations cover bounded concurrency and injected failure/drain.
Scripted API success is infrastructure evidence, not measured model task success.

## Container/HTTP checks

[journey-sidecars.yml](../../.github/workflows/journey-sidecars.yml) installs pinned
native dependencies, runs the offline suite/lint/task contracts and builds the
shared persona main plus assistant/simulator containers. Reference HTTP cases
exercise Car and Home; the main cannot reach private simulator control or read
credentials. Native replay and cleanup run, with diagnostics retained by CI.
Inspect the Actions result for the exact commit under review rather than treating
a historical successful run as evidence for an untested head.

## Real API validation is separate

After the above passes, an authorized operator can prepare the built-in
`validation-plan` and explicitly execute its 16 cases as documented in the
collaborator guide. That step sends source persona/task data and incurs provider
cost. It is never required for this offline suite, never launched automatically
and never counted as formal research. Inspect completion, replay, request usage
and service lifecycle; terminal/replay counts are not task-success counts.

A new API protocol or H4 consent-contract revision needs its own tests and new
plans. Current implementation boundaries are recorded in [HANDOVER.md](HANDOVER.md).
