"""Execute revision-pinned CAR-bench tools on experiment-owned fixtures.

Only package initializers (which import unrelated agent backends) are bypassed.
Context models, policy recorder, schemas, calculations and tool invoke methods are
loaded unchanged. The upstream lazy data provider is replaced by a task fixture
repository, scoped to each invocation. No original benchmark score is claimed.
"""

from __future__ import annotations

from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
import hashlib
import importlib
import importlib.machinery
import io
import json
import os
from pathlib import Path
import sys
import types
import zipfile

import jsonschema

from .cases import public_context
from .common import HERE, PIN, read_json, tool

MUTATIONS = {
    "set_new_navigation",
    "delete_current_navigation",
    "navigation_delete_waypoint",
    "set_climate_temperature",
    "open_close_window",
    "set_fan_speed",
    "set_air_conditioning",
}
_loaded = None


def load_source():
    global _loaded
    if _loaded is not None:
        return _loaded
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    manifest = read_json(HERE / "vendor" / "provenance.json")
    archive = HERE / "vendor" / "car-bench-source.zip"
    if hashlib.sha256(archive.read_bytes()).hexdigest() != manifest["archive_sha256"]:
        raise RuntimeError("Bundled native source checksum mismatch")
    root = HERE / ".cache" / PIN[:12]
    if os.name == "nt":
        root = Path("\\\\?\\" + str(root.resolve()))
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            relative = Path(info.filename)
            if relative.is_absolute() or ".." in relative.parts or ":" in info.filename:
                raise RuntimeError("Unsafe native archive entry")
            if info.is_dir():
                continue
            target = root / relative
            content = z.read(info)
            if (
                not target.exists()
                or hashlib.sha256(target.read_bytes()).digest()
                != hashlib.sha256(content).digest()
            ):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
    if "car_bench" in sys.modules:
        raise RuntimeError(
            "Run this study in a fresh Python process; another CAR-bench is already imported"
        )
    package_root = root / "car_bench"
    # These __init__.py files only aggregate modules irrelevant to this runner.
    for directory in [
        package_root,
        *sorted(p for p in package_root.rglob("*") if p.is_dir()),
    ]:
        if "__pycache__" in directory.parts or directory.name == "mock_data":
            continue
        name = ".".join(directory.relative_to(root).parts)
        module = types.ModuleType(name)
        module.__path__ = [str(directory)]
        module.__spec__ = importlib.machinery.ModuleSpec(
            name, loader=None, is_package=True
        )
        sys.modules[name] = module
    prefix = "car_bench.envs.car_voice_assistant"
    context = importlib.import_module(prefix + ".context.dynamic_context_state")
    fixed = importlib.import_module(prefix + ".context.fixed_context")
    data = importlib.import_module(prefix + ".mock_data")
    policy = importlib.import_module("car_bench.envs.policy_evaluator")
    errors = importlib.import_module("car_bench.envs.tool_execution_error_evaluator")
    definitions = [
        ("navigation.get_apis.get_routes_from_start_to_destination", "GetRoutes"),
        ("navigation.get_apis.search_poi_along_the_route", "SearchPoiAlongTheRoute"),
        (
            "navigation.get_apis.get_current_navigation_state",
            "GetCurrentNavigationState",
        ),
        ("navigation.set_apis.set_new_navigation", "SetNewNavigation"),
        ("navigation.set_apis.delete_current_navigation", "DeleteCurrentNavigation"),
        (
            "navigation.set_apis.navigation_delete_one_waypoint",
            "NavigationDeleteOneWaypoint",
        ),
        ("charging.get_apis.get_charging_status", "GetChargingStatus"),
        (
            "charging.get_apis.calculate_charging_time_by_soc",
            "CalculateChargingTimeBySoc",
        ),
        ("vehicle_functions.set_apis.set_climate_temperature", "SetClimateTemperature"),
        ("vehicle_functions.set_apis.open_close_window", "OpenCloseWindow"),
        ("vehicle_functions.set_apis.set_fan_speed", "SetFanSpeed"),
        ("vehicle_functions.set_apis.set_air_conditioning", "SetAirConditioning"),
    ]
    native_tools = {}
    for path, clsname in definitions:
        cls = getattr(importlib.import_module(prefix + ".tools." + path), clsname)
        native_tools[cls.get_info()["function"]["name"]] = cls
    _loaded = context, fixed, data, policy, errors, native_tools, manifest
    return _loaded


class FixtureRepository:
    def __init__(self, case):
        self.locations, self.pois = deepcopy(case["locations"]), deepcopy(case["pois"])
        self.routes = {r["route_id"]: deepcopy(r) for r in case["routes"]}

    def get_route_by_id(self, identifier):
        return deepcopy(self.routes.get(identifier))

    def get_location_by_id(self, identifier):
        return deepcopy(self.locations.get(identifier))

    def get_poi_by_id(self, identifier):
        return deepcopy(self.pois.get(identifier))

    def get_routes_location_to_location(self, start, end):
        return [
            deepcopy(r)
            for r in self.routes.values()
            if r["start_id"] == start and r["destination_id"] == end
        ]

    get_routes_location_to_poi = get_routes_location_to_location
    get_routes_poi_to_location = get_routes_location_to_location


class Backend:
    def __init__(self, case):
        self.case = case
        (
            self.context,
            self.fixed,
            self.data,
            self.policy,
            self.errors,
            self.tools,
            self.provenance,
        ) = load_source()
        self.state = self.context.ContextState(**case["initial"])
        self.fixed_state = self.fixed.FixedContext(**case["fixed"])
        self.repository = FixtureRepository(case)
        self.initial = self.snapshot()
        self.failure_pending = case["inject_first_navigation_failure"]
        self.trace = []

    @contextmanager
    def scope(self):
        pairs = [
            (self.context.context_state, self.state),
            (self.fixed.fixed_context, self.fixed_state),
            (self.policy.policy_errors_during_runtime, []),
            (self.errors.tool_execution_errors_during_runtime, []),
        ]
        tokens = [(var, var.set(value)) for var, value in pairs]
        previous = self.data.car_va_data_manager._instance
        self.data.car_va_data_manager._instance = self.repository
        try:
            yield
        finally:
            self.data.car_va_data_manager._instance = previous
            for var, token in reversed(tokens):
                var.reset(token)

    def snapshot(self):
        return self.state.model_dump(mode="json")

    def schemas(self):
        schemas = [deepcopy(t.get_info()) for t in self.tools.values()]
        for schema in schemas:
            fn = schema["function"]
            if fn["name"] == "set_new_navigation":
                fn["description"] += (
                    " Implementation clarification: requires navigation inactive; if active, edit a waypoint or delete navigation before setting a new route."
                )
        return schemas + [
            tool(
                "get_vehicle_state",
                "Read current vehicle state, local time, location, a local place directory and energy model. No user goal is revealed.",
            ),
            tool(
                "get_user_profile",
                "Read authorized stable route preferences and dated climate history. Current explicit instructions take precedence.",
            ),
            tool(
                "respond_to_user",
                "Speak to the user. Set await_reply=true for a question or proposal needing a reply; false to end the episode. Only this message is heard by the user.",
                {
                    "message": {"type": "string", "minLength": 1},
                    "await_reply": {"type": "boolean"},
                },
                ["message", "await_reply"],
            ),
        ]

    def _validate_identifiers(self, name, args):
        locations = set(self.repository.locations) | set(self.repository.pois)
        plugs = {
            p["plug_id"]
            for poi in self.repository.pois.values()
            for p in poi.get("charging_plugs", [])
        }
        for key, value in args.items():
            if key == "route_ids":
                if not value or any(v not in self.repository.routes for v in value):
                    return "Unknown or empty route IDs"
            elif (
                key in {"route_id", "route_id_without_waypoint"}
                and value not in self.repository.routes
            ):
                return "Unknown route ID"
            elif (
                key
                in {
                    "start_id",
                    "destination_id",
                    "waypoint_id_to_delete",
                    "charging_station_id",
                }
                and value not in locations
            ):
                return "Unknown location/POI ID"
            elif key == "charging_station_plug_id" and value not in plugs:
                return "Unknown plug ID"
        if (
            name == "navigation_delete_waypoint"
            and args["waypoint_id_to_delete"] not in self.state.waypoints_id[1:-1]
        ):
            return "Only an existing intermediate waypoint may be deleted"
        return None

    def execute(self, name, args, event_index=None):
        before = self.snapshot()
        schema = next(
            (
                s["function"]["parameters"]
                for s in self.schemas()
                if s["function"]["name"] == name
            ),
            None,
        )
        error = None
        if schema is None or name == "respond_to_user":
            error = "Unknown environment tool"
        else:
            try:
                jsonschema.validate(args, schema)
                error = self._validate_identifiers(name, args)
            except jsonschema.ValidationError:
                error = "Arguments do not match tool schema"
        native_errors, policy_errors = [], []
        injected = False
        if error:
            result = {"status": "FAILURE", "error": error}
        elif name == "get_vehicle_state":
            result = {
                "status": "SUCCESS",
                "result": self.snapshot(),
                "context": public_context(self.case),
            }
        elif name == "get_user_profile":
            result = {"status": "SUCCESS", "result": deepcopy(self.case["profile"])}
        else:
            with self.scope(), redirect_stdout(io.StringIO()):
                raw = self.tools[name].invoke(data={}, **args)
                result = json.loads(raw) if isinstance(raw, str) else raw
                native_errors = list(
                    self.errors.tool_execution_errors_during_runtime.get()
                )
                policy_errors = list(self.policy.policy_errors_during_runtime.get())
            # Inject only after validating that the attempted native operation WOULD
            # succeed. Roll back atomically and clear its derived errors.
            if (
                self.failure_pending
                and name
                in {
                    "set_new_navigation",
                    "delete_current_navigation",
                    "navigation_delete_waypoint",
                }
                and result.get("status") == "SUCCESS"
            ):
                self.state = self.context.ContextState(**before)
                self.failure_pending = False
                injected = True
                result = {
                    "status": "FAILURE",
                    "error": "Temporary navigation service failure; state unchanged. A later retry is permitted.",
                }
        entry = {
            "event": event_index,
            "tool": name,
            "arguments": deepcopy(args),
            "before": before,
            "after": self.snapshot(),
            "result": result,
            "injected_failure": injected,
            "native_errors": native_errors,
            "native_policy_errors": policy_errors,
        }
        self.trace.append(entry)
        return deepcopy(result)
