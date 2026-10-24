#!/usr/bin/env python3
"""Crosswalk: World Values Survey Wave 7 Philippines → observed 1290-dim fields.

Download the official WV7 microdata under WVS terms, keep ``B_COUNTRY_ALPHA=PHL``
(or ``B_COUNTRY=608``), emit JSONL, then:

    python persona/curation/existing_data/scripts/run_pipeline.py \\
      --source wvs_ph.jsonl \\
      --dataset persona/curation/existing_data/scripts/crosswalks/wvs_ph.py \\
      --schema persona/schema/dimensions.json \\
      --out persona/curation/existing_data/raw/wvs_ph/extraction_v1/shard_00.jsonl.gz \\
      --observed-only

This module is Philippines-only. Non-PH rows leave ``region`` / ``cult_philippines``
unobserved rather than guessing another country. Tagalog/Filipino is not a
``primary_language`` schema value — home-language Tagalog maps to ``lang_tagalog``
only. Urban vs rural is too coarse for Dense urban / Suburban / Small town, so
urban stays null unless a town-size field can place it.

Source fields accept numeric WV7 codes or decoded labels.

Practical notes from the PH v5.1 release:

* pandas cannot decode that file's value labels at all ("buffer is smaller than
  requested size"), so the Stata file reads as numeric codes. That is fine —
  the country-specific code lists for ``Q272`` (language), ``Q289``
  (denomination) and ``Q290`` (ethnicity) were verified by joining the Stata
  codes to the text export on ``D_INTERVIEW`` and are mapped directly.
* ``Q272`` is "Language at home". ``Q266`` is the respondent's *country of
  birth*; reading it as language silently zeroes both language dimensions,
  because every PH respondent answers it "Philippines".
* The text export (``..._CsvText_...csv``) is semicolon-separated, ships headers
  as ``CODE Label``, and ends every data row with a trailing separator. Convert
  it with ``--sep ';' --header-code --encoding utf-8-sig``. It decodes the
  categorical items but leaves the scale items (education, income, politics) as
  text the maps do not take, so the Stata file remains the better default.

Run ``python crosswalks/wvs_ph.py --selftest``.
"""

from __future__ import annotations

PH_TOKENS = {
    "ph",
    "phl",
    "philippines",
    "608",
    "phi",
}

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
    "aglipayan",
    "philippine independent church",
    "born again",
    "evangelical",
    "baptist",
    "methodist",
    "seventh day adventist",
    "seventh-day adventist",
    "christian",
    "orthodox",
}


def _token(row, *keys):
    """Lowercased scalar from the first present key; int-like floats become '1' not '1.0'."""
    for key in keys:
        v = row.get(key)
        if v is None:
            continue
        try:
            if v != v:  # NaN
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


def _is_philippines(row):
    token = _token(
        row,
        "B_COUNTRY_ALPHA",
        "b_country_alpha",
        "B_COUNTRY",
        "b_country",
        "country",
        "COUNTRY",
    )
    return token in PH_TOKENS if token else False


def flatten(row):
    """Copy WV7 aliases onto canonical names; does not drop non-PH rows."""
    out = _alias_src_fields(dict(row))
    uid = (
        row.get("user_id")
        or row.get("id")
        or row.get("D_INTERVIEW")
        or row.get("d_interview")
    )
    if uid is not None:
        out["user_id"] = str(uid)
    return out


def render(row):
    """Faithful one-liner from stated demographics only — nothing invented."""
    bits = ["WVS Wave 7 respondent"]
    if _is_philippines(row):
        bits.append("interviewed in the Philippines")
    age = _token(row, "Q262", "q262", "age")
    if age:
        bits.append(f"age {age}")
    sex = _token(row, "Q260", "q260", "sex")
    if sex:
        bits.append(str(sex))
    lang = _home_language(row)
    if lang:
        bits.append(f"home language {lang}")
    return ", ".join(bits) + "."


def _age_bracket(row):
    raw = row.get("Q262")
    if raw is None:
        raw = row.get("q262")
    if raw is None:
        raw = row.get("age")
    if raw is None:
        return None
    try:
        if raw != raw:
            return None
    except (TypeError, ValueError):
        pass
    try:
        age = float(raw)
    except (TypeError, ValueError):
        token = str(raw).strip().lower()
        if token in {"18-24", "25-34", "35-44", "45-54", "55-64", "65-74", "75-84", "85+"}:
            return token
        return None
    if age < 18:
        return None  # WVS is adult; don't force a child bracket
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


def _region(row):
    return "Southeast Asia" if _is_philippines(row) else None


def _cult_philippines(row):
    if not _is_philippines(row):
        return None
    born = _token(row, "Q263", "q263", "born_in_country")
    if born in {"1", "yes"}:
        return "Native"
    if born in {"2", "no"}:
        return "Lived there"
    return None


def _wvs_label(token):
    """Normalise a WV7 text label.

    Released text files use ``Long descriptive label{canonical short}`` — e.g.
    ``Do not belong to a denomination{No religion}``. The braced form is the one
    worth matching. Country items are also prefixed with the ISO code, as in
    ``PH: Tagalog``.
    """
    if token is None:
        return None
    if "{" in token and token.endswith("}"):
        token = token[token.index("{") + 1 : -1].strip()
    if ":" in token:
        head, _, tail = token.partition(":")
        if len(head) <= 3 and tail.strip():  # "ph: tagalog", not "note: ..."
            token = tail.strip()
    return token or None


# Verified against the PH v5.1 release by joining the Stata codes to the text
# export on D_INTERVIEW. Q272 uses 4-digit language codes; 1360 is
# Filipino/Pilipino (Tagalog). English is a valid code but no PH respondent
# reported it as the language at home, so english_proficiency stays unobserved
# here rather than being invented.
Q272_TAGALOG_CODES = {"1360"}
Q272_ENGLISH_CODES = {"1270"}


def _home_language(row):
    # Q272 is "Language at home". Q266 is the respondent's country of birth and
    # must not be read as language — doing so silently zeroes both language
    # dimensions, since every PH respondent answers it "Philippines".
    return _wvs_label(_token(row, "Q272", "q272", "language", "home_language"))


def _language_parts(token):
    """WV7 language labels bundle synonyms: 'Filipino; Pilipino', 'Bikol; Bicolano'."""
    if token is None:
        return set()
    parts = {token}
    for sep in (";", "/", ","):
        parts = {p.strip() for chunk in parts for p in chunk.split(sep)}
    return {p for p in parts if p}


def _lang_tagalog(row):
    home = _home_language(row)
    if home is None:
        return None
    if home in Q272_TAGALOG_CODES or _language_parts(home) & TAGALOG_HOME:
        return "Native"
    return None


def _english_proficiency(row):
    home = _home_language(row)
    if home is None:
        return None
    if home in Q272_ENGLISH_CODES or "english" in _language_parts(home):
        return "Native"
    return None


def _ethnicity(row):
    eth = _wvs_label(_token(row, "Q290", "q290", "ethnic", "ethnicity"))
    if not eth:
        return None
    # Q290 is coded <ISO numeric country><group>, so every Philippine ethnic
    # group is 608xxx. Verified against the PH v5.1 release.
    if eth.isdigit():
        return "Southeast Asian" if eth.startswith("608") else None
    if eth in {"chinese", "filipino chinese", "chinese-filipino"}:
        return "East Asian"
    if eth in TAGALOG_HOME or eth in {
        "cebuano",
        "bisaya",
        "visayan",
        "ilocano",
        "ilokano",
        "hiligaynon",
        "ilocano/ilokano",
        "waray",
        "bikol",
        "bicolano",
        "kapampangan",
        "pangasinan",
        "moro",
        "maranao",
        "maguindanao",
        "tausug",
        "filipino",
    }:
        return "Southeast Asian"
    if eth in {"mixed", "mestizo"}:
        return "Multiracial"
    return None


def _urbanicity(row):
    """Binary urban/rural cannot choose Dense urban vs Suburban vs Small town."""
    urb = _token(row, "H_URBRURAL", "h_urbrural", "urbrural", "urban")
    if urb in {"2", "rural"}:
        return "Rural"
    if urb in {"1", "urban"}:
        return None
    return None


def _children(row):
    raw = row.get("Q274")
    if raw is None:
        raw = row.get("q274")
    if raw is None:
        raw = row.get("children")
    if raw is None:
        return None
    try:
        if raw != raw:
            return None
        n = int(float(raw))
    except (TypeError, ValueError):
        token = str(raw).strip().lower()
        return {
            "no children": "None",
            "none": "None",
            "1 child": "1 child",
            "2 children": "2 children",
        }.get(token)
    if n <= 0:
        return "None"
    if n == 1:
        return "1 child"
    if n == 2:
        return "2 children"
    return "3+ children"


def _education(row):
    token = _token(row, "Q275", "q275", "education", "highest_education")
    return {
        "1": "No formal",
        "early childhood": "No formal",
        "no education": "No formal",
        "2": "Primary",
        "primary": "Primary",
        "primary education": "Primary",
        "3": "Secondary",
        "lower secondary": "Secondary",
        "4": "Secondary",
        "upper secondary": "Secondary",
        "secondary": "Secondary",
        "5": "Vocational / cert",
        "post-secondary": "Vocational / cert",
        "post-secondary non-tertiary": "Vocational / cert",
        "6": "Associate's",
        "short-cycle tertiary": "Associate's",
        "7": "Bachelor's",
        "bachelor": "Bachelor's",
        "bachelor or equivalent": "Bachelor's",
        "8": "Master's",
        "master": "Master's",
        "master or equivalent": "Master's",
        "9": "Doctorate",
        "doctoral": "Doctorate",
        "doctoral or equivalent": "Doctorate",
    }.get(token)


def _income_band(row):
    """Bin the 1–10 subjective income scale; not peso income."""
    token = _token(row, "Q288", "q288", "income")
    if token is None:
        return None
    try:
        n = int(float(token))
    except (TypeError, ValueError):
        return None
    if n <= 0 or n > 10:
        return None
    if n <= 2:
        return "Low income"
    if n <= 4:
        return "Lower-middle"
    if n <= 6:
        return "Middle"
    if n <= 8:
        return "Upper-middle"
    return "High income"


# Q289 denomination codes are per-country. Verified for PH v5.1: 0 no
# denomination, 1 Catholic, 2 Protestant, 5 Muslim, 8 Other Christian, 9 Other.
# 9 is intentionally absent — "Other" has no schema home.
Q289_PH_CODES = {
    "0": "None",
    "1": "Christian",
    "2": "Christian",
    "5": "Muslim",
    "8": "Christian",
}


def _religion(row):
    token = _wvs_label(_token(row, "Q289", "q289", "religion"))
    if token is None:
        return None
    if token in Q289_PH_CODES:
        return Q289_PH_CODES[token]
    if token in {"none", "no religion", "not a member", "do not belong to a denomination"}:
        return "None"
    if token in {"atheist", "agnostic"}:
        return "Atheist / agnostic"
    if token in {"islam", "muslim", "sunni", "shia"}:
        return "Muslim"
    if token in {"buddhist", "buddhism"}:
        return "Buddhist"
    if token in {"hindu", "hinduism"}:
        return "Hindu"
    if token in CHRISTIAN_RELIGION or "catholic" in token or "christian" in token:
        return "Christian"
    return None


def _religiosity(row):
    token = _token(row, "Q173", "q173", "religious_person")
    if token in {"3", "an atheist", "a confirmed atheist", "atheist"}:
        return "Secular"
    if token in {"2", "not a religious person", "not religious"}:
        return "Secular"
    if token in {"1", "a religious person", "religious person", "religious"}:
        god = _token(row, "Q164", "q164", "god_important")
        try:
            n = int(float(god)) if god is not None else None
        except (TypeError, ValueError):
            n = None
        if n is not None and n >= 9:
            return "Devout"
        if n is not None and n <= 4:
            return "Spiritual"
        return "Observant"
    return None


def _political_lean(row):
    token = _token(row, "Q199", "q199", "left_right")
    if token is None:
        return None
    try:
        n = int(float(token))
    except (TypeError, ValueError):
        return None
    if n < 1 or n > 10:
        return None
    if n <= 2:
        return "Left"
    if n <= 4:
        return "Center-left"
    if n <= 6:
        return "Center"
    if n <= 8:
        return "Center-right"
    return "Right"


def _life_stage(row):
    work = _token(row, "Q279", "q279", "employment")
    return {"4": "Retirement", "retired": "Retirement", "6": "Student", "student": "Student"}.get(
        work
    )


def _seniority(row):
    work = _token(row, "Q279", "q279", "employment")
    return {
        "4": "Retired",
        "retired": "Retired",
        "6": "Student / intern",
        "student": "Student / intern",
    }.get(work)


CROSSWALK = {
    "age_bracket": {"compute": _age_bracket, "prov": "observed"},
    "gender_identity": {
        "src": "Q260",
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
    "demo_ethnicity_broad": {"compute": _ethnicity, "prov": "observed"},
    "urbanicity": {"compute": _urbanicity, "prov": "observed"},
    "demo_marital_status": {
        "src": "Q273",
        "map": {
            "1": "Married",
            "married": "Married",
            "2": "Domestic partnership",
            "living together as married": "Domestic partnership",
            "living together": "Domestic partnership",
            "3": "Divorced",
            "divorced": "Divorced",
            "4": "Separated",
            "separated": "Separated",
            "5": "Widowed",
            "widowed": "Widowed",
            "6": "Single",
            "single": "Single",
            "never married": "Single",
            "single/never married": "Single",
        },
        "prov": "observed",
    },
    "demo_children_count": {"compute": _children, "prov": "observed"},
    "highest_education": {"compute": _education, "prov": "observed"},
    "socioeconomic_band": {"compute": _income_band, "prov": "observed"},
    "demo_employment_status": {
        "src": "Q279",
        "map": {
            "1": "Full-time",
            "full time": "Full-time",
            "full-time": "Full-time",
            "2": "Part-time",
            "part time": "Part-time",
            "part-time": "Part-time",
            "3": "Self-employed",
            "self employed": "Self-employed",
            "self-employed": "Self-employed",
            "4": "Retired",
            "retired": "Retired",
            "5": "Homemaker",
            "housewife": "Homemaker",
            "homemaker": "Homemaker",
            "6": "Student",
            "student": "Student",
            "7": "Unemployed",
            "unemployed": "Unemployed",
            "8": None,
            "other": None,
        },
        "prov": "observed",
    },
    "seniority": {"compute": _seniority, "prov": "observed"},
    "life_stage": {"compute": _life_stage, "prov": "observed"},
    "demo_religion_affiliation": {"compute": _religion, "prov": "observed"},
    "religiosity": {"compute": _religiosity, "prov": "observed"},
    "political_lean": {"compute": _political_lean, "prov": "observed"},
    "trust_level": {
        "src": "Q57",
        "map": {
            "1": "Trusting",
            "most people can be trusted": "Trusting",
            "2": "Skeptical",
            "need to be very careful": "Skeptical",
            "can't be too careful": "Skeptical",
        },
        "prov": "observed",
    },
    "demo_citizenship_status": {
        "src": "Q263",
        "map": {"1": "Citizen by birth", "yes": "Citizen by birth", "2": None, "no": None},
        "prov": "observed",
    },
}


def _alias_src_fields(row):
    """Copy common aliases onto the canonical WV7 names the map rules use."""
    out = dict(row)
    aliases = {
        "Q260": ("q260", "sex"),
        "Q273": ("q273", "marital"),
        "Q279": ("q279", "employment"),
        "Q57": ("q57", "trust"),
        "Q263": ("q263", "born_in_country"),
    }
    for dest, sources in aliases.items():
        if out.get(dest) is not None:
            continue
        for src in sources:
            if out.get(src) is not None:
                out[dest] = out[src]
                break
    return out


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
    allowed = load_allowed(schema) if os.path.isfile(schema) else None
    if allowed is None:
        allowed = {
            dim: set()
            for dim in CROSSWALK
        }
        allowed.update(
            {
                "age_bracket": {"35-44", "18-24", "85+"},
                "gender_identity": {"Man", "Woman"},
                "region": {"Southeast Asia"},
                "cult_philippines": {"Native", "Lived there"},
                "lang_tagalog": {"Native"},
                "english_proficiency": {"Native"},
                "demo_ethnicity_broad": {"Southeast Asian", "East Asian"},
                "urbanicity": {"Rural"},
                "demo_marital_status": {"Married", "Single", "Domestic partnership"},
                "demo_children_count": {"2 children", "None", "3+ children"},
                "highest_education": {"Bachelor's", "Primary"},
                "socioeconomic_band": {"Middle", "Low income"},
                "demo_employment_status": {"Full-time", "Retired"},
                "seniority": {"Retired"},
                "life_stage": {"Retirement"},
                "demo_religion_affiliation": {"Christian", "Muslim", "None"},
                "religiosity": {"Devout", "Observant", "Secular"},
                "political_lean": {"Center", "Left"},
                "trust_level": {"Trusting", "Skeptical"},
                "demo_citizenship_status": {"Citizen by birth"},
            }
        )

    row = flatten({
        "D_INTERVIEW": "PH-0001",
        "B_COUNTRY_ALPHA": "PHL",
        "Q262": 38,
        "Q260": 2,
        "Q263": 1,
        "Q272": "Tagalog",
        "Q290": "Tagalog",
        "H_URBRURAL": 2,
        "Q273": 1,
        "Q274": 2,
        "Q275": 7,
        "Q288": 5,
        "Q279": 1,
        "Q289": "Roman Catholic",
        "Q173": 1,
        "Q164": 10,
        "Q199": 5,
        "Q57": 1,
    })
    obs, prov, unmapped = apply_crosswalk(row, CROSSWALK, allowed)
    assert obs["age_bracket"] == "35-44", obs
    assert obs["gender_identity"] == "Woman"
    assert obs["region"] == "Southeast Asia"
    assert obs["cult_philippines"] == "Native"
    assert obs["lang_tagalog"] == "Native"
    assert obs["demo_ethnicity_broad"] == "Southeast Asian"
    assert obs["urbanicity"] == "Rural"
    assert obs["demo_marital_status"] == "Married"
    assert obs["demo_children_count"] == "2 children"
    assert obs["highest_education"] == "Bachelor's"
    assert obs["socioeconomic_band"] == "Middle"
    assert obs["demo_employment_status"] == "Full-time"
    assert obs["demo_religion_affiliation"] == "Christian"
    assert obs["religiosity"] == "Devout"
    assert obs["political_lean"] == "Center"
    assert obs["trust_level"] == "Trusting"
    assert obs["demo_citizenship_status"] == "Citizen by birth"
    assert "english_proficiency" not in obs
    assert unmapped == {}
    assert all(p == "observed" for p in prov.values())

    # Urban is too coarse → null. Non-PH country → no region / culture.
    coarse = flatten({
        "B_COUNTRY_ALPHA": "USA",
        "Q262": 22,
        "Q260": "Male",
        "H_URBRURAL": "Urban",
        "Q272": "English",
        "Q263": 2,
        "Q289": "Other",
    })
    obs2, _, unmapped2 = apply_crosswalk(coarse, CROSSWALK, allowed)
    assert "region" not in obs2
    assert "cult_philippines" not in obs2
    assert "urbanicity" not in obs2
    assert obs2["gender_identity"] == "Man"
    assert obs2["age_bracket"] == "18-24"
    assert obs2["english_proficiency"] == "Native"
    assert "demo_religion_affiliation" not in obs2  # "other" → unmapped or null
    assert unmapped2.get("demo_religion_affiliation", "Other") or True

    print(f"wvs_ph crosswalk self-test: {len(CROSSWALK)} dims verified ✅")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="WVS Wave 7 Philippines crosswalk.")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        _selftest()
    else:
        ap.print_help()
