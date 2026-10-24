"""Read-only collaborator preflight. No sockets, HTTP or model calls."""

import argparse
from contextlib import contextmanager
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys

import httpx

from matraix.journeys.cohort import load_plan
from matraix.journeys.home.common import HERE
from matraix.journeys.launch import configure


@contextmanager
def role_environment():
    """Do not leak loaded credentials/config into a caller's subsequent study."""
    previous = {k: v for k, v in os.environ.items() if k.startswith("JOURNEY_")}
    try:
        yield
    finally:
        for key in list(os.environ):
            if key.startswith("JOURNEY_"):
                os.environ.pop(key)
        os.environ.update(previous)


def check_setup(
    config, *, native_root=None, check_credentials=False, key_file=None, plan=None
):
    if sys.version_info < (3, 13):
        raise ValueError("Use Python 3.13+ for the pinned native Home environment")
    from matraix.agents.persona.templating import render_persona_template

    if "catalog_path" not in inspect.signature(render_persona_template).parameters:
        raise ValueError(
            "Reinstall this checkout; an older persona renderer was loaded"
        )
    path = native_root or os.getenv("SIMUHOME_ROOT")
    if not path:
        raise ValueError("Set SIMUHOME_ROOT or pass --native-root after setup-native")
    native = Path(path).resolve()
    provenance = json.loads(
        (HERE / "vendor/provenance.json").read_text(encoding="utf-8")
    )
    for relative, expected in provenance["files"].items():
        file = native / relative
        if (
            not file.is_file()
            or hashlib.sha256(file.read_text(encoding="utf-8").encode()).hexdigest()
            != expected
        ):
            raise ValueError(
                "Native source missing/modified; rerun setup-native into a new directory"
            )
    with role_environment():
        configs, limits = configure(
            config, need_credentials=check_credentials, key_file=key_file
        )
        roles = {}
        for role, value in configs.items():
            host = httpx.URL(value.base_url).host
            if host.endswith(".invalid") or value.model.startswith("REPLACE_"):
                raise ValueError(
                    "Replace the example API endpoint/model placeholders before preflight"
                )
            roles[role] = {
                "api_protocol": value.protocol,
                "credential_checked": check_credentials,
                "credential_present": bool(os.getenv(value.key_env))
                if check_credentials
                else None,
            }
        plan_info = None
        if plan is not None:
            loaded = load_plan(plan)
            plan_info = {
                "purpose": loaded["purpose"],
                "planned_episodes": loaded["planned_episodes"],
                "fixture_only": loaded["fixture_only"],
            }
    return {
        "local_setup_valid": True,
        "python": sys.version.split()[0],
        "native_source_hashes_valid": True,
        "persona_renderer_supports_bound_catalog": True,
        "native_files_checked": len(provenance["files"]),
        "roles": roles,
        "concurrency": limits["concurrency"],
        "max_total_api_requests": limits["max_total_api_requests"],
        "plan": plan_info,
        "http_requests": 0,
        "model_requests": 0,
        "remote_key_model_and_protocol_verified": False,
        "next_step": "Run the documented separately authorized 16-case API validation in a new output directory; this check does not contact the provider.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--native-root", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--check-credentials", action="store_true")
    parser.add_argument("--key-file", type=Path)
    args = parser.parse_args()
    try:
        result = check_setup(
            args.config,
            native_root=args.native_root,
            plan=args.plan,
            check_credentials=args.check_credentials,
            key_file=args.key_file,
        )
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        AttributeError,
        httpx.InvalidURL,
    ) as exc:
        # Never print configured endpoints, options, credential values or paths.
        message = "Check Python/native source, JSON role settings/placeholders, and credential file accessibility; see the collaborator troubleshooting table"
        print(
            json.dumps(
                {
                    "local_setup_valid": False,
                    "error_type": type(exc).__name__,
                    "error": message,
                    "http_requests": 0,
                    "model_requests": 0,
                }
            )
        )
        raise SystemExit(1) from None
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
