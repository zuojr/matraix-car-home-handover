"""Versioned simulator diagnostics. On-state time is not electrical energy."""

from statistics import mean

from .task_contracts import has_measurement_contract


H5_METRIC_SCOPE = {
    "unit": "native simulator On-state minutes; not compressor minutes or kWh",
    "goal_window": "0 through the private user deadline; includes the preparation period",
    "temperature_window": "every 5-minute sample from minute 30 through the user deadline",
    "economy_preference": "goal-window On minutes <=45 plus successful handling; fixed benchmark allowance, not optimal control",
    "comparison": "same matched fixture, deadline and boundary; report temperature compliance alongside On time",
    "unsupported": [
        "electrical energy",
        "electricity cost",
        "energy-saving percentage",
        "continuous real-world comfort",
        "optimality",
        "adaptation from boundary success alone",
    ],
}


def h5_measurements(case, state):
    if case["task"] != "H5" or not has_measurement_contract(case):
        return None  # Do not reinterpret historical measurements.
    until = case["facts"]["until_minute"]
    if (
        type(until) is not int
        or until < 30
        or until % 5
        or until >= case["world"]["horizon"]
    ):
        raise ValueError(
            "H5 deadline must be a 5-minute boundary inside the independent observation window"
        )
    history = {sample["minute"]: sample for sample in state.get("history", [])}
    required = list(range(30, until + 1, 5))
    readings = [
        history[t]["temperature_c"]["bedroom"] for t in required if t in history
    ]
    complete = len(readings) == len(required)
    lo, hi = case["profile"]["acceptable_c"]
    compliant = sum(lo - 0.05 <= t <= hi + 0.05 for t in readings)
    runtime = history.get(until, {}).get("ac_on_minutes", {}).get("bedroom")
    observation_runtime = state.get("ac_on_minutes", {}).get("bedroom")
    return {
        "version": "home-h5-measurements-v1.7",
        "goal_until_minute": until,
        "observation_until_minute": case["world"]["horizon"],
        "goal_ac_on_minutes": runtime,
        "goal_ac_on_fraction": runtime / until if runtime is not None else None,
        "observation_ac_on_minutes": observation_runtime,
        "required_temperature_samples": len(required),
        "observed_temperature_samples": len(readings),
        "all_required_samples_present": complete,
        "temperature_in_range_fraction": compliant / len(required),
        "temperature_goal_met": complete and compliant == len(required),
        "mean_absolute_error_c": mean(
            abs(t - case["profile"]["ideal_c"]) for t in readings
        )
        if complete
        else None,
        "max_absolute_error_c": max(
            abs(t - case["profile"]["ideal_c"]) for t in readings
        )
        if complete
        else None,
        "electrical_energy_measured": False,
        "electrical_energy_kwh": None,
        "scope": H5_METRIC_SCOPE,
    }
