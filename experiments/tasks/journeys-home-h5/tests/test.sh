#!/bin/sh
# Objective evidence is private. Fail closed if the custom controller hook was not selected.
echo "Configure verifier.import_path=matraix.journeys.harbor:JourneyVerifier" >&2
exit 2
