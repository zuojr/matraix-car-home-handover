# MatrAIx in the Wild

Start at the project [README](../README.md) — install, Playground, and the
first experiment. This handbook is the rest of the map: how to run, personas,
tasks, and the runtime.

The population schema and Persona 1M live in
[MatrAIx-Persona-8B](https://github.com/MatrAIx-ai/MatrAIx-Persona-8B).
Study design:
[technical report](https://matraix.ai/research/matraix-in-the-wild.html).

```bash
uv run --with mkdocs-material mkdocs serve   # http://127.0.0.1:8000
```

---

## 1. Run

**[Quickstart](quickstart.md)** — install → smoke → one persona → batch → Playground.

| Also | Page |
|------|------|
| Job YAML | [Configuration](configuration.md) |
| Agents & API keys | [Environment → Agents](environment/agents.md) |

---

## 2. Persona 1M (recommended)

The checked-in `matraix-persona-dev-sample` (~200) is for smoke only. For real
cohorts, strategy coverage, and Playground sampling, import the public 1M coreset:

```bash
huggingface-cli download MatrAIx2026/MatrAIx_Persona_1M_Public_Release \
  --repo-type dataset \
  --local-dir persona/datasets/matraix-persona-1m/release
```

Playground: Dataset → **`matraix-persona-1m`**. CLI: `--dataset persona/datasets/matraix-persona-1m`.  
Details: [Persona](persona/README.md#setup-and-usage).

---

## 3. Inherited stack

Same three pillars as 8B — used here to run studies, not as the product surface.

| Pillar | Path | What it covers |
|--------|------|----------------|
| **Persona** | [`persona/`](persona/README.md) | Schema, 1M coreset, sampling, [pipeline](persona/pipeline.md), [validation](persona/validation.md) |
| **Application** | [`application/`](application/README.md) | Task types; **contracts** in [`application/task-spec/`](../application/task-spec/README.md); **experiments** in [experiment-task-guide.md](application/experiment-task-guide.md) |
| **Environment** | [`environment/`](environment/README.md) | Matraix Playground runtime, [agents](environment/agents.md), [web modes](environment/web-interaction.md), [scaling](environment/large-scale-runs.md) |

Optional packages: [packages.md](packages.md).

To author a **new task**, copy an `example-*` under `application/tasks/`
(or an exemplar under `experiments/tasks/`), then the
[task guide](application/task-guide.md) or
[experiment task guide](application/experiment-task-guide.md).
Finished runs go to the private
[HF artifact dataset](application/hf-experiment-artifacts.md).

---

## Map

```text
docs/
├── README.md              this page
├── intake/                study intake form
├── quickstart.md          install → first runs → Playground
├── configuration.md       job recipes
├── persona/               schema · 1M · pipeline · validation
├── application/           tasks overview · task guide · experiment guide · Playground API
├── environment/           Matraix Playground · agents · web modes · scaling
└── packages.md

application/tasks/         example tasks + templates
experiments/tasks/         controlled experiments (SUT / PUT)
application/task-spec/     task contracts
persona/ · environment/    data/schema · runtime code
```
