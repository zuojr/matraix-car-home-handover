"""Philippines ingest: WVS-PH / PSA crosswalks and the Playground strategy file."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from persona.curation.existing_data.scripts.crosswalk_engine import (
    apply_crosswalk,
    load_allowed,
)
from persona.curation.existing_data.scripts.crosswalks import ndhs_ph, psa_ph, wvs_ph

REPO = Path(__file__).resolve().parents[4]
SCHEMA = REPO / "persona" / "schema" / "dimensions.json"
STRATEGY = (
    REPO
    / "persona"
    / "curation"
    / "existing_data"
    / "philippines"
    / "persona_strategy.json"
)
SAMPLES = REPO / "persona" / "curation" / "existing_data" / "samples" / "philippines"


@pytest.fixture(scope="module")
def allowed():
    return load_allowed(str(SCHEMA))


def test_strategy_filters_are_schema_values(allowed):
    strategy = json.loads(STRATEGY.read_text(encoding="utf-8"))
    filters = strategy["dimensionFilters"]
    sampling = strategy["sampling"]
    assert sampling["fields"]
    for field in sampling["fields"]:
        assert field in filters
    for dim, values in filters.items():
        assert dim in allowed, dim
        for value in values:
            assert value in allowed[dim], (dim, value)


def test_wvs_ph_sample_rows(allowed):
    rows = [
        json.loads(line)
        for line in (SAMPLES / "wvs_ph_sample.jsonl").read_text().splitlines()
        if line.strip()
    ]
    ph, student, usa = (wvs_ph.flatten(r) for r in rows)

    obs, _, unmapped = apply_crosswalk(ph, wvs_ph.CROSSWALK, allowed)
    assert unmapped == {}
    assert obs["region"] == "Southeast Asia"
    assert obs["cult_philippines"] == "Native"
    assert obs["lang_tagalog"] == "Native"
    assert obs["gender_identity"] == "Woman"

    obs_s, _, _ = apply_crosswalk(student, wvs_ph.CROSSWALK, allowed)
    assert obs_s["cult_philippines"] == "Lived there"  # born elsewhere, interviewed in PH
    assert obs_s["english_proficiency"] == "Native"
    assert "lang_tagalog" not in obs_s
    assert "urbanicity" not in obs_s  # urban too coarse
    assert obs_s["demo_employment_status"] == "Student"

    obs_us, _, _ = apply_crosswalk(usa, wvs_ph.CROSSWALK, allowed)
    assert "region" not in obs_us
    assert "cult_philippines" not in obs_us


def test_psa_ph_sample_rows(allowed):
    rows = [
        json.loads(line)
        for line in (SAMPLES / "psa_ph_sample.jsonl").read_text().splitlines()
        if line.strip()
    ]
    ncr, visayas, luzon = (psa_ph.flatten(r) for r in rows)

    ncr_obs, _, unmapped = apply_crosswalk(ncr, psa_ph.CROSSWALK, allowed)
    assert unmapped == {}
    assert ncr_obs["urbanicity"] == "Dense urban"
    assert ncr_obs["lang_tagalog"] == "Native"
    assert ncr_obs["highest_education"] == "Bachelor's"

    vis = apply_crosswalk(visayas, psa_ph.CROSSWALK, allowed)[0]
    assert vis["age_bracket"] == "5-12"
    assert vis["urbanicity"] == "Rural"
    assert vis["demo_religion_affiliation"] == "Muslim"
    assert "lang_tagalog" not in vis

    luz = apply_crosswalk(luzon, psa_ph.CROSSWALK, allowed)[0]
    # urban, not NCR, no province column -> the HUC / commuter-belt rules cannot
    # fire, so it degrades to Small town rather than going unobserved
    assert luz["urbanicity"] == "Small town"
    assert luz["highest_education"] == "Some college"
    assert luz["demo_marital_status"] == "Domestic partnership"
    assert luz["demo_religion_affiliation"] == "Christian"


def test_ndhs_ph_sample_rows(allowed):
    rows = [
        json.loads(line)
        for line in (SAMPLES / "ndhs_ph_sample.jsonl").read_text().splitlines()
        if line.strip()
    ]
    pr, ir, elder = (ndhs_ph.flatten(r) for r in rows)

    pr_obs, _, unmapped = apply_crosswalk(pr, ndhs_ph.CROSSWALK, allowed)
    assert unmapped == {}
    assert pr_obs["age_bracket"] == "35-44"
    assert pr_obs["gender_identity"] == "Woman"
    assert pr_obs["urbanicity"] == "Dense urban"  # NCR
    assert pr_obs["socioeconomic_band"] == "High income"  # wealth quintile 5

    ir_obs = apply_crosswalk(ir, ndhs_ph.CROSSWALK, allowed)[0]
    assert ir_obs["urbanicity"] == "Rural"
    assert ir_obs["socioeconomic_band"] == "Low income"
    assert ir_obs["demo_children_count"] == "2 children"
    assert ir_obs["demo_religion_affiliation"] == "Christian"
    # DHS "higher" has no degree detail and must not be guessed at
    assert "highest_education" not in ir_obs

    eld = apply_crosswalk(elder, ndhs_ph.CROSSWALK, allowed)[0]
    assert eld["age_bracket"] == "65-74"
    assert eld["urbanicity"] == "Small town"  # urban, not NCR, no province
    assert eld["demo_marital_status"] == "Widowed"


def test_ndhs_ph_rejects_dhs_missing_codes(allowed):
    """98/99 are don't-know codes; an unguarded cast makes them ages and levels."""
    row = ndhs_ph.flatten({"hv105": 98, "hv104": 9, "hv025": 9, "hv109": 8, "hv270": 9})
    obs = apply_crosswalk(row, ndhs_ph.CROSSWALK, allowed)[0]
    for dim in ("age_bracket", "gender_identity", "urbanicity", "highest_education", "socioeconomic_band"):
        assert dim not in obs, dim

    # codes with no schema home stay unobserved (v130 96 "Other",
    # v131 88 "Other Nationality")
    unplaceable = ndhs_ph.flatten({"hv105": 30, "v130": 96, "v131": 88})
    obs2 = apply_crosswalk(unplaceable, ndhs_ph.CROSSWALK, allowed)[0]
    assert "demo_religion_affiliation" not in obs2
    assert "demo_ethnicity_broad" not in obs2


def test_ndhs_ph_uses_verified_ph2022_code_lists(allowed):
    """Numeric maps come from the PH-2022 DDI codebook, not the DHS generic defaults."""
    row = ndhs_ph.flatten(
        {"hv105": 30, "hv024": 13, "hv025": 1, "v130": 5, "v131": 2, "v045c": 2}
    )
    obs = apply_crosswalk(row, ndhs_ph.CROSSWALK, allowed)[0]
    assert obs["urbanicity"] == "Dense urban"  # hv024 13 = National Capital Region
    assert obs["demo_religion_affiliation"] == "Muslim"  # v130 5 = Islam
    assert obs["demo_ethnicity_broad"] == "Southeast Asian"  # v131 2 = Cebuano
    assert obs["lang_tagalog"] == "Native"  # v045c 2 = Tagalog


def test_ndhs_ph_marital_codes_differ_between_files(allowed):
    """hv115 and v501 assign different meanings to code 4.

    PH-2022 hv115 code 4 is the combined "Divorced/annulled/separated" and has
    no code 5; divorce is not available in the Philippines. v501 code 4 is a
    clean "Divorced". Sharing one map between them mislabels the household file.
    """
    hh = ndhs_ph.flatten({"hv105": 40, "hv115": 4})
    assert apply_crosswalk(hh, ndhs_ph.CROSSWALK, allowed)[0]["demo_marital_status"] == "Separated"

    ind = ndhs_ph.flatten({"v012": 40, "v501": 4})
    assert apply_crosswalk(ind, ndhs_ph.CROSSWALK, allowed)[0]["demo_marital_status"] == "Divorced"

    sep = ndhs_ph.flatten({"v012": 40, "v501": 5})
    assert apply_crosswalk(sep, ndhs_ph.CROSSWALK, allowed)[0]["demo_marital_status"] == "Separated"


def test_ndhs_ph_interview_language_is_not_native_language(allowed):
    """v045b is the language the interview was conducted in, not v045c native language."""
    row = ndhs_ph.flatten({"hv105": 30, "v045b": 2})
    obs = apply_crosswalk(row, ndhs_ph.CROSSWALK, allowed)[0]
    assert "lang_tagalog" not in obs
    assert "english_proficiency" not in obs


def test_wvs_and_psa_selftests():
    wvs_ph._selftest()
    psa_ph._selftest()
