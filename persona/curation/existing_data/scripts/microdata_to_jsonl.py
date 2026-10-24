#!/usr/bin/env python3
"""Convert gated microdata (Stata/SPSS/CSV, optionally inside a zip) to JSONL.

One person per row, original column names preserved — the crosswalks alias
column names themselves, so renaming here would only hide drift.

This script does **not** download anything. Obtain files yourself under the
provider's terms (PSA data-use agreement, WVS account) and drop them in
``persona/curation/existing_data/raw/`` (gitignored). Never commit the inputs.

    # PSA CPH 2020 person PUF
    python persona/curation/existing_data/scripts/microdata_to_jsonl.py \
      --src persona/curation/existing_data/raw/psa_ph/<person_file>.dta \
      --out persona/curation/existing_data/raw/psa_ph/psa_ph.jsonl \
      --check psa_ph

    # WVS Wave 7 (pooled file -> Philippines only, trimmed to the used columns)
    python persona/curation/existing_data/scripts/microdata_to_jsonl.py \
      --src persona/curation/existing_data/raw/wvs_ph/WVS_Cross-National_Wave_7_stata_v6_0.dta \
      --out persona/curation/existing_data/raw/wvs_ph/wvs_ph.jsonl \
      --preset wvs --check wvs_ph

``--check`` loads the named crosswalk and reports, on a sample, which alias
resolved from which source column and how often each dimension came out
observed. Run it *before* the full pipeline: a dimension at 0% almost always
means this release names the column something the alias table has not seen,
which is a one-line fix in the crosswalk rather than a silent hole in the data.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import sys
import zipfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent

# WV7 columns the wvs_ph crosswalk reads, plus identifiers/country filter.
# Q272 is "Language at home"; Q266 is country of birth. Both are kept, but they
# are not interchangeable — see _home_language in crosswalks/wvs_ph.py.
#
# W_WEIGHT is the within-country weight and must be kept: WV7 quota-samples sex
# (the PH release is exactly 600 men / 600 women), so an unweighted margin
# reports the sample design rather than the country.
WVS_KEEP = [
    "D_INTERVIEW", "B_COUNTRY_ALPHA", "B_COUNTRY", "W_WEIGHT", "PWGHT",
    "Q262", "Q260", "Q263", "Q266", "Q272", "Q290", "H_URBRURAL",
    "Q273", "Q274", "Q275", "Q288", "Q279", "Q289",
    "Q173", "Q164", "Q199", "Q57",
]

DATA_SUFFIXES = {".dta", ".sav", ".csv", ".tsv", ".txt", ".gz"}


def _log(msg):
    print(msg, file=sys.stderr)


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------

def _resolve_zip_member(path, member):
    """Pick the data file inside a zip; largest data-like member by default."""
    with zipfile.ZipFile(path) as zf:
        entries = [i for i in zf.infolist() if not i.is_dir()]
        if member:
            match = [i for i in entries if i.filename == member or i.filename.endswith("/" + member)]
            if not match:
                names = "\n  ".join(i.filename for i in entries)
                raise SystemExit(f"--member {member!r} not found in {path}. Members:\n  {names}")
            chosen = match[0]
        else:
            data = [i for i in entries if Path(i.filename).suffix.lower() in DATA_SUFFIXES]
            if not data:
                names = "\n  ".join(i.filename for i in entries)
                raise SystemExit(
                    f"No .dta/.sav/.csv member in {path}. Pass --member explicitly. Members:\n  {names}"
                )
            chosen = max(data, key=lambda i: i.file_size)
            if len(data) > 1:
                _log(f"  zip has {len(data)} data members; picked largest: {chosen.filename}")
                _log("  (pass --member to choose a different one — CPH ships household and person files together)")
        _log(f"  extracting {chosen.filename} ({chosen.file_size / 1e6:.1f} MB) into memory")
        return chosen.filename, io.BytesIO(zf.read(chosen))


def _stata_frames(src, chunksize, categoricals=None):
    """Yield Stata chunks, falling back to numeric codes if labels will not decode.

    Real PSA/WVS releases carry value-label blocks pandas cannot parse (the WVS
    Wave 7 PH v5.1 file raises "buffer is smaller than requested size"). The
    failure surfaces while *iterating*, not when the reader is constructed, so
    guarding only construction misses it. The crosswalks accept raw codes just
    as well as decoded labels, so dropping to numeric loses nothing.
    """
    import pandas as pd

    modes = (True, False) if categoricals is None else (categoricals,)
    for mode in modes:
        emitted = False
        try:
            if hasattr(src, "seek"):
                src.seek(0)
            reader = pd.read_stata(src, convert_categoricals=mode, chunksize=chunksize)
            with reader:
                for frame in reader:
                    if not emitted:
                        _log(f"  stata: value labels {'decoded' if mode else 'kept as numeric codes'}")
                    emitted = True
                    yield frame
            return
        except ValueError as exc:
            # Restarting after rows were handed out would duplicate them.
            if mode is False or emitted:
                raise
            _log(f"  value labels unreadable ({exc}); re-reading with numeric codes")


def _iter_frames(src, suffix, chunksize, encoding, categoricals=None, sep=None):
    """Yield DataFrames. Chunked for Stata/CSV so a census-sized file streams."""
    import pandas as pd

    if suffix == ".dta":
        yield from _stata_frames(src, chunksize, categoricals)
    elif suffix == ".sav":
        try:
            import pyreadstat  # noqa: F401
        except ImportError:
            raise SystemExit(
                "Reading .sav needs pyreadstat:  pip install pyreadstat\n"
                "(Or re-export the file as .dta/.csv from the provider.)"
            )
        # pandas.read_spss has no chunksize; SPSS PUFs are survey-sized, so
        # this is acceptable where a census-sized .dta would not be.
        yield pd.read_spss(src, convert_categoricals=True)
    else:
        # .txt PUFs use an unadvertised delimiter; sniffing needs the python engine.
        if sep:
            kwargs = {"sep": sep}
        elif suffix == ".txt":
            kwargs = {"sep": None, "engine": "python"}
        else:
            kwargs = {"sep": "\t" if suffix == ".tsv" else ","}
        try:
            # index_col=False is essential, not cosmetic: a trailing delimiter
            # makes data rows one field wider than the header (the WVS text
            # export does this), and pandas then silently promotes the first
            # column to an index, shifting every value one column left.
            reader = pd.read_csv(
                src, chunksize=chunksize, encoding=encoding, index_col=False, **kwargs
            )
        except UnicodeDecodeError:
            _log(f"  {encoding} decode failed; retrying as latin-1")
            if hasattr(src, "seek"):
                src.seek(0)
            reader = pd.read_csv(
                src, chunksize=chunksize, encoding="latin-1", index_col=False, **kwargs
            )
        if chunksize is None:
            yield reader
        else:
            yield from reader


def read_source(path, member=None, chunksize=200_000, encoding="utf-8", categoricals=None, sep=None):
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"source not found: {path}")
    if path.suffix.lower() == ".zip":
        name, buf = _resolve_zip_member(path, member)
        suffix = Path(name).suffix.lower()
        if suffix == ".sav":
            raise SystemExit(
                "pandas cannot read .sav from memory — unzip first:\n"
                f"  unzip -j {path} '{name}' -d {path.parent}"
            )
        return _iter_frames(buf, suffix, chunksize, encoding, categoricals, sep)
    suffix = path.suffix.lower()
    if suffix == ".gz":
        inner = Path(path.stem).suffix.lower() or ".csv"
        return _iter_frames(gzip.open(path, "rb"), inner, chunksize, encoding, categoricals, sep)
    if suffix not in DATA_SUFFIXES:
        raise SystemExit(f"unsupported extension {suffix!r} (want .dta/.sav/.csv/.tsv/.zip/.gz)")
    return _iter_frames(str(path), suffix, chunksize, encoding, categoricals, sep)


# --------------------------------------------------------------------------
# alias / dimension coverage
# --------------------------------------------------------------------------

def _load_crosswalk(name):
    sys.path.insert(0, str(SCRIPTS_DIR))
    sys.path.insert(0, str(SCRIPTS_DIR / "crosswalks"))
    import importlib

    return importlib.import_module(name)


def _schema_path():
    return SCRIPTS_DIR.parent.parent.parent / "schema" / "dimensions.json"


class CoverageReport:
    """Which aliases resolved, and how often each dimension came out observed."""

    def __init__(self, module_name):
        self.module = _load_crosswalk(module_name)
        self.name = module_name
        from crosswalk_engine import load_allowed  # noqa: E402

        self.allowed = load_allowed(str(_schema_path()))
        self.rows = 0
        self.observed = {}
        self.unmapped = {}
        self.alias_hits = {}
        self.src_cols = set()

    def add(self, records):
        from crosswalk_engine import apply_crosswalk  # noqa: E402

        crosswalk = self.module.CROSSWALK
        for raw in records:
            self.src_cols.update(raw.keys())
            flat = self.module.flatten(raw)
            # A canonical key the crosswalk reads that was absent pre-flatten
            # was supplied by an alias — worth reporting either way.
            for key in flat:
                if flat.get(key) is not None:
                    self.alias_hits[key] = self.alias_hits.get(key, 0) + 1
            obs, _prov, unmapped = apply_crosswalk(flat, crosswalk, self.allowed)
            self.rows += 1
            for dim in obs:
                self.observed[dim] = self.observed.get(dim, 0) + 1
            for dim, val in unmapped.items():
                self.unmapped.setdefault(dim, {})
                token = str(val)[:40]
                self.unmapped[dim][token] = self.unmapped[dim].get(token, 0) + 1

    def render(self):
        if not self.rows:
            return "no rows sampled"
        out = [f"\n=== {self.name} coverage over {self.rows:,} sampled rows ==="]
        crosswalk = self.module.CROSSWALK
        dead = []
        for dim in crosswalk:
            n = self.observed.get(dim, 0)
            pct = 100.0 * n / self.rows
            flag = "  <-- never observed" if n == 0 else ""
            if n == 0:
                dead.append(dim)
            out.append(f"  {dim:<32} {pct:6.1f}%  ({n:,}){flag}")
        # Source columns the crosswalk reads directly, so drift is obvious.
        wanted = {spec["src"] for spec in crosswalk.values() if "src" in spec}
        missing = sorted(c for c in wanted if c not in self.alias_hits)
        if missing:
            out.append(f"\n  source keys never populated: {', '.join(missing)}")
        if self.unmapped:
            out.append("\n  values seen but not in the map (top 5 each):")
            for dim, counts in sorted(self.unmapped.items()):
                top = sorted(counts.items(), key=lambda kv: -kv[1])[:5]
                pairs = ", ".join(f"{v!r}x{c}" for v, c in top)
                out.append(f"    {dim}: {pairs}")
        if dead:
            out.append(
                "\n  ACTION: dimensions at 0% usually mean this release names the column "
                "differently.\n  Check the codebook and add the real name to the alias table in "
                f"crosswalks/{self.name}.py."
            )
        return "\n".join(out)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Convert Stata/SPSS/CSV microdata to one-person-per-row JSONL.",
        epilog="Downloads nothing. Obtain files under the provider's terms first.",
    )
    ap.add_argument("--src", required=True, help="path to .dta/.sav/.csv/.tsv/.zip/.gz")
    ap.add_argument("--out", required=True, help="output .jsonl (or .jsonl.gz)")
    ap.add_argument("--member", help="file inside --src zip (default: largest data member)")
    ap.add_argument("--preset", choices=["psa", "wvs"], help="wvs: keep WV7 columns and filter to PHL")
    ap.add_argument("--keep", help="comma-separated columns to keep (default: all)")
    ap.add_argument("--filter-col", help="keep rows where this column matches --filter-val")
    ap.add_argument("--filter-val", help="comma-separated accepted values, case-insensitive")
    ap.add_argument("--check", help="crosswalk module to report coverage for, e.g. psa_ph / wvs_ph")
    ap.add_argument("--check-sample", type=int, default=20_000, help="rows to sample for --check")
    ap.add_argument("--limit", type=int, help="stop after N output rows (smoke tests)")
    ap.add_argument("--chunksize", type=int, default=200_000, help="rows per read chunk")
    ap.add_argument("--encoding", default="utf-8")
    ap.add_argument("--sep", help="column separator (WVS text exports use ';')")
    ap.add_argument("--header-code", action="store_true",
                    help="use the first token of each header as the column name "
                         "(WVS text exports ship headers like 'Q272 Language at home')")
    ap.add_argument("--numeric-codes", action="store_true",
                    help="skip Stata value-label decoding (crosswalks accept raw codes)")
    ap.add_argument("--columns-only", action="store_true", help="print column names and exit")
    args = ap.parse_args(argv)

    keep = [c.strip() for c in args.keep.split(",")] if args.keep else None
    filter_col, filter_vals = args.filter_col, None
    if args.preset == "wvs":
        keep = keep or WVS_KEEP
        filter_col = filter_col or "B_COUNTRY_ALPHA"
        filter_vals = {"phl", "philippines", "608"}
    if args.filter_val:
        filter_vals = {v.strip().lower() for v in args.filter_val.split(",")}

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _log(f"reading {args.src}")

    frames = read_source(
        args.src, args.member, args.chunksize, args.encoding,
        categoricals=False if args.numeric_codes else None,
        sep=args.sep,
    )
    report = CoverageReport(args.check) if args.check else None

    opener = gzip.open if out_path.suffix == ".gz" else open
    written = dropped = 0
    seen_cols = None
    try:
        with opener(out_path, "wt", encoding="utf-8") as fh:
            for frame in frames:
                if args.header_code:
                    frame = frame.rename(columns=lambda c: str(c).split(" ")[0].strip())
                if seen_cols is None:
                    seen_cols = list(frame.columns)
                    _log(f"  {len(seen_cols)} columns")
                    if args.columns_only:
                        print("\n".join(seen_cols))
                        frames.close()  # else the half-consumed StataReader warns on GC
                        return 0
                if filter_col:
                    if filter_col not in frame.columns:
                        raise SystemExit(
                            f"--filter-col {filter_col!r} not in file. Columns include: "
                            f"{', '.join(map(str, seen_cols[:25]))} ...\n"
                            "For a single-country WVS file no filter is needed — drop --preset wvs "
                            "and pass --keep instead."
                        )
                    before = len(frame)
                    mask = frame[filter_col].astype(str).str.strip().str.lower().isin(filter_vals)
                    frame = frame[mask]
                    dropped += before - len(frame)
                if keep:
                    present = [c for c in keep if c in frame.columns]
                    if not present:
                        raise SystemExit(
                            f"none of --keep found. Columns include: {', '.join(map(str, seen_cols[:25]))} ..."
                        )
                    if written == 0:
                        absent = [c for c in keep if c not in frame.columns]
                        if absent:
                            _log(f"  --keep columns absent from file (skipped): {', '.join(absent)}")
                    frame = frame[present]
                if frame.empty:
                    continue

                # to_json per-chunk keeps NaN -> null and non-ASCII intact.
                payload = frame.to_json(orient="records", lines=True, force_ascii=False)
                for line in payload.splitlines():
                    if args.limit and written >= args.limit:
                        break
                    fh.write(line + "\n")
                    written += 1
                if report and report.rows < args.check_sample:
                    room = args.check_sample - report.rows
                    report.add(json.loads(row) for row in payload.splitlines()[:room])
                if args.limit and written >= args.limit:
                    break
    except Exception:
        # Never leave a truncated JSONL that looks like a complete extraction.
        if out_path.exists() and written == 0:
            out_path.unlink()
        raise

    if written == 0:
        raise SystemExit(
            "0 rows written."
            + (f" {dropped:,} rows dropped by --filter-col {filter_col}." if dropped else "")
            + "\nIf this is a WVS country file it holds only PHL already — drop --preset wvs."
        )

    _log(f"\n✓ wrote {written:,} rows -> {out_path}")
    if dropped:
        _log(f"  filtered out {dropped:,} rows on {filter_col}")
    if report:
        _log(report.render())
    _log("\nNext:")
    _log(f"  python {SCRIPTS_DIR}/run_pipeline.py \\")
    _log(f"    --source {out_path} \\")
    _log(f"    --dataset {SCRIPTS_DIR}/crosswalks/{args.check or '<crosswalk>'}.py \\")
    _log(f"    --schema {_schema_path()} \\")
    _log(f"    --out {out_path.parent}/extraction_v1/shard_00.jsonl.gz --observed-only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
