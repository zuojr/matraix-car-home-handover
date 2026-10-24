# chatbot-api-sidecar_acme-support-api

Local Acme support REST endpoint for chat tasks.
Persona agent runtime: `application/shared-chat-persona`.

Conversation state is scoped by `sessionId` so shared-sidecar multi-persona
batches do not merge transcripts across trials.
