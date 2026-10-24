# Experiment artifacts on Hugging Face

Private dataset:
[MatrAIx2026/MatrAIx_in_the_Wild](https://huggingface.co/datasets/MatrAIx2026/MatrAIx_in_the_Wild)

**Who** = `personas/<group>/`. **What** = `models/<m>/arms/<arm-id>/`
(one experiment arm / Harbor job). SUT has **only** `personas/shared/`.
Crossed does **not** mint `stimulus__group` paths — which cohort an arm
used is `personaArm` / `persona_strategy` on the experiment.

The engine manifest still stores these as `cells[]`. The upload folder is
`arms/` to match Playground language.

| Design | Personas | Arms |
|--------|----------|------|
| Explore | `shared/` only | one arm |
| SUT | `shared/` only | `feature`, `outcome`, … |
| PUT | one folder per group | usually the group names |
| Crossed | one folder per group | system arms; group via `personaArm` |

[Full card](https://huggingface.co/datasets/MatrAIx2026/MatrAIx_in_the_Wild/blob/main/README.md#who--what-one-layout).
