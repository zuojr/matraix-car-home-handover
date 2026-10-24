#!/usr/bin/env python3
"""Crosswalk: PSA Census / FIES / LFS public-use files → observed 1290-dim fields.

Requires a PSA data-use agreement (https://psada.psa.gov.ph/). Flatten your PUF
to JSONL with one person per row, then:

    python persona/curation/existing_data/scripts/run_pipeline.py \\
      --source psa_ph.jsonl \\
      --dataset persona/curation/existing_data/scripts/crosswalks/psa_ph.py \\
      --schema persona/schema/dimensions.json \\
      --out persona/curation/existing_data/raw/psa_ph/extraction_v1/shard_00.jsonl.gz \\
      --observed-only

Column names vary across CPH 2015/2020 and FIES releases. ``flatten()`` copies
common aliases (AGE/P07_AGE, SEX/P05_SEX, URB/URBAN_RURAL, …) onto canonical
keys.

Urbanicity uses locality on top of PSA's binary urban flag: NCR and the
highly urbanized cities map to Dense urban, the Metro Manila commuter belt
(Bulacan / Rizal / Cavite / Laguna) to Suburban, other urban barangays to
Small town, and rural to Rural. Without a province/city column the HUC and
commuter-belt rules cannot fire and urban outside NCR degrades to Small town.

NOTE: this emits four urbanicity values, so any calibration target for
``urbanicity`` must list all four. ``rake_weights`` divides by the sum of the
codes you supply while counting every observed row in the denominator, so a
target naming only a subset silently skews the margin. Derive the target from
the PUF itself with ``scripts/derive_targets_ph.py``.

This is the demographic backbone. Pair with ``wvs_ph.py`` for values/attitudes.
Run ``python crosswalks/psa_ph.py --selftest``.
"""

from __future__ import annotations

NCR_TOKENS = {
    "ncr",
    "national capital region",
    "metro manila",
    "metropolitan manila",
    "13",
    "region xiii",
    "ncr (national capital region)",
}

TAGALOG_HOME = {
    "tagalog",
    "filipino",
    "pilipino",
    "filipino/tagalog",
}

# Highly urbanized cities outside NCR, as they appear as province-level entries
# in the 2020 CPH geography. Isabela City is deliberately excluded: it is an
# independent component city (~130k), not an HUC.
#
# Split into two sets because three HUCs share a name with the province that
# surrounds them — matching "Cebu" would swallow the whole 3.3M-person province.
# Those require an explicit "City of X" / "X City" marker; the rest are
# unambiguous bare. "Quezon" is in neither set on purpose: Quezon City is NCR
# (already caught upstream) and Quezon province is not urban by default.
HUC_BARE = {
    "baguio",
    "angeles",
    "olongapo",
    "lucena",
    "puerto princesa",
    "bacolod",
    "lapu-lapu",
    "mandaue",
    "tacloban",
    "cagayan de oro",
    "iligan",
    "general santos",
    "butuan",
    "davao",
    "zamboanga",
}
HUC_CITY_MARKER_REQUIRED = {"cebu", "iloilo", "cotabato"}

# Metro Manila commuter belt. An urban barangay here is functionally suburban
# rather than a standalone town; PSA's binary urban flag cannot say so itself.
GREATER_MANILA_PROVINCES = {"bulacan", "rizal", "cavite", "laguna"}

LOCALITY_KEYS = (
    "PROV",
    "prov",
    "PROVINCE",
    "province",
    "CITY",
    "city",
    "MUNCITY",
    "muncity",
    "HUC",
    "huc",
    "P_PROV",
    "P_CITY",
)

CHRISTIAN_RELIGION = {
    "roman catholic",
    "catholic",
    "iglesia ni cristo",
    "inc",
    "aglipayan",
    "philippine independent",
    "protestant",
    "baptist",
    "methodist",
    "born again",
    "evangelical",
    "seventh day adventist",
    "seventh-day adventist",
    "christian",
    "iglesia filipina independiente",
}


def _token(row, *keys):
    for key in keys:
        v = row.get(key)
        if v is None:
            continue
        try:
            if v != v:
                continue
        except (TypeError, ValueError):
            pass
        if isinstance(v, bool):
            return str(v).lower()
        if isinstance(v, float) and v == int(v):
            return str(int(v))
        if isinstance(v, int):
            return str(v)
        s = str(v).strip().lower()
        if s and s not in {"nan", "none", "null", ""}:
            return s
    return None


def _alias_src_fields(row):
    out = dict(row)
    aliases = {
        "AGE": ("age", "P07_AGE", "p07_age", "A05_AGE"),
        "SEX": ("sex", "P05_SEX", "p05_sex", "A04_SEX"),
        "URB": ("urb", "URBAN", "urban", "URBAN_RURAL", "urban_rural", "P_URBAN"),
        "RELIGION": ("religion", "REL", "rel", "P12_REL", "p12_rel", "P12_RELIGION"),
        "MSTAT": ("mstat", "MARITAL", "marital", "P10_MSTAT", "p10_mstat"),
        "HGC": ("hgc", "EDUC", "educ", "HIGHEST_GRADE", "highest_grade", "P13_HGC", "p13_hgc"),
        "MTONGUE": ("mtongue", "MOTHER_TONGUE", "mother_tongue", "LANGUAGE", "language"),
        "REGION": ("region", "RSTR", "rstr", "REGN", "regn", "P_REGION"),
        "WORK": ("work", "EMPSTAT", "empstat", "EMPLOYMENT", "employment", "P_WORK"),
        "CHILD": ("child", "NCHILD", "nchild", "CHILDREN", "children"),
    }
    for dest, sources in aliases.items():
        if out.get(dest) is not None:
            continue
        for src in sources:
            if out.get(src) is not None:
                out[dest] = out[src]
                break
    return out


def flatten(row):
    out = _alias_src_fields(row)
    uid = row.get("user_id") or row.get("id") or row.get("PSN_ID") or row.get("person_id")
    if uid is not None:
        out["user_id"] = str(uid)
    return out


def render(row):
    bits = ["PSA census/survey respondent in the Philippines"]
    age = _token(row, "AGE", "age")
    if age:
        bits.append(f"age {age}")
    sex = _token(row, "SEX", "sex")
    if sex:
        bits.append(str(sex))
    region = _token(row, "REGION", "region")
    if region:
        bits.append(f"region {region}")
    return ", ".join(bits) + "."


def _age_bracket(row):
    raw = row.get("AGE")
    if raw is None:
        raw = row.get("age")
    if raw is None:
        return None
    try:
        if raw != raw:
            return None
        age = float(raw)
    except (TypeError, ValueError):
        token = str(raw).strip()
        if token in {
            "Under 5",
            "5-12",
            "13-17",
            "18-24",
            "25-34",
            "35-44",
            "45-54",
            "55-64",
            "65-74",
            "75-84",
            "85+",
        }:
            return token
        return None
    if age < 0:
        return None
    if age < 5:
        return "Under 5"
    if age <= 12:
        return "5-12"
    if age <= 17:
        return "13-17"
    for lo, hi, lab in (
        (18, 24, "18-24"),
        (25, 34, "25-34"),
        (35, 44, "35-44"),
        (45, 54, "45-54"),
        (55, 64, "55-64"),
        (65, 74, "65-74"),
        (75, 84, "75-84"),
    ):
        if lo <= age <= hi:
            return lab
    return "85+" if age >= 85 else None


def _region(_row):
    return "Southeast Asia"


def _is_ncr(row):
    token = _token(row, "REGION", "region")
    return token in NCR_TOKENS if token else False


def _strip_city_marker(name):
    """('City of Cebu' | 'Cebu City') -> ('cebu', True); 'Cebu' -> ('cebu', False)."""
    base = name.split("(")[0].strip().rstrip("*").strip()
    marked = False
    if base.startswith("city of "):
        base, marked = base[len("city of ") :].strip(), True
    elif base.endswith(" city"):
        base, marked = base[: -len(" city")].strip(), True
    return base, marked


def _locality_names(row):
    for key in LOCALITY_KEYS:
        v = row.get(key)
        if v is None:
            continue
        try:
            if v != v:
                continue
        except (TypeError, ValueError):
            pass
        s = str(v).strip().lower()
        if s and s not in {"nan", "none", "null", ""}:
            yield s


def _is_huc(row):
    for name in _locality_names(row):
        base, marked = _strip_city_marker(name)
        if base in HUC_BARE:
            return True
        if marked and base in HUC_CITY_MARKER_REQUIRED:
            return True
    return False


def _in_greater_manila(row):
    for name in _locality_names(row):
        base, marked = _strip_city_marker(name)
        if not marked and base in GREATER_MANILA_PROVINCES:
            return True
    return False


def _urbanicity(row):
    if _is_ncr(row):
        return "Dense urban"
    urb = _token(row, "URB", "urban")
    if urb in {"2", "rural"}:
        return "Rural"
    if urb not in {"1", "urban"}:
        return None
    # Urban outside NCR. PSA's flag is barangay-level and binary, so it cannot
    # rank density on its own — but the locality can. An HUC is a real metro
    # core; the Metro Manila commuter belt is suburban; everything else urban is
    # a poblacion, which is a small town rather than a suburb of anywhere.
    if _is_huc(row):
        return "Dense urban"
    if _in_greater_manila(row):
        return "Suburban"
    return "Small town"


def _cult_philippines(_row):
    return "Native"


def _lang_tagalog(row):
    home = _token(row, "MTONGUE", "mother_tongue", "language")
    if home in TAGALOG_HOME:
        return "Native"
    return None


def _english_proficiency(row):
    home = _token(row, "MTONGUE", "mother_tongue", "language")
    if home in {"english"}:
        return "Native"
    return None


def _education(row):
    token = _token(row, "HGC", "educ", "highest_grade")
    if token is None:
        return None
    labeled = {
        "no grade": "No formal",
        "no grade completed": "No formal",
        "none": "No formal",
        "no formal": "No formal",
        "0": "No formal",
        "00": "No formal",
        "elementary": "Primary",
        "primary": "Primary",
        "grade school": "Primary",
        "high school": "Secondary",
        "secondary": "Secondary",
        "jhs": "Secondary",
        "shs": "Secondary",
        "junior high": "Secondary",
        "senior high": "Secondary",
        "vocational": "Vocational / cert",
        "post secondary": "Vocational / cert",
        "post-secondary": "Vocational / cert",
        "college undergraduate": "Some college",
        "some college": "Some college",
        "college graduate": "Bachelor's",
        "bachelor": "Bachelor's",
        "bachelor's": "Bachelor's",
        "academic degree holder": "Master's",
        "master": "Master's",
        "master's": "Master's",
        "doctorate": "Doctorate",
        "phd": "Doctorate",
    }
    if token in labeled:
        return labeled[token]
    try:
        n = int(float(token))
    except (TypeError, ValueError):
        return None
    # CPH highest grade completed: 0 none, 1-6 elementary, 7-10 HS / K-12 JHS-SHS,
    # 11-14 college years, 15+ graduate. Too many release-specific codes → only
    # the obvious buckets; unknown codes stay null.
    if n == 0:
        return "No formal"
    if 1 <= n <= 6:
        return "Primary"
    if 7 <= n <= 10:
        return "Secondary"
    return None


def _religion(row):
    token = _token(row, "RELIGION", "religion")
    if token is None:
        return None
    if token in {"none", "no religion", "none/not reported", "0"}:
        return "None"
    if token in {"islam", "muslim", "2"}:
        return "Muslim"
    if token in {"buddhist", "buddhism"}:
        return "Buddhist"
    if token in {"hindu", "hinduism"}:
        return "Hindu"
    # CPH "Tribal religion" — 0.23% of the 2020 household population. Checked
    # before the Christian branch so a syncretic label like "tribal christian"
    # is not swallowed by the substring test below.
    if token in {"tribal", "tribal religion", "indigenous", "animist"} or "tribal" in token:
        return "Folk / traditional"
    if (
        token in CHRISTIAN_RELIGION
        or "catholic" in token
        or "christian" in token
        or token in {"1", "3", "4", "5"}  # Catholic / INC / Aglipayan / Protestant
    ):
        return "Christian"
    return None


def _children(row):
    raw = row.get("CHILD")
    if raw is None:
        raw = row.get("nchild")
    if raw is None:
        return None
    try:
        if raw != raw:
            return None
        n = int(float(raw))
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return "None"
    if n == 1:
        return "1 child"
    if n == 2:
        return "2 children"
    return "3+ children"


CROSSWALK = {
    "age_bracket": {"compute": _age_bracket, "prov": "observed"},
    "gender_identity": {
        "src": "SEX",
        "map": {
            "1": "Man",
            "male": "Man",
            "man": "Man",
            "2": "Woman",
            "female": "Woman",
            "woman": "Woman",
        },
        "prov": "observed",
    },
    "region": {"compute": _region, "prov": "observed"},
    "cult_philippines": {"compute": _cult_philippines, "prov": "observed"},
    "lang_tagalog": {"compute": _lang_tagalog, "prov": "observed"},
    "english_proficiency": {"compute": _english_proficiency, "prov": "observed"},
    "demo_ethnicity_broad": {
        "src": "MTONGUE",
        "map": {
            "chinese": "East Asian",
            "tagalog": "Southeast Asian",
            "filipino": "Southeast Asian",
            "cebuano": "Southeast Asian",
            "bisaya": "Southeast Asian",
            "ilocano": "Southeast Asian",
            "ilokano": "Southeast Asian",
            "hiligaynon": "Southeast Asian",
            "waray": "Southeast Asian",
            "bikol": "Southeast Asian",
            "bicolano": "Southeast Asian",
            "kapampangan": "Southeast Asian",
            "pangasinan": "Southeast Asian",
            "maranao": "Southeast Asian",
            "maguindanao": "Southeast Asian",
            "tausug": "Southeast Asian",
        },
        "prov": "observed",
    },
    "urbanicity": {"compute": _urbanicity, "prov": "observed"},
    "demo_marital_status": {
        "src": "MSTAT",
        "map": {
            "1": "Single",
            "single": "Single",
            "never married": "Single",
            "2": "Married",
            "married": "Married",
            "3": "Widowed",
            "widowed": "Widowed",
            "4": "Separated",
            "divorced": "Divorced",
            "divorced/separated": "Separated",
            "separated": "Separated",
            "5": "Domestic partnership",
            "live-in": "Domestic partnership",
            "common-law": "Domestic partnership",
            "living-in": "Domestic partnership",
        },
        "prov": "observed",
    },
    "demo_children_count": {"compute": _children, "prov": "observed"},
    "highest_education": {"compute": _education, "prov": "observed"},
    "demo_employment_status": {
        "src": "WORK",
        "map": {
            "employed": "Full-time",
            "full-time": "Full-time",
            "part-time": "Part-time",
            "self-employed": "Self-employed",
            "unemployed": "Unemployed",
            "student": "Student",
            "retired": "Retired",
            "housewife": "Homemaker",
            "homemaker": "Homemaker",
            "not in the labor force": None,
        },
        "prov": "observed",
    },
    "demo_religion_affiliation": {"compute": _religion, "prov": "observed"},
}


def _selftest():
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from crosswalk_engine import apply_crosswalk, load_allowed

    schema = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "..",
            "..",
            "schema",
            "dimensions.json",
        )
    )
    allowed = load_allowed(schema)

    manila = flatten(
        {
            "id": "psa-1",
            "P07_AGE": 41,
            "P05_SEX": "Female",
            "RSTR": "NCR",
            "URBAN": 1,
            "P12_REL": "Roman Catholic",
            "P10_MSTAT": 2,
            "P13_HGC": "College graduate",
            "MOTHER_TONGUE": "Tagalog",
            "EMPSTAT": "Employed",
            "NCHILD": 3,
        }
    )
    obs, prov, unmapped = apply_crosswalk(manila, CROSSWALK, allowed)
    assert obs["age_bracket"] == "35-44", obs
    assert obs["gender_identity"] == "Woman"
    assert obs["region"] == "Southeast Asia"
    assert obs["cult_philippines"] == "Native"
    assert obs["urbanicity"] == "Dense urban"  # NCR
    assert obs["lang_tagalog"] == "Native"
    assert obs["demo_ethnicity_broad"] == "Southeast Asian"
    assert obs["demo_marital_status"] == "Married"
    assert obs["highest_education"] == "Bachelor's"
    assert obs["demo_employment_status"] == "Full-time"
    assert obs["demo_religion_affiliation"] == "Christian"
    assert obs["demo_children_count"] == "3+ children"
    assert unmapped == {}
    assert all(p == "observed" for p in prov.values())

    rural = flatten(
        {
            "AGE": 8,
            "SEX": 1,
            "REGION": "Region VII (Central Visayas)",
            "URB": 2,
            "RELIGION": "Islam",
            "MSTAT": 1,
            "HGC": 3,
            "MTONGUE": "Cebuano",
        }
    )
    obs2, _, _ = apply_crosswalk(rural, CROSSWALK, allowed)
    assert obs2["age_bracket"] == "5-12"
    assert obs2["gender_identity"] == "Man"
    assert obs2["urbanicity"] == "Rural"
    assert obs2["demo_religion_affiliation"] == "Muslim"
    assert obs2["highest_education"] == "Primary"
    assert "lang_tagalog" not in obs2  # Cebuano home language ≠ Tagalog Native
    assert obs2["demo_ethnicity_broad"] == "Southeast Asian"

    # Urban outside NCR with no locality column: degrades to Small town.
    urban_not_ncr = flatten({"AGE": 30, "SEX": 2, "REGION": "Region III", "URB": 1})
    obs3, _, _ = apply_crosswalk(urban_not_ncr, CROSSWALK, allowed)
    assert obs3["urbanicity"] == "Small town", obs3

    def urb(**extra):
        row = flatten({"AGE": 30, "SEX": 2, "URB": 1, **extra})
        return apply_crosswalk(row, CROSSWALK, allowed)[0].get("urbanicity")

    # HUC -> Dense urban, bare or marked
    assert urb(REGION="Region XI", PROVINCE="City of Davao") == "Dense urban"
    assert urb(REGION="CAR", PROVINCE="Baguio") == "Dense urban"
    assert urb(REGION="Region VII", PROVINCE="City of Lapu-Lapu (Opon)") == "Dense urban"
    # the three name-collision HUCs need the city marker...
    assert urb(REGION="Region VII", PROVINCE="City of Cebu") == "Dense urban"
    assert urb(REGION="Region VI", PROVINCE="Iloilo City") == "Dense urban"
    # ...and the surrounding province must NOT be upgraded with them
    assert urb(REGION="Region VII", PROVINCE="Cebu") == "Small town"
    assert urb(REGION="Region VI", PROVINCE="Iloilo") == "Small town"
    assert urb(REGION="Region XII", PROVINCE="Cotabato") == "Small town"
    # Quezon province must not be read as Quezon City
    assert urb(REGION="Region IV-A", PROVINCE="Quezon *") == "Small town"
    # commuter belt -> Suburban, and a rural row there is still Rural
    assert urb(REGION="Region III", PROVINCE="Bulacan") == "Suburban"
    assert urb(REGION="Region IV-A", PROVINCE="Cavite") == "Suburban"
    rural_belt = flatten({"AGE": 30, "SEX": 2, "URB": 2, "PROVINCE": "Cavite"})
    assert apply_crosswalk(rural_belt, CROSSWALK, allowed)[0]["urbanicity"] == "Rural"
    # NCR still wins over any locality reading
    assert urb(REGION="NCR", PROVINCE="Quezon City") == "Dense urban"
    # no urban flag at all -> still unobserved
    noflag = flatten({"AGE": 30, "SEX": 2, "PROVINCE": "Bulacan"})
    assert "urbanicity" not in apply_crosswalk(noflag, CROSSWALK, allowed)[0]

    tribal = flatten({"AGE": 55, "SEX": 1, "RELIGION": "Tribal Religion"})
    obs4, _, _ = apply_crosswalk(tribal, CROSSWALK, allowed)
    assert obs4["demo_religion_affiliation"] == "Folk / traditional", obs4
    # the substring rule must not steal syncretic labels from Christian
    syncretic = flatten({"AGE": 55, "SEX": 1, "RELIGION": "Roman Catholic"})
    obs5, _, _ = apply_crosswalk(syncretic, CROSSWALK, allowed)
    assert obs5["demo_religion_affiliation"] == "Christian"

    print(f"psa_ph crosswalk self-test: {len(CROSSWALK)} dims verified ✅")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="PSA Philippines census/survey crosswalk.")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        _selftest()
    else:
        ap.print_help()
