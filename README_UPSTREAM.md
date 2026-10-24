<div align="center">
  <h1>MatrAIx in the Wild</h1>
  <p><strong>A Persona-Simulation Controlled-Experiment Architecture for Real-World Decision Making</strong></p>
  <p>
    <strong>English</strong> |
    <a href="docs/i18n/README.zh-CN.md">简体中文</a> |
    <a href="docs/i18n/README.zh-TW.md">繁體中文</a> |
    <a href="docs/i18n/README.ko.md">한국어</a> |
    <a href="docs/i18n/README.ja.md">日本語</a> |
    <a href="docs/i18n/README.es.md">Español</a> |
    <a href="docs/i18n/README.pt-BR.md">Português</a>
  </p>
  <p>
    <a href="https://matraix.ai/"><img alt="Website" src="https://img.shields.io/badge/Website-matraix.ai-4f7cff?style=for-the-badge"></a>
    <a href="https://matraix.ai/research/matraix-in-the-wild.html"><img alt="Technical report" src="https://img.shields.io/badge/Technical%20report-In%20the%20Wild-176b4d?style=for-the-badge"></a>
    <a href="docs/README.md"><img alt="Docs" src="https://img.shields.io/badge/Docs-Handbook-5b5b5b?style=for-the-badge"></a>
    <a href="https://huggingface.co/datasets/MatrAIx2026/MatrAIx_Persona_1M_Public_Release"><img alt="Hugging Face" src="https://img.shields.io/badge/Hugging%20Face-Persona%201M-ffcc4d?style=for-the-badge"></a>
    <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/License-MIT-c33b32?style=for-the-badge"></a>
  </p>
</div>

This repository accompanies our
[technical report](https://matraix.ai/research/matraix-in-the-wild.html)
on persona simulation for real-world decision making. It turns the behavior of
specified persona cohorts in product environments into repeatable
measurements, linking **user simulation**, **product journeys**, and
**industry-standard controlled experiments** in one pipeline.

Evidence is organized into four linked units: a *trial* (one persona × one
stimulus), a *batch run* (one cohort × one fixed stimulus), a *controlled
comparison* across cohorts or stimuli, and a *standardized report* for
decision-making. Each unit maps to the one below it, so an aggregate result
remains traceable to its constituent observations and to the claims that
level can support.

A study freezes its target cohort as a reusable persona manifest, then
exposes that cohort to surveys, chatbots, websites, or OS apps under a
written experiment contract—what changes, what remains fixed, and which
metrics are primary, secondary, or guardrail. Shared assignment reuses the
same persona IDs across arms; split assignment partitions them. The same
protocol can be rerun after a product or model revision.

Simulated responses do not replace evidence from real people. They make *who
is simulated* an inspectable part of the study, and they identify which
alternatives, subgroup differences, and open questions warrant subsequent
human evaluation. The underlying population schema and Persona 1M coreset
live in
[MatrAIx-Persona-8B](https://github.com/MatrAIx-ai/MatrAIx-Persona-8B).

<p align="center">
  <img src="docs/assets/matraix-in-the-wild-infrastructure.png" alt="Four steps: synthesize a cohort, run it as a batch, optionally run a controlled experiment, then produce a decision report" width="100%">
</p>

<p align="center"><em>Cohort → batch run → controlled experiment → report. Each aggregate result maps back to its trials.</em></p>

## What you can ask

Every study is **who × what**: one cohort or several, one experience or
several versions. That gives four designs. The pictures are from the
[technical report](https://matraix.ai/research/matraix-in-the-wild.html)
(details omitted). They illustrate the *kind* of question, not a task you
must clone.

<table>
  <tr>
    <th width="14%" align="center"><sub>who ↓ · what →</sub></th>
    <th width="43%" align="center">One experience</th>
    <th width="43%" align="center">Several versions</th>
  </tr>
  <tr>
    <th valign="middle" align="center">One<br>cohort</th>
    <td valign="top" align="center">
      <img src="docs/assets/who-what-explore.png" alt="Explore responses: one cohort meets one signup experience" width="100%">
      <br><strong>Explore responses</strong><br>
      How does this group respond to an idea or experience?<br>
      <em>A batch run. Useful for friction and tails — not an effect by itself.</em>
    </td>
    <td valign="top" align="center">
      <img src="docs/assets/who-what-compare-alternatives.png" alt="Compare alternatives: one cohort sees original vs clearer wording" width="100%">
      <br><strong>Compare alternatives</strong><br>
      How does this group respond to different versions?<br>
      <em>Same people, different product / copy / page (SUT).</em>
    </td>
  </tr>
  <tr>
    <th valign="middle" align="center">Several<br>cohorts</th>
    <td valign="top" align="center">
      <img src="docs/assets/who-what-compare-groups.png" alt="Compare groups: several cohorts see the same experience" width="100%">
      <br><strong>Compare groups</strong><br>
      How do different groups respond to the same experience?<br>
      <em>Experience fixed; who is simulated changes (PUT).</em>
    </td>
    <td valign="top" align="center">
      <img src="docs/assets/who-what-crossed.png" alt="Compare alternatives across groups: versions crossed with cohorts" width="100%">
      <br><strong>Compare alternatives across groups</strong><br>
      Which version works better for which group?<br>
      <em>Both axes vary.</em>
    </td>
  </tr>
</table>

The first experiment below is **Compare alternatives**. Survey and web
exemplars for that cell (and for Compare groups) are in `experiments/tasks/`.

## Start here

You need [uv](https://docs.astral.sh/uv/) and Python 3.12. Node 20+ is only
for Playground. Docker is only for web / OS-app tasks — not for the survey
experiment below. On Windows use
[WSL2](https://learn.microsoft.com/windows/wsl/install) and clone inside the
Linux filesystem (not `/mnt/c/…`).

```bash
git clone https://github.com/MatrAIx-ai/MatrAIx_in_the_Wild.git
cd MatrAIx_in_the_Wild
uv venv --python 3.12
uv pip install -e .
uv pip install -e packages/playground
uv pip install -e packages/harbor-langsmith
uv pip install -e packages/rewardkit
```

Copy `application/playground/.env.local.example` to
`application/playground/.env.local` and add a key. The example file defaults
to `anthropic/claude-haiku-4-5` (`ANTHROPIC_API_KEY`). Other prefixes
(`ppapi/…`, `dashscope/…`, `openai/…`) are listed in
[agents.md](docs/environment/agents.md).

Confirm the install (no key):

```bash
uv run matraix smoke application/tasks/example-survey_product-feedback
```

You should see `Smoke: ok`. Longer walkthrough:
[quickstart](docs/quickstart.md).

### 1. Playground — run an experiment in the UI

```bash
# Terminal A
VENV=.venv bash application/playground/backend/run_dev.sh

# Terminal B
cd application/playground/frontend && npm ci && npm run dev
```

Open http://localhost:5173 → **Experiments** → **New experiment** →
[`survey-onboarding-framing`](experiments/tasks/survey-onboarding-framing/)
→ **Configure & Run** → choose a small cohort → **Launch 2-arm experiment**.

Same people see feature-framed vs outcome-framed onboarding. Satisfaction is
the primary metric; perceived effort is the guardrail.

### 2. CLI — the same experiment

```bash
uv run matraix experiment create experiments/tasks/survey-onboarding-framing \
  --name onboarding-first-run \
  --per-arm 4 \
  --seed 42
```

`--per-arm 4` is a cheap first pass (same 4 people on both arms). It uses
the persona model from `.env.local`. When it finishes:

```bash
uv run matraix experiment list
uv run matraix experiment analyze <experiment_id>
```

Also in `experiments/tasks/`: `survey-upgrade-copy` (copy A/B),
`survey-trust-by-segment` (compare groups), `web-compare-options` (web A/B,
needs Docker).

For a real cohort, import
[Persona 1M](https://huggingface.co/datasets/MatrAIx2026/MatrAIx_Persona_1M_Public_Release):

```bash
huggingface-cli download MatrAIx2026/MatrAIx_Persona_1M_Public_Release \
  --repo-type dataset \
  --local-dir persona/datasets/matraix-persona-1m/release
```

The in-repo `matraix-persona-dev-sample` (~200 people) is only for smoke.

To add your own study, copy `application/tasks/example-*` or
`experiments/tasks/*` and follow the
[task guide](docs/application/task-guide.md) or
[experiment task guide](docs/application/experiment-task-guide.md).

## What happens in a run

1. **Cohort** — filter and sample personas, then freeze the IDs so the same
   people can meet a new version later.
2. **Batch** — one experience, isolated trials. Outputs land in
   `jobs/<job_name>/`.
3. **Experiment** — the contract expands into arms and launches those jobs.
   Shared assignment reuses the same people across arms; split assignment
   partitions them.
4. **Report** — arms are compared on the metrics you named. The report keeps
   denominators, exclusions, and a path back to each trial.

## Docs

| | |
|---|---|
| [Technical report](https://matraix.ai/research/matraix-in-the-wild.html) | Why this stack exists, and how studies are designed |
| [Quickstart](docs/quickstart.md) | Step-by-step first run |
| [Experiment task guide](docs/application/experiment-task-guide.md) | Author a compare-alternatives or compare-groups experiment |
| [Experiment artifacts (HF)](docs/application/hf-experiment-artifacts.md) | Submit a frozen cohort + trial artifacts (private dataset) |
| [Agents & keys](docs/environment/agents.md) | Model ids and API keys |
| [Car / Home API journeys](docs/journeys/QUICKSTART_CN.md) | Native personas, twelve task families, isolated sidecars, programmatic replay and one-command API execution |
| [Car / Home: bring another model API](docs/journeys/COLLABORATOR_QUICKSTART_CN.md) | Collaborator setup, supported protocols, separate role keys, native-persona pilot and results |
| [Handbook](docs/README.md) | Persona, application, and environment docs |

```text
application/tasks/       Example tasks (survey, chat, web, OS-app)
experiments/             Controlled experiments + scorecard
persona/                 Schema, datasets, sampling
environment/             Runtime, agents, Docker / sidecars
application/playground/  Visual runner
configs/jobs/            Job recipes
jobs/                    Local outputs (gitignored)
```

## License

MIT — see [LICENSE](LICENSE).
