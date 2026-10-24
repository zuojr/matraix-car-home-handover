"""Integration tests for ExperimentService with fake Harbor + persona pool."""

from __future__ import annotations

import json
from pathlib import Path

from backend.service.experiment_service import ExperimentError, ExperimentService

REPO_ROOT = Path(__file__).resolve().parents[4]
EXPERIMENT_TASK = "experiments/tasks/web-compare-options"
SURVEY_SUT_TASK = "experiments/tasks/survey-onboarding-framing"
SURVEY_PUT_TASK = "experiments/tasks/survey-trust-by-segment"
SURVEY_ABN_TASK = "experiments/tasks/survey-upgrade-copy"


class FakeHarbor:
    def __init__(self, repo_root: Path, jobs_dir: Path):
        self.repo_root = repo_root
        self.jobs_dir = jobs_dir
        self.launches: list[dict] = []
        self.deleted: list[str] = []

    def launch(self, **kwargs):
        self.launches.append(kwargs)
        return kwargs["job_name"]

    def delete_job(self, job_name: str) -> None:
        self.deleted.append(job_name)


class FakePersonaPool:
    def __init__(self, ids):
        self.ids = list(ids)

    def sample_pool(self, **kwargs):
        return {"pool": kwargs["persona_pool"], "personaIds": list(self.ids)}


def _service(tmp_path):
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    harbor = FakeHarbor(REPO_ROOT, jobs_dir)
    pool = FakePersonaPool(["0001", "0002", "0003", "0004"])
    svc = ExperimentService(
        harbor=harbor,
        persona_pool=pool,
        repo_root=REPO_ROOT,
        runs_dir=tmp_path / "runs",
    )
    return svc, harbor


def test_preview_expands_cells_without_launch(tmp_path):
    svc, harbor = _service(tmp_path)
    preview = svc.preview_design(task=EXPERIMENT_TASK, design_type="full_factorial")
    assert preview["appType"] == "web"
    assert len(preview["design"]["cells"]) == 2  # target_url has two levels
    assert harbor.launches == []


def test_create_launches_one_job_per_cell_with_param_env(tmp_path):
    svc, harbor = _service(tmp_path)
    manifest = svc.create_experiment(task=EXPERIMENT_TASK, design_type="ab_n", per_arm=4)

    assert len(manifest["cells"]) == 2
    assert len(harbor.launches) == 2
    for cell, launch in zip(manifest["cells"], harbor.launches):
        assert cell["jobName"] == launch["job_name"]
        env = launch["extra_launch_env"]
        assert "MATRIX_PARAM_TARGET_URL" in env
        assert env["EXPERIMENTS_TASK_DIR"].endswith("web-compare-options")
        # shared cohort: every arm runs the same personas
        assert launch["persona_ids"] == ["0001", "0002", "0003", "0004"]

    # manifest persisted + listable
    listed = svc.list_experiments()
    assert any(e["experimentId"] == manifest["experimentId"] for e in listed)


def test_list_experiment_tasks_includes_web_compare_options(tmp_path):
    svc, _ = _service(tmp_path)
    tasks = svc.list_experiment_tasks()
    by_task = {t["task"]: t for t in tasks}
    assert EXPERIMENT_TASK in by_task
    entry = by_task[EXPERIMENT_TASK]
    assert entry["appType"] == "web"
    assert entry["factorCount"] >= 1
    assert entry["signalCount"] >= 1
    assert entry["domain"] == "software"
    assert entry["difficulty"] == "medium"
    assert entry["name"] == "Explore the product and decide whether to sign up"
    assert "signup_clicked" in (entry.get("primaryMetrics") or [])
    assert "Landing page design" in (entry.get("factorLabels") or [])
    assert entry.get("controlLabel") == "Variant A - value framing"

    onboarding = by_task[SURVEY_SUT_TASK]
    assert onboarding.get("controlLabel") == "Feature-framed"
    upgrade = by_task[SURVEY_ABN_TASK]
    assert upgrade.get("controlLabel") == "Social proof"
    assert upgrade["axis"] == "sut"


def test_create_with_explicit_cohort_skips_sampling(tmp_path):
    svc, harbor = _service(tmp_path)
    # sentinel: if sample_pool is called, it would return these instead
    svc.persona_pool = FakePersonaPool(["9999"])
    explicit = ["p1", "p2", "p3"]
    svc.create_experiment(
        task=EXPERIMENT_TASK,
        design_type="ab_n",
        persona_ids=explicit,
        persona_pool="persona/datasets/custom",
    )
    assert harbor.launches, "expected launches"
    for launch in harbor.launches:
        assert launch["persona_ids"] == explicit
        assert launch["persona_pool"] == "persona/datasets/custom"
        assert "9999" not in launch["persona_ids"]


def test_per_arm_overrides_authored_size(tmp_path):
    """UI 'personas per arm' must replace the authored sample size."""

    class RecordingPool(FakePersonaPool):
        def __init__(self):
            super().__init__([f"{i:04d}" for i in range(1, 101)])
            self.calls: list[dict] = []

        def sample_pool(self, **kwargs):
            self.calls.append(kwargs)
            return super().sample_pool(**kwargs)

    svc, harbor = _service(tmp_path)
    pool = RecordingPool()
    svc.persona_pool = pool
    manifest = svc.create_experiment(
        task=SURVEY_SUT_TASK,
        design_type="ab_n",
        per_arm=100,
    )
    assert pool.calls, "expected cohort sampling"
    call = pool.calls[0]
    assert call["sample_size"] == 100
    assert call.get("sample_size_per_value_group") is None
    assert manifest["sampling"]["perArm"] == 100
    assert len(manifest["sampling"]["personaIds"]) == 100
    assert len(harbor.launches) == 2
    for launch in harbor.launches:
        assert len(launch["persona_ids"]) == 100


def test_survey_upgrade_copy_is_three_arm_abn_with_portions(tmp_path):
    """A/B/n survey: three copy arms, cohort mixed by declared segment shares."""
    svc, harbor = _service(tmp_path)
    preview = svc.preview_design(task=SURVEY_ABN_TASK)
    assert preview["appType"] == "survey"
    assert preview["design"]["type"] == "ab_n"
    assert len(preview["design"]["cells"]) == 3
    assert [c["factorLevels"]["context_variant"] for c in preview["design"]["cells"]] == [
        "social_proof",
        "savings",
        "premium",
    ]

    detail = svc.get_experiment_task(SURVEY_ABN_TASK)
    sampling = detail["cohortStrategy"]["sampling"]
    assert sampling["mode"] == "stratified"
    assert sampling["allocation"] == "proportional"
    assert sampling["portions"]["economic_motivation"] == {
        "Cost-sensitive": 0.5,
        "Value-driven": 0.3,
        "Premium-seeking": 0.2,
    }

    manifest = svc.create_experiment(task=SURVEY_ABN_TASK, design_type="ab_n", per_arm=4)
    assert len(manifest["cells"]) == 3
    assert len(harbor.launches) == 3
    for launch in harbor.launches:
        assert "MATRIX_PARAM_CONTEXT_VARIANT" in launch["extra_launch_env"]
        assert launch["persona_ids"] == ["0001", "0002", "0003", "0004"]


def test_blank_per_arm_keeps_authored_strategy(tmp_path):
    """Blank per_arm keeps the task's authored sampling (random sampleSize here)."""

    class RecordingPool(FakePersonaPool):
        def __init__(self):
            super().__init__([f"{i:04d}" for i in range(1, 13)])
            self.calls: list[dict] = []

        def sample_pool(self, **kwargs):
            self.calls.append(kwargs)
            return {"pool": kwargs["persona_pool"], "personaIds": list(self.ids)}

    svc, harbor = _service(tmp_path)
    pool = RecordingPool()
    svc.persona_pool = pool
    svc.create_experiment(task=SURVEY_SUT_TASK, design_type="ab_n", per_arm=None)
    assert pool.calls
    call = pool.calls[0]
    # authored survey-onboarding-framing strategy: mode=random, sampleSize=12
    assert call.get("sample_size") == 12
    assert call.get("sample_size_per_value_group") is None
    assert call.get("stratify_fields") is None


def _write_trial(job_dir: Path, trial: str, persona_id: str, facets: dict):
    tdir = job_dir / trial
    (tdir / "verifier").mkdir(parents=True)
    (tdir / "config.json").write_text(
        json.dumps({"agent": {"kwargs": {"persona_path": f"persona/x/persona_{persona_id}.yaml"}}}),
        encoding="utf-8",
    )
    (tdir / "result.json").write_text(json.dumps({"status": "done"}), encoding="utf-8")
    (tdir / "verifier" / "structured_output.json").write_text(
        json.dumps({"contexts": [{"facets": [{"key": k, "value": v} for k, v in facets.items()]}]}),
        encoding="utf-8",
    )


def test_analysis_pairs_arms_and_flags_significance(tmp_path):
    svc, harbor = _service(tmp_path)
    manifest = svc.create_experiment(task=EXPERIMENT_TASK, design_type="ab_n", per_arm=4)
    baseline_cell, treat_cell = manifest["cells"]

    personas = ["0001", "0002", "0003", "0004"]
    base_ratings = [5, 6, 5, 6]
    for pid, r in zip(personas, base_ratings):
        _write_trial(
            harbor.jobs_dir / baseline_cell["jobName"], f"t_{pid}", pid,
            {"overall_experience_rating": r, "chosen_option": "Free", "effort_rating": 3},
        )
        _write_trial(
            harbor.jobs_dir / treat_cell["jobName"], f"t_{pid}", pid,
            {"overall_experience_rating": r + 3, "chosen_option": "Plus", "effort_rating": 3},
        )

    analysis = svc.get_experiment_analysis(manifest["experimentId"])
    assert analysis["baselineCell"] == baseline_cell["cellId"]

    by_metric = {c["metricKey"]: c for c in analysis["comparisons"]}
    # primary numerical metric detects the +3 paired shift
    rating = by_metric["overall_experience_rating"]
    assert rating["kind"] == "numerical"
    assert rating["paired"] is True
    assert rating["effect"]["diff"] == 3.0
    assert rating["significant"] is True
    # guardrail is unchanged -> not significant
    assert by_metric["effort_rating"]["significant"] is False


def test_get_experiment_task_returns_hypothesis_design_and_cohort(tmp_path):
    svc, _ = _service(tmp_path)
    detail = svc.get_experiment_task(EXPERIMENT_TASK)
    assert detail["appType"] == "web"
    assert detail["hypothesis"]  # non-empty declared hypothesis
    assert detail["declaredDesignType"] == "ab_n"
    assert detail["design"]["type"] == "ab_n"
    # cohort strategy comes from persona_strategy.json
    sampling = detail["cohortStrategy"]["sampling"]
    assert sampling.get("mode") == "stratified"
    assert sampling.get("allocation") == "proportional"
    assert "company_size" in (sampling.get("fields") or [])
    # pool is a run-time choice, not part of the task cohort contract
    assert "pool" in detail["cohortStrategy"]


def test_preview_uses_task_declared_design_when_unspecified(tmp_path):
    svc, _ = _service(tmp_path)
    preview = svc.preview_design(task=EXPERIMENT_TASK)
    assert preview["design"]["type"] == "ab_n"
    assert preview["hypothesis"]


def test_create_put_launches_one_job_per_persona_arm(tmp_path):
    svc, harbor = _service(tmp_path)
    manifest = svc.create_experiment(
        task=EXPERIMENT_TASK,
        axis="put",
        put_dimension="economic_motivation",
        put_arms=[
            {"label": "Cost-sensitive", "dimensionValue": "Cost-sensitive", "personaIds": ["a1", "a2"]},
            {"label": "Premium-seeking", "dimensionValue": "Premium-seeking", "personaIds": ["b1", "b2"]},
        ],
    )
    assert manifest["axis"] == "put"
    assert manifest["design"]["type"] == "put"
    assert len(manifest["cells"]) == 2
    assert len(harbor.launches) == 2
    # each arm runs its OWN personas on the same (baseline) environment
    assert harbor.launches[0]["persona_ids"] == ["a1", "a2"]
    assert harbor.launches[1]["persona_ids"] == ["b1", "b2"]
    envs = {tuple(sorted(launch["extra_launch_env"].items())) for launch in harbor.launches}
    assert len(envs) == 1  # identical environment across arms
    assert manifest["cells"][0]["baseline"] is True


def test_analysis_reports_confidence_interval_and_delta_pct(tmp_path):
    svc, harbor = _service(tmp_path)
    manifest = svc.create_experiment(task=EXPERIMENT_TASK, design_type="ab_n", per_arm=4)
    baseline_cell, treat_cell = manifest["cells"]
    personas = ["0001", "0002", "0003", "0004"]
    for pid, r in zip(personas, [4, 5, 4, 5]):
        _write_trial(harbor.jobs_dir / baseline_cell["jobName"], f"t_{pid}", pid, {"overall_experience_rating": r})
        _write_trial(harbor.jobs_dir / treat_cell["jobName"], f"t_{pid}", pid, {"overall_experience_rating": r + 2})
    analysis = svc.get_experiment_analysis(manifest["experimentId"])
    rating = next(c for c in analysis["comparisons"] if c["metricKey"] == "overall_experience_rating")
    effect = rating["effect"]
    assert "ci" in effect and len(effect["ci"]) == 2
    assert effect["ci"][0] <= effect["diff"] <= effect["ci"][1]
    assert effect["deltaPct"] > 0  # baseline mean 4.5, +2 shift


def test_list_tasks_carry_axis_and_includes_survey_tasks(tmp_path):
    svc, _ = _service(tmp_path)
    by_task = {t["task"]: t for t in svc.list_experiment_tasks()}
    assert by_task[EXPERIMENT_TASK]["axis"] == "sut"
    assert SURVEY_SUT_TASK in by_task
    assert SURVEY_PUT_TASK in by_task
    assert by_task[SURVEY_SUT_TASK]["axis"] == "sut"
    put = by_task[SURVEY_PUT_TASK]
    assert put["axis"] == "put"
    assert put["putDimension"] == "economic_motivation"


def test_get_experiment_task_put_exposes_dimension_and_values(tmp_path):
    svc, _ = _service(tmp_path)
    detail = svc.get_experiment_task(SURVEY_PUT_TASK)
    assert detail["axis"] == "put"
    assert detail["putDimension"] == "economic_motivation"
    # the contrast values come from persona_strategy dimensionFilters
    values = detail["cohortStrategy"]["dimensionFilters"]["economic_motivation"]
    assert "Premium-seeking" in values


def test_create_put_defaults_axis_and_dimension_from_task(tmp_path):
    svc, harbor = _service(tmp_path)
    manifest = svc.create_experiment(
        task=SURVEY_PUT_TASK,
        put_arms=[
            {"label": "Cost-sensitive", "dimensionValue": "Cost-sensitive", "personaIds": ["a1"]},
            {"label": "Premium-seeking", "dimensionValue": "Premium-seeking", "personaIds": ["b1"]},
        ],
    )
    assert manifest["axis"] == "put"
    assert manifest["design"]["putDimension"] == "economic_motivation"
    assert len(harbor.launches) == 2


def test_split_arm_assignment_partitions_cohort(tmp_path, monkeypatch):
    """SUT split: cohort is partitioned into disjoint per-arm groups (between-subject)."""
    svc, harbor = _service(tmp_path)
    svc.persona_pool = FakePersonaPool([f"{i:04d}" for i in range(1, 9)])  # 8 ids
    monkeypatch.setattr(svc, "_declared_arm_assignment", lambda cfg: "split")
    manifest = svc.create_experiment(task=EXPERIMENT_TASK, design_type="ab_n", per_arm=8)

    assert manifest["armAssignment"] == "split"
    assert manifest["sampling"]["armAssignment"] == "split"
    groups = [set(launch["persona_ids"]) for launch in harbor.launches]
    assert len(groups) == 2  # two arms
    assert groups[0].isdisjoint(groups[1])  # no persona spans arms
    assert set().union(*groups) == {f"{i:04d}" for i in range(1, 9)}  # full coverage
    assert all(len(g) == 4 for g in groups)  # size-balanced


def test_shared_arm_assignment_reuses_cohort(tmp_path):
    """SUT shared (default): the same cohort runs every arm (within-subject)."""
    svc, harbor = _service(tmp_path)
    manifest = svc.create_experiment(task=EXPERIMENT_TASK, design_type="ab_n", per_arm=4)
    assert manifest["armAssignment"] == "shared"
    ids = [tuple(launch["persona_ids"]) for launch in harbor.launches]
    assert ids[0] == ids[1]  # identical cohort across arms


def test_create_sut_is_default_axis_for_web_task(tmp_path):
    svc, harbor = _service(tmp_path)
    manifest = svc.create_experiment(task=EXPERIMENT_TASK, per_arm=4)
    assert manifest["axis"] == "sut"
    assert len(harbor.launches) == 2


def test_persona_model_threads_to_every_launch(tmp_path):
    svc, harbor = _service(tmp_path)
    manifest = svc.create_experiment(
        task=EXPERIMENT_TASK,
        per_arm=4,
        persona_model="anthropic/claude-sonnet-4-6",
    )
    assert manifest["personaModel"] == "anthropic/claude-sonnet-4-6"
    assert harbor.launches, "expected launches"
    for launch in harbor.launches:
        assert launch["persona_model"] == "anthropic/claude-sonnet-4-6"


def test_persona_model_omitted_when_unset(tmp_path):
    svc, harbor = _service(tmp_path)
    manifest = svc.create_experiment(task=EXPERIMENT_TASK, per_arm=4)
    assert manifest["personaModel"] is None
    for launch in harbor.launches:
        assert "persona_model" not in launch


def test_agent_name_threads_to_every_launch(tmp_path):
    svc, harbor = _service(tmp_path)
    manifest = svc.create_experiment(
        task=EXPERIMENT_TASK,
        per_arm=4,
        agent_name="persona-browser-use",
    )
    assert manifest["agentName"] == "persona-browser-use"
    assert harbor.launches, "expected launches"
    for launch in harbor.launches:
        assert launch["agent_name"] == "persona-browser-use"


def test_agent_name_omitted_when_unset(tmp_path):
    svc, harbor = _service(tmp_path)
    manifest = svc.create_experiment(task=EXPERIMENT_TASK, per_arm=4)
    assert manifest["agentName"] is None
    for launch in harbor.launches:
        assert "agent_name" not in launch


def test_cua_backend_threads_to_every_launch(tmp_path):
    svc, harbor = _service(tmp_path)
    manifest = svc.create_experiment(
        task=EXPERIMENT_TASK,
        per_arm=4,
        cua_backend="macos",
    )
    assert manifest["cuaBackend"] == "macos"
    assert harbor.launches, "expected launches"
    for launch in harbor.launches:
        assert launch["cua_backend"] == "macos"


def test_get_experiment_reports_progress(tmp_path):
    svc, harbor = _service(tmp_path)
    manifest = svc.create_experiment(task=EXPERIMENT_TASK, design_type="ab_n", per_arm=4)
    cell = manifest["cells"][0]
    for pid in ["0001", "0002"]:
        _write_trial(harbor.jobs_dir / cell["jobName"], f"t_{pid}", pid, {"overall_experience_rating": 7})

    detail = svc.get_experiment(manifest["experimentId"])
    assert detail["progress"]["completedTrials"] == 2


def test_delete_experiment_removes_manifest_and_arm_jobs(tmp_path):
    svc, harbor = _service(tmp_path)
    manifest = svc.create_experiment(task=EXPERIMENT_TASK, design_type="ab_n", per_arm=4)
    eid = manifest["experimentId"]
    run_dir = tmp_path / "runs" / eid
    assert (run_dir / "manifest.json").is_file()
    svc.delete_experiment(eid)
    assert not run_dir.exists()
    assert harbor.deleted == [cell["jobName"] for cell in manifest["cells"]]


def test_job_arm_index_maps_factor_labels(tmp_path):
    svc, _ = _service(tmp_path)
    manifest = svc.create_experiment(task=EXPERIMENT_TASK, design_type="ab_n", per_arm=4)
    index = svc.job_arm_index()
    assert len(index) == len(manifest["cells"])
    for cell in manifest["cells"]:
        meta = index[cell["jobName"]]
        assert meta["experimentId"] == manifest["experimentId"]
        assert meta["armLabel"]
        assert meta["factorLevels"] == cell["factorLevels"]
        # Single-factor arms collapse Factor=Level → Level for list titles.
        assert "=" not in meta["armLabel"] or " · " in meta["armLabel"]


def test_delete_missing_experiment_raises(tmp_path):
    svc, _ = _service(tmp_path)
    try:
        svc.delete_experiment("exp-nope-00000000")
    except ExperimentError:
        return
    raise AssertionError("expected ExperimentError")
