# Car/Home journeys: architecture and handover

Start with [the native Harbor collaborator guide](COLLABORATOR_QUICKSTART_CN.md).
The supported integration entry is `matraix experiment create` or Playground
Experiments, using `experiments/tasks/journeys-*`. Official services bind full
source personas and factorial arms before Harbor starts. The host `execute`
coordinator remains a separate utility; it is not needed for native experiments.
[VALIDATION.md](VALIDATION.md) distinguishes real Harbor acceptance from
reference-mode containers and scripted host tests. No historical results are imported.

## Components and trust boundaries

The feature uses the repository's standard chatbot HTTP interface and task layout.
The baseline assistant (SUT), persona actor (PUT) and simulator have separate state.

```text
host coordinator / source-persona actor
  | public chatbot HTTP (/v1/messages)
  v
assistant sidecar ---- SUT model API
  | private authenticated control channel
  v
simulator sidecar ---- isolated native worker per episode
  |
  +---- event log / final state -> independent native replay -> score envelope
```

The host coordinator keeps the PUT model credential; the assistant sidecar keeps
the SUT credential. Native simulator children do not inherit model credentials.
The containerized persona `main` joins only the public chat network: it cannot
reach the simulator control channel or read its control token. Host `execute`
uses loopback sidecars; Harbor uses the shared persona environment plus the local
compose overlay in
`environment/task-environments/application/chatbot-api-sidecar_journeys/`.
Docker is needed for the Harbor path, not for host execution.

The model-mode assistant has no access to the private reference policy. Reference
mode exists only for offline infrastructure tests; its rewards are not model
experiment results. There is no LLM Judge or native model subagent.

## Task specifications

Each `application/tasks/chat_journeys-{car-j1,...,home-h6}/` contains a standard
`task.toml`, instructions, public chatbot input, persona strategy, reporting
contract and verifier tests. Native case builders and checkers are under
`src/matraix/journeys/{car,home}/`; `materialize` generates the task assets.

| Car | Programmatic goal | Home | Programmatic goal |
|---|---|---|---|
| J1 | Navigation route selection | H1 | Arrival preparation and actual temperature |
| J2 | Route, charge target and feasible charging plan | H2 | Tonight's exception with next-day routine protected |
| J3 | Breakfast stop with timing and route constraints | H3 | Leaving-home shutdown within room/occupancy scope |
| J4 | Driver/passenger temperature coordination | H4 | Shared lighting and explicit roommate consent |
| J5 | Window and air-conditioning authorization constraints | H5 | Temperature over a specified time window |
| J6 | Multi-stop route modification | H6 | Bedroom preparation with offline-device partial completion |

These are custom tasks built on CAR-bench and SimuHome, not an assertion that
their upstream benchmark tasks or physical devices were evaluated unchanged.
Car planning checks do not simulate an actual drive or charging queue. Home
temperature checks use simulated dynamics. Runtime minutes are not measured kWh.

The same source persona crosses four assigned current conditions:

| Condition | Disclosure | Car priority | Home priority |
|---|---|---|---|
| C1 | Proactive | Time | Comfort |
| C2 | On demand | Time | Comfort |
| C3 | Proactive | Avoid fees | Energy |
| C4 | On demand | Avoid fees | Energy |

Six tasks x two variants x four conditions give 48 fresh episodes per source
persona per domain. Each episode has its own native state and model contexts;
the source persona remains the paired statistical unit, not 48 independent people.
Full original persona attributes and provenance are retained. Fixed task facts
and explicit permissions take precedence over the assigned condition, which takes
precedence over background attributes. PUT emits validated finite act/style JSON;
the program supplies the factual payload and consent state.

## API and tool protocol

`configs/journeys/chat-compatible.example.json` is the generic Chat Completions
template. SUT requires function tools, tool-choice semantics and call-ID history;
PUT requires strict structured actions. Model-specific Responses adapters and
examples are explicitly selected by endpoint/model, not an arbitrary SDK option.
Native Messages/GenerateContent APIs require a compatible gateway or a separate
adapter. A new provider must pass its own protocol validation before research use.

The protocol identifier is `journey-sidecar-v10`; programmatic scoring is
`structured-journeys-v4`. A response may contain 1-32 tool calls, executed in
order. Questions, confirmations, public responses, submissions or a tool failure
end the batch. Later calls receive `NOT_EXECUTED`; a pending phase cannot be
skipped. Call IDs and outcomes are preserved in `tool-batches/`. Batching does not
increase the episode operation/request limits. Malformed, refused or truncated
PUT output is retained as an error, not repaired or replaced by a default action.

Input prefix reuse may reduce provider computation; no saved model answer or
tool result is reused as a new model output. Full persona content is not truncated.

## Native dependencies and licenses

Journeys requires Python 3.13+. Install with `python -m pip install -e '.[journeys]'`.
`setup-native` installs the pinned, unmodified SimuHome checkout; set its returned
absolute directory as `SIMUHOME_ROOT`. It verifies an existing checkout rather
than resetting it. SimuHome commit:
`83d28837b69f0cbf1bc02ed5334cb8b561a9d54d`.
CAR-bench's vendored archive, hashes and MIT license are in `car/vendor/`.
SimuHome provenance and the CC-BY-NC-ND-4.0 source license are in `home/vendor/`.
Check those terms before redistributing native source or derived study data.

## Results, failure handling and reproducibility

Successful completion requires the simulated goal, numeric/time constraints,
assigned task preference, authorized scope and valid structured submission.
Feasible partial completion is separate. Terminal records and successful replay
do not imply task success. The main denominator is every planned episode;
technical missingness remains unknown [0,1], never silently dropped.

The coordinator binds code/source/config hashes and shares a SQLite request cap
across both model roles. API/protocol failures stop new dispatch and drain work
already sent. No automatic retry, JSON repair, model fallback or quota reset is
performed. Never delete a lock or overwrite an old output to resume. Explicit
continuation of never-attempted cases is documented in [RECOVERY_CN.md](RECOVERY_CN.md).

Record the checkout SHA, frozen plan, source manifests, API settings, receipts,
completion status and replay outputs. Reproducibility means rerunnable contracts
and traceable evidence; stochastic API responses need not match byte-for-byte.
`release-local` performs local validation/packaging, not official dataset upload
format certification. Credentials, full study personas and raw run data stay out
of Git. Dataset publishing is a separate, permissioned step.

## Versioned H4 correction

The v4 lighting protocol publishes the 0–40% acceptable compromise and returns
alternatives on denial. Information queries never grant consent; confirmation
binds exact operations. Ordinary cases retain reading-lamp and preference checks.
Boundary endpoints use the public compromise range. This is prospective only;
old frozen plans, trajectories and scores remain under their original runtime.
H1/H5 native dynamics and thresholds are unchanged; offline witness tests audit
reachability across the original 50 fixture indices, both priorities and variants.
