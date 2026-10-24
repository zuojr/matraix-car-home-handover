# Car/Home assistant and native simulator sidecars

See [handover](../../../../docs/journeys/HANDOVER.md).
Generate `runtime/` from the current source before Harbor materializes this directory:
`python -m matraix.journeys materialize --repo .`

The shared main persona environment joins `dialogue`; only the assistant also joins
`control`. Simulator state, scores and the control credential are never public chat fields.
Default mode is reference-only and makes no model calls. Model mode requires explicit API
configuration and a source-bound plan mounted at `plan/`. Do not start a model experiment
using the checked-in reference scenarios.

Source: pinned CAR-bench archive (MIT) and external, unmodified SimuHome
(CC-BY-NC-ND-4.0; see the upstream license). No physical devices are controlled.
