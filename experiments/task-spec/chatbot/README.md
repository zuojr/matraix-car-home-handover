# chatbot — generic factor vocabulary

For experiments whose SUT is a conversational application. Verifier:
`chatbot_generic`. This type already has the richest launch-time override
channel, so most factors inject with no new plumbing.

## Factorable surfaces (generic)

| Factor id | params key(s) | What it varies | Injection |
|---|---|---|---|
| `sut_endpoint` | `application_id` | Which chatbot application / sidecar answers | `MATRIX_CHATBOT_APPLICATION_ID` |
| `application_context` | `application_context` | Context/config handed to the SUT each turn | `MATRIX_CHATBOT_APPLICATION_CONTEXT` |
| `domain` | `domain` | Domain routing | `MATRIX_CHATBOT_DOMAIN` |
| `max_turns` | `max_turns` | Turn budget | `MATRIX_CHATBOT_MAX_TURNS` |
| `system_prompt` | `system_prompt` | SUT system prompt variant | `MATRIX_PARAM_SYSTEM_PROMPT` (SUT reads it) |
| `goal_variant` | `goal_variant` | Conversation goal framing | `{{ goal_variant }}` in instruction |

The first four map onto the existing `chat*` launch overrides; the experiment
layer routes level `params` into those fields.

## Behavioral extraction (default)

`chatbot_generic` derives success and metrics from `transcript.json` +
`user_feedback.json` (no external ground truth). It always emits a
`conversation_summary` (user turn count), reflects any declared `signals`, and
folds in `user_feedback`. A goal-specific objective (per `goal_variant`) belongs
in a `custom` verifier.

## Emitted facet contract (shared-core)

Conversation `task_outcome` + `conversation_summary` + declared `signals` +
`user_feedback` (shared subjective channel). Keys held constant across levels.
