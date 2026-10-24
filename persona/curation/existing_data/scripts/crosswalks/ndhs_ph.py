#!/usr/bin/env python3
"""Crosswalk: Philippines NDHS 2022 (DHS recode) → observed 1290-dim fields.

Obtain the file yourself under DHS terms (free account, state a research
purpose): https://dhsprogram.com/data/ — the Philippines 2022 standard DHS.
A mirror exists at https://microdata.worldbank.org/index.php/catalog/5846.

Prefer the **household member recode (PR)** file. The women's (IR) file is
women 15-49 only, so it cannot carry a population margin; the PR file covers
every household member of both sexes at all ages, which is what makes NDHS
usable for `highest_education` and `socioeconomic_band` targets.

DHS recode names are standardised across every DHS survey worldwide, so this
module accepts both the PR (``hv*``) and IR/MR (``v*``) spellings. The
country-specific code lists here were **verified against the PH-2022 DDI
codebook** (``PHL_2022_DHS_v01_M.xml``), which is why ``v130`` religion,
``v131`` ethnicity and ``v045c`` language are mapped from raw numbers at all.
Do not copy those numeric maps to another country's DHS — they are per-survey.

Two things that verification changed, both easy to get wrong:

* ``hv115`` and ``v501`` do **not** share a code list. In PH-2022 ``hv115`` has
  no code 5 and its code 4 is "Divorced/annulled/separated" — a combined
  category. Divorce is not available in the Philippines, so that maps to
  Separated, whereas ``v501`` code 4 is a clean "Divorced".
* ``v045c`` is the respondent's *native* language; ``v045b`` is the language the
  interview happened to be conducted in. Only the former is read here.

**If you have the raw REC distribution rather than the merged PR recode**, the
fields this module needs are spread across files and must be joined first:

    RECH1  (129,724 members)  hvidx hv104 hv105 hv106 hv109 hv115
    RECH0  (35,470 households) hv024 hv025 hv005
    RECH2                      hv270

Join RECH1 to RECH0 and RECH2 on ``hhid`` before converting, or region,
urbanicity, wealth and the sample weight will all be missing. The standard
``PHPR*FL.DTA`` recode already has them merged and needs no join.

    python persona/curation/existing_data/scripts/microdata_to_jsonl.py \\
      --src persona/curation/existing_data/raw/ndhs_ph/PHPR82FL.DTA \\
      --out persona/curation/existing_data/raw/ndhs_ph/ndhs_ph.jsonl \\
      --check ndhs_ph

    python persona/curation/existing_data/scripts/run_pipeline.py \\
      --source persona/curation/existing_data/raw/ndhs_ph/ndhs_ph.jsonl \\
      --dataset persona/curation/existing_data/scripts/crosswalks/ndhs_ph.py \\
      --schema persona/schema/dimensions.json \\
      --out persona/curation/existing_data/raw/ndhs_ph/extraction_v1/shard_00.jsonl.gz \\
      --observed-only

NDHS is a **sample**, not a census. Any target derived from it must be
weighted, or it describes the sample design rather than the Philippines:

    python persona/curation/existing_data/scripts/derive_targets_ph.py ... \\
      --weight-col hv005      # v005 on the IR/MR file

Two deliberate gaps, both documented at their mapping below: DHS tops education
out at "higher" with no degree detail, and it carries no province/city, so
urbanicity cannot reach Suburban the way ``psa_ph.py`` does. Run
``python crosswalks/ndhs_ph.py --selftest``.
"""

from __future__ import annotations

# hv024/v024 in PH-2022: 13 = National Capital Region (verified against the
# PHL_2022_DHS_v01_M DDI codebook). Without the numeric code, a file read with
# convert_categoricals=False would never resolve NCR at all.
NCR_TOKENS = {
    "ncr",
    "13",
    "national capital region",
    "metro manila",
    "metropolitan manila",
}

# DHS reserves the top of each numeric range for "don't know" / missing. On
# hv105 that is 98/99 against a real range of 0-95, so an unguarded cast turns
# a refusal into a 98-year-old.
DHS_MISSING_AGE = 96

TAGALOG_HOME = {
    "tagalog",
    "filipino",
    "pilipino",
    "filipino/tagalog",
    "tagalog/filipino",
}

CHRISTIAN_RELIGION = {
    "roman catholic",
    "catholic",
    "protestant",
    "iglesia ni cristo",
    "inc",
    "aglipay",
    "aglipayan",
    "philippine independent church",
    "iglesia filipina independiente",
    "born again",
    "evangelical",
    "baptist",
    "methodist",
    "seventh day adventist",
    "seventh-day adventist",
    "jehovah's witness",
    "jehovahs witness",
    "christian",
    "other christian",
}

SEA_ETHNICITY = {
    "tagalog",
    "cebuano",
    "bisaya",
    "binisaya",
    "ilocano",
    "ilokano",
    "hiligaynon",
    "ilonggo",
    "bicol",
    "bikol",
    "bicolano",
    "waray",
    "kapampangan",
    "pampango",
    "pangasinan",
    "pangasinense",
    "maranao",
    "maguindanao",
    "tausug",
    "boholano",
    "ibanag",
    "zamboangueno",
    "filipino",
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
        # PR (household member) first, then IR/MR, then upper-case variants.
        "AGE": ("hv105", "HV105", "v012", "V012", "age"),
        "SEX": ("hv104", "HV104", "v151", "V151", "sex"),
        "URBAN": ("hv025", "HV025", "v025", "V025"),
        "REGION": ("hv024", "HV024", "v024", "V024", "region"),
        # hv109/v149 are the harmonised attainment items and are strictly more
        # informative than the hv106/v106 level items, so they win.
        "EDUC": ("hv109", "HV109", "v149", "V149", "hv106", "HV106", "v106", "V106"),
        "WEALTH": ("hv270", "HV270", "v190", "V190"),
        # hv115 and v501 do NOT share a code list — see _marital.
        "MSTAT_HH": ("hv115", "HV115"),
        "MSTAT_IND": ("v501", "V501"),
        "CHILDREN": ("v218", "V218"),
        "RELIGION": ("v130", "V130", "sh_religion", "religion"),
        "ETHNICITY": ("v131", "V131", "ethnicity"),
        # v045c is the respondent's *native* language. v045b is the language the
        # interview happened to be conducted in, which is not the same thing and
        # must not stand in for it.
        "LANGUAGE": ("v045c", "V045C", "language"),
        "WEIGHT": ("hv005", "HV005", "v005", "V005"),
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
    uid = row.get("user_id") or row.get("caseid") or row.get("CASEID")
    if uid is None:
        # PR rows are identified by household id + line number, not one column.
        hh = row.get("hhid") or row.get("HHID")
        line = row.get("hvidx") or row.get("HVIDX")
        if hh is not None and line is not None:
            uid = f"{str(hh).strip()}-{line}"
    if uid is not None:
        out["user_id"] = str(uid)
    return out


def render(row):
    bits = ["Philippines NDHS 2022 household member"]
    age = _token(row, "AGE")
    if age:
        bits.append(f"age {age}")
    sex = _token(row, "SEX")
    if sex:
        bits.append(str(sex))
    region = _token(row, "REGION")
    if region:
        bits.append(f"region {region}")
    return ", ".join(bits) + "."


def _age_bracket(row):
    raw = row.get("AGE")
    if raw is None:
        return None
    try:
        if raw != raw:
            return None
        age = float(raw)
    except (TypeError, ValueError):
        return None
    # 96-99 are DHS don't-know / missing codes, not ages.
    if age < 0 or age >= DHS_MISSING_AGE:
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
    return "85+"


def _region(_row):
    return "Southeast Asia"


def _cult_philippines(_row):
    return "Native"


def _is_ncr(row):
    token = _token(row, "REGION")
    return token in NCR_TOKENS if token else False


def _urbanicity(row):
    if _is_ncr(row):
        return "Dense urban"
    urb = _token(row, "URBAN")
    if urb in {"2", "rural"}:
        return "Rural"
    if urb in {"1", "urban"}:
        # Unlike psa_ph.py there is no province/city column here, so the HUC and
        # commuter-belt rules cannot run and Suburban is unreachable from DHS.
        return "Small town"
    return None


def _education(row):
    token = _token(row, "EDUC")
    if token is None:
        return None
    labeled = {
        "no education": "No formal",
        "no education, preschool": "No formal",
        "none": "No formal",
        "preschool": "No formal",
        "incomplete primary": "Primary",
        "complete primary": "Primary",
        "primary": "Primary",
        "elementary": "Primary",
        "incomplete secondary": "Secondary",
        "complete secondary": "Secondary",
        "secondary": "Secondary",
        "high school": "Secondary",
    }
    if token in labeled:
        return labeled[token]
    # DHS "higher" means any post-secondary and carries no degree detail, so it
    # cannot be split across Some college / Bachelor's / Master's / Doctorate.
    # Left unobserved rather than collapsed onto one of them — but note this
    # censors the top of the distribution, so CPH's HGC remains the better
    # source for a highest_education margin.
    if token in {"higher", "tertiary", "college", "university"}:
        return None
    try:
        n = int(float(token))
    except (TypeError, ValueError):
        return None
    # hv109 / v149: 0 none, 1 incomplete primary, 2 complete primary,
    # 3 incomplete secondary, 4 complete secondary, 5 higher, 8/9 dk/missing.
    return {0: "No formal", 1: "Primary", 2: "Primary", 3: "Secondary", 4: "Secondary"}.get(n)


def _socioeconomic_band(row):
    token = _token(row, "WEALTH")
    if token is None:
        return None
    # DHS wealth index is a within-country relative quintile and the schema band
    # is likewise relative, so this is a direct 1:1.
    return {
        "1": "Low income",
        "poorest": "Low income",
        "2": "Lower-middle",
        "poorer": "Lower-middle",
        "3": "Middle",
        "middle": "Middle",
        "4": "Upper-middle",
        "richer": "Upper-middle",
        "5": "High income",
        "richest": "High income",
    }.get(token)


def _children(row):
    raw = row.get("CHILDREN")
    if raw is None:
        return None
    try:
        if raw != raw:
            return None
        n = int(float(raw))
    except (TypeError, ValueError):
        return None
    if n < 0:
        return None
    if n == 0:
        return "None"
    if n == 1:
        return "1 child"
    if n == 2:
        return "2 children"
    return "3+ children"


def _marital(row):
    """hv115 and v501 use different code lists — do not merge them.

    PH-2022 hv115: 0 never married, 1 married or living together, 2 living
    together, 3 widowed, 4 divorced/annulled/separated. There is no code 5, and
    code 4 is a *combined* category. Divorce is not available in the
    Philippines, so that group is overwhelmingly annulled or separated and maps
    to Separated — reading it as Divorced (the standard DHS meaning of 4) would
    be wrong for this country.

    v501 is the regular recode: 4 divorced, 5 no longer living together.
    """
    household = _token(row, "MSTAT_HH")
    if household is not None:
        return {
            "0": "Single",
            "never married": "Single",
            "1": "Married",
            "married or living together": "Married",
            "married": "Married",
            "2": "Domestic partnership",
            "living together": "Domestic partnership",
            "3": "Widowed",
            "widowed": "Widowed",
            "4": "Separated",
            "divorced/annulled/separated": "Separated",
        }.get(household)
    individual = _token(row, "MSTAT_IND")
    if individual is None:
        return None
    return {
        "0": "Single",
        "never in union": "Single",
        "never married": "Single",
        "1": "Married",
        "married": "Married",
        "2": "Domestic partnership",
        "living with partner": "Domestic partnership",
        "living together": "Domestic partnership",
        "3": "Widowed",
        "widowed": "Widowed",
        "4": "Divorced",
        "divorced": "Divorced",
        "5": "Separated",
        "separated": "Separated",
        "no longer living together/separated": "Separated",
    }.get(individual)


# PH-2022 v130 (verified against the DDI codebook): 1 Roman Catholic,
# 2 Protestant, 3 Iglesia ni Cristo, 4 Aglipay, 5 Islam, 6 Other Christian,
# 95 No religion, 96 Other. Numeric codes are safe *because* they were checked
# against this survey; do not copy this map to another country's DHS.
V130_NUMERIC = {
    "1": "Christian",
    "2": "Christian",
    "3": "Christian",
    "4": "Christian",
    "5": "Muslim",
    "6": "Christian",
    "95": "None",
}


def _religion(row):
    token = _token(row, "RELIGION")
    if token is None:
        return None
    if token.isdigit():
        # 96 "Other" is intentionally absent: it cannot be placed in the schema.
        return V130_NUMERIC.get(token)
    if token in {"no religion", "none", "atheist"}:
        return "None"
    if token in {"islam", "muslim"}:
        return "Muslim"
    if token in {"buddhist", "buddhism"}:
        return "Buddhist"
    if token in {"hindu", "hinduism"}:
        return "Hindu"
    if "tribal" in token or token in {"animist", "indigenous"}:
        return "Folk / traditional"
    if token in CHRISTIAN_RELIGION or "catholic" in token or "christian" in token:
        return "Christian"
    return None


def _ethnicity(row):
    token = _token(row, "ETHNICITY")
    if token is None:
        return None
    if token.isdigit():
        # PH-2022 v131: codes 1-87 are Filipino ethnolinguistic groups;
        # 88 "Other Nationality" and 96 "Other" are not placeable.
        n = int(token)
        return "Southeast Asian" if 1 <= n <= 87 else None
    if "chinese" in token:
        return "East Asian"
    if token in {"other", "other nationality"}:
        return None
    return "Southeast Asian" if token in SEA_ETHNICITY else None


# PH-2022 v045c native language: 1 English, 2 Tagalog, 3 Ilocano, 4 Bikol,
# 5 Waray, 6 Hiligaynon, 7 Cebuano, 96 Other.
def _lang_tagalog(row):
    token = _token(row, "LANGUAGE")
    if token is None:
        return None
    return "Native" if token == "2" or token in TAGALOG_HOME else None


def _english_proficiency(row):
    token = _token(row, "LANGUAGE")
    if token is None:
        return None
    return "Native" if token in {"1", "english"} else None


CROSSWALK = {
    "age_bracket": {"compute": _age_bracket, "prov": "observed"},
    "gender_identity": {
        "src": "SEX",
        "map": {"1": "Man", "male": "Man", "2": "Woman", "female": "Woman"},
        "prov": "observed",
    },
    "region": {"compute": _region, "prov": "observed"},
    "cult_philippines": {"compute": _cult_philippines, "prov": "observed"},
    "urbanicity": {"compute": _urbanicity, "prov": "observed"},
    "highest_education": {"compute": _education, "prov": "observed"},
    "socioeconomic_band": {"compute": _socioeconomic_band, "prov": "observed"},
    "demo_marital_status": {"compute": _marital, "prov": "observed"},
    "demo_children_count": {"compute": _children, "prov": "observed"},
    "demo_religion_affiliation": {"compute": _religion, "prov": "observed"},
    "demo_ethnicity_broad": {"compute": _ethnicity, "prov": "observed"},
    "lang_tagalog": {"compute": _lang_tagalog, "prov": "observed"},
    "english_proficiency": {"compute": _english_proficiency, "prov": "observed"},
}


def _selftest():
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from crosswalk_engine import apply_crosswalk, load_allowed

    schema = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "schema", "dimensions.json")
    )
    allowed = load_allowed(schema)

    # PR file, numeric codes (convert_categoricals=False)
    pr = flatten(
        {
            "hhid": "  001  002",
            "hvidx": 3,
            "hv105": 41,
            "hv104": 2,
            "hv024": "National Capital Region",
            "hv025": 1,
            "hv109": 4,
            "hv270": 5,
            "hv115": 1,
            "hv005": 1_234_567,
        }
    )
    obs, prov, unmapped = apply_crosswalk(pr, CROSSWALK, allowed)
    assert obs["age_bracket"] == "35-44", obs
    assert obs["gender_identity"] == "Woman"
    assert obs["region"] == "Southeast Asia"
    assert obs["cult_philippines"] == "Native"
    assert obs["urbanicity"] == "Dense urban"  # NCR
    assert obs["highest_education"] == "Secondary"
    assert obs["socioeconomic_band"] == "High income"
    assert obs["demo_marital_status"] == "Married"
    assert unmapped == {}
    assert all(p == "observed" for p in prov.values())
    assert pr["user_id"] == "001  002-3"

    # IR file, decoded labels
    ir = flatten(
        {
            "caseid": "        1  2  3",
            "v012": 28,
            "v151": "female",
            "v024": "Central Visayas",
            "v025": "rural",
            "v149": "higher",
            "v190": "poorest",
            "v501": "living together",
            "v218": 2,
            "v130": "Roman Catholic",
            "v131": "Cebuano",
            "v045c": "Tagalog",
        }
    )
    obs2, _, _ = apply_crosswalk(ir, CROSSWALK, allowed)
    assert obs2["age_bracket"] == "25-34"
    assert obs2["urbanicity"] == "Rural"
    assert obs2["socioeconomic_band"] == "Low income"
    assert obs2["demo_marital_status"] == "Domestic partnership"
    assert obs2["demo_children_count"] == "2 children"
    assert obs2["demo_religion_affiliation"] == "Christian"
    assert obs2["demo_ethnicity_broad"] == "Southeast Asian"
    assert obs2["lang_tagalog"] == "Native"
    # "higher" carries no degree detail, so it must not be guessed
    assert "highest_education" not in obs2

    # DHS missing/DK codes must not become ages or categories
    dk = flatten({"hv105": 98, "hv104": 9, "hv025": 9, "hv109": 8, "hv270": 9})
    obs3, _, _ = apply_crosswalk(dk, CROSSWALK, allowed)
    assert "age_bracket" not in obs3, obs3
    assert "gender_identity" not in obs3
    assert "urbanicity" not in obs3
    assert "highest_education" not in obs3
    assert "socioeconomic_band" not in obs3

    # PH-2022 numeric code lists, verified against the DDI codebook
    numeric = flatten({"hv105": 30, "hv024": 13, "hv025": 1, "v130": 5, "v131": 2, "v045c": 2})
    obs4, _, _ = apply_crosswalk(numeric, CROSSWALK, allowed)
    assert obs4["demo_religion_affiliation"] == "Muslim", obs4  # v130 5 = Islam
    assert obs4["demo_ethnicity_broad"] == "Southeast Asian"  # v131 2 = Cebuano
    assert obs4["lang_tagalog"] == "Native"  # v045c 2 = Tagalog
    assert obs4["urbanicity"] == "Dense urban"  # hv024 13 = NCR
    # codes that cannot be placed in the schema stay unobserved
    unplaceable = flatten({"hv105": 30, "v130": 96, "v131": 88})
    obs5, _, _ = apply_crosswalk(unplaceable, CROSSWALK, allowed)
    assert "demo_religion_affiliation" not in obs5
    assert "demo_ethnicity_broad" not in obs5

    # hv115 and v501 disagree on what 4 means; PH has no legal divorce
    hh4 = flatten({"hv105": 40, "hv115": 4})
    assert apply_crosswalk(hh4, CROSSWALK, allowed)[0]["demo_marital_status"] == "Separated"
    ind4 = flatten({"v012": 40, "v501": 4})
    assert apply_crosswalk(ind4, CROSSWALK, allowed)[0]["demo_marital_status"] == "Divorced"
    ind5 = flatten({"v012": 40, "v501": 5})
    assert apply_crosswalk(ind5, CROSSWALK, allowed)[0]["demo_marital_status"] == "Separated"
    # interview language must not be read as native language
    interview_only = flatten({"hv105": 30, "v045b": 2})
    assert "lang_tagalog" not in apply_crosswalk(interview_only, CROSSWALK, allowed)[0]

    # urban outside NCR is Small town; Suburban is unreachable from DHS
    urban = flatten({"hv105": 30, "hv024": "Calabarzon", "hv025": 1})
    obs5, _, _ = apply_crosswalk(urban, CROSSWALK, allowed)
    assert obs5["urbanicity"] == "Small town"

    print(f"ndhs_ph crosswalk self-test: {len(CROSSWALK)} dims verified ✅")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Philippines NDHS 2022 (DHS recode) crosswalk.")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        _selftest()
    else:
        ap.print_help()
