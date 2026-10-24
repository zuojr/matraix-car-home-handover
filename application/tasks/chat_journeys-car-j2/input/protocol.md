Agent/runtime contract (not persona prose).
POST /v1/messages through the task's standard sidecar_http adapter.
The message is a JSON string with exactly {"act":"continue|clarify|stop","style":"terse|balanced|polite"}.
No free text or additional numeric/consent fields are accepted. Canonical task facts and consent are inserted by the simulator.
Respect response.terminal; never retry failed requests. Observe pendingUserRequest as a request for a lawful user decision, not permission to rewrite its facts.
Use a generated resolved task for actual execution. The checked-in applicationContext is offline reference only.
The controller MUST use matraix.journeys.harbor:JourneyVerifier; the generic self-report verifier is insufficient.
