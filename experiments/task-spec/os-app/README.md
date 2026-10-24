# os-app — generic factor vocabulary

For experiments whose SUT is native app / OS workflow operation. Verifier:
`osapp_generic`.

## Factorable surfaces (generic)

| Factor id | params key(s) | What it varies | Injection |
|---|---|---|---|
| `backend` | `backend` | Runtime host (`docker` / `macos` / `ios`) | job config (`cua_backend`) + `MATRIX_PARAM_BACKEND` |
| `app_build` | `app_build` | Which app build / version | env + template |
| `initial_state` | `initial_state` | Seed state / fixture the workflow starts from | env + template |
| `target_entity` | `target_entity` | The concrete subject (e.g. a ticker, a file, a contact) | `{{ target_entity }}` + `MATRIX_PARAM_TARGET_ENTITY` |

`backend` maps to the Harbor environment type at launch (reusing the existing
`osAppBackend` -> `cua_backend` path); the rest inject as env/template.

## Behavioral extraction (default)

`osapp_generic` is behavioral by default: presence of `outputArtifact` is the
`task_outcome` check, then it reflects the task's declared `signals` into facets,
plus `user_feedback` when collected.

## Optional correctness path

When a level ships `expected.json`, its `constraints` are checked verbatim (e.g.
`ticker`, computed values); a violation flips `task_outcome` to failed.

## Emitted facet contract (shared-core)

`task_outcome` + declared `signals` contexts + optional `user_feedback`, all using
the shared-core facet keys. `side_effects` / `execution_profile` contexts require
a custom verifier that can compute them. Keys stay identical across levels so arms
align.
