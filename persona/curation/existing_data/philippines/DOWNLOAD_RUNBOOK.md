# Philippines microdata: download runbook

Everything downstream of the raw files is built and tested. What is left is the
part that requires a logged-in human browser: clicking the download on PSADA and
WVS. This file is the click-path plus the exact commands to run afterwards.

## Why this is not automated

| Route | Result |
|---|---|
| `psada.psa.gov.ph` from CLI | **403** on every path, `/home` included — server-side block, not a login redirect |
| `psa.gov.ph` press releases / PDFs | **403** (WAF blocks non-browser clients on HTML and PDF paths) |
| `openstat.psa.gov.ph` **API** | **200** — this is how `targets_ph.json` got its census figures |
| Browser automation from this session | not available — no Chrome/Computer-Use tool is wired in |

So: do the two downloads in the browser you are already logged into. Do not dump
cookies, do not scrape the portals, do not commit the files.

## Task 1 — PSA (priority)

Logged in at <https://psada.psa.gov.ph/home>. Register: `/auth/register`.
DPAF (researcher): <https://tinyurl.com/DPAFresearch>.

1. **CPH 2020 person PUF — required.** <https://psada.psa.gov.ph/catalog/231> →
   **Get Microdata**. Study `PHL-PSA-CPH-2020-v1.0`. Take the **person** file,
   not household-only, and grab the codebook — you will need it the moment a
   dimension reports 0% (see below).
2. **One LFS round that actually has a zip.** Collection:
   <https://psada.psa.gov.ph/catalog/LFS/about>. Skip months showing `--` in the
   microdata column. Prefer a recent round with a download icon (older known-good
   example: April 2016 = `catalog/67`). Person file. Feeds `demo_employment_status`.
3. **FIES — only if income is needed.** <https://psada.psa.gov.ph/catalog/FIES>.
   Listed PUFs run through ~2012 and still need login; 2018/2021 usually need a
   letter + DPAF and often ship CSPro rather than Stata.
4. **POPCEN 2015 — optional.** <https://psada.psa.gov.ph/catalog/168>. Older
   vintage; do not substitute it for CPH 2020. The IHSN copy is not a workaround
   (Data Access Not Available).

Zip icons on collection pages route to `/auth/register`, not to a public file.
**If a study has no zip after login, stop** — that needs a letter + DPAF
(<https://psa.gov.ph/how-acquire-data-psa>). Do not try to route around the wall.

Drop whatever you get into `persona/curation/existing_data/raw/psa_ph/`
(already gitignored, already created).

## Task 2 — WVS Wave 7 Philippines

<https://www.worldvaluessurvey.org/WVSDocumentationWV7.jsp> — account required,
accept the terms, download by hand.

Either the country file (`WVS_Wave_7_Philippines_Stata_v5.0`, ~1200 × 434) or the
Wave-7 pooled file. Put it in `raw/wvs_ph/`. The converter handles the country
filter for you; for a single-country file just drop `--preset wvs` and pass
`--keep` instead.

## Task 3 — NDHS 2022 (easiest gate, highest value per effort)

<https://dhsprogram.com/data/> — free account, state a research purpose;
approval is normally quick. Mirror:
<https://microdata.worldbank.org/index.php/catalog/5846>.

Take the **household member recode (PR)** file, e.g. `PHPR82FL.DTA`. The
women's (IR) file is women 15-49 only and cannot carry a population margin; the
PR file covers every household member of both sexes at all ages. Put it in
`raw/ndhs_ph/`.

This is the source that fills `highest_education` and gives `socioeconomic_band`
a real anchor (DHS wealth quintile maps 1:1 onto the schema band — both are
within-country relative measures).

Two limits, both enforced in the crosswalk rather than papered over:

- DHS tops education out at "higher" with no degree detail, so it cannot be
  split across Some college / Bachelor's / Master's / Doctorate. Those rows stay
  unobserved, which censors the top of the distribution — **CPH's `HGC` remains
  the better source for an education margin.** `derive_targets_ph.py` prints the
  observed-coverage percentage so this is visible, not silent.
- DHS carries no province or city, so `urbanicity` cannot reach `Suburban` and
  no HUC upgrade is possible; urban outside NCR becomes `Small town`. `psa_ph.py`
  *can* reach Suburban. If you ever pool PSA and NDHS rows into one calibration,
  that difference in observability is real — derive the target from the pooled
  file, not from either source alone.

NDHS is a **sample**. Always pass `--weight-col hv005` (`v005` on IR/MR) when
deriving targets from it, or you describe the sample design instead of the
country.

## Then run this

The converter takes `.dta` / `.sav` / `.csv` / `.zip` / `.gz`, streams in chunks
so a census-sized file does not blow memory, picks the person file out of a zip,
and falls back to numeric codes when Stata value labels will not decode (common
in these releases).

```bash
# PSA — inspect columns first if you want to eyeball them
python persona/curation/existing_data/scripts/microdata_to_jsonl.py \
  --src persona/curation/existing_data/raw/psa_ph/<file>.zip --out /dev/null --columns-only

python persona/curation/existing_data/scripts/microdata_to_jsonl.py \
  --src persona/curation/existing_data/raw/psa_ph/<file>.zip \
  --out persona/curation/existing_data/raw/psa_ph/psa_ph.jsonl \
  --check psa_ph

# WVS — pooled file, filtered to PHL and trimmed to the used columns
python persona/curation/existing_data/scripts/microdata_to_jsonl.py \
  --src persona/curation/existing_data/raw/wvs_ph/<file>.dta \
  --out persona/curation/existing_data/raw/wvs_ph/wvs_ph.jsonl \
  --preset wvs --check wvs_ph
```

`--check` prints a per-dimension observed rate. **Read it before running the
pipeline.** A dimension at 0% almost always means this release names the column
something the alias table has not seen — a one-line fix in
`scripts/crosswalks/psa_ph.py`, versus a silent hole in the extraction if you
skip the check. `--member` picks a specific file out of a zip when the largest
one is not the person file.

Then the extraction, unchanged from the hand-off:

```bash
python persona/curation/existing_data/scripts/run_pipeline.py \
  --source persona/curation/existing_data/raw/psa_ph/psa_ph.jsonl \
  --dataset persona/curation/existing_data/scripts/crosswalks/psa_ph.py \
  --schema persona/schema/dimensions.json \
  --out persona/curation/existing_data/raw/psa_ph/extraction_v1/shard_00.jsonl.gz \
  --observed-only
```

Same shape for WVS with `wvs_ph`.

## Then derive the targets that depend on the PUF

`urbanicity` and `highest_education` in `targets_ph.json` are intentionally
empty — an empty margin is skipped by `calibration.py`, which is the safe state.
Fill them from the census itself:

```bash
python persona/curation/existing_data/scripts/derive_targets_ph.py \
  --source persona/curation/existing_data/raw/psa_ph/psa_ph.jsonl \
  --dataset persona/curation/existing_data/scripts/crosswalks/psa_ph.py \
  --dims urbanicity,highest_education \
  --targets persona/curation/existing_data/philippines/targets_ph.json --write
```

Drop `--write` first to see what it would change. **Pass `--weight-col` for any
sampled source** (LFS, FIES, NDHS) — without it you get a target for the sample
design, not for the Philippines. CPH is a census, so unweighted is correct there.

Why derive rather than hand-write: `rake_weights` divides by the sum of the
codes you supply while counting *every* observed row in the denominator
([calibration.py:37-46](../../../post_process/coreset_1m/calibration.py#L37-L46)).
A target that names three of four urbanicity values silently skews the margin
instead of failing. Deriving from the same crosswalk that produced the rows
makes that impossible.

## Still open after the files land

- **`highest_education` in `targets_ph.json` is empty.** Confirmed unavailable
  from public aggregates: the whole OpenStat tree (199 nodes) was crawled, and
  the only attainment tables are LFS *employed persons* by highest grade
  completed (a biased base — excludes students, unemployed, retirees, homemakers)
  and PhilStat table 10.16, which turns out to publish functional-literacy
  *rates* within attainment bands, not the attainment distribution. So this needs
  either the CPH person PUF (`HGC`) or a hand transcription of the PSA
  educational-attainment release in your browser. Do not calibrate it until then.
- **`.sav` needs `pip install pyreadstat`** (`.dta` and `.csv` do not).

## Never

Commit `.dta` / `.sav` / `.zip` / PUF CSV, or redistribute any of it. `raw/*` is
gitignored — verified with `git check-ignore`. Keep it that way.
