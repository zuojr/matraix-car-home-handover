# Car/Home experiment handover

Use the immutable `handover-20261024-json` tag (the earlier tag is unchanged). Start with [COLLABORATOR_QUICKSTART_CN.md](docs/journeys/COLLABORATOR_QUICKSTART_CN.md).

This is the independent public code handover. The original private fork and upstream PR remain unchanged. Use the standard MatrAIx experiment CLI and real Harbor sidecars, not the old standalone collection utility.

- [Architecture and API contract](docs/journeys/HANDOVER.md)
- [Validation and limitations](docs/journeys/VALIDATION.md)
- [Public snapshot provenance and excluded data](docs/journeys/PUBLIC_HANDOVER.md)
- [No-model-call CI](https://github.com/zuojr/matraix-car-home-handover/actions/workflows/journey-sidecars.yml)

Supply your own eligible native cohort and API credentials. No author study results or credentials are included. Scripted infrastructure validation does not establish compatibility with every actual model.

Machine-readable CLI output now separates payload stdout from diagnostic stderr,
including inherited Harbor subprocess output. Use `--format json > experiment.json 2> experiment.log` with the complete create command; do not merge those streams.
JSON does not override a nonzero failure exit status. No study was rerun for this fix.
