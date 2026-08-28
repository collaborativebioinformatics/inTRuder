"""Cache the `data/plots` TSVs as Parquet, once, so everything downstream is fast.

    cd backend && uv run python scripts/plots_to_parquet.py          # all of them
    cd backend && uv run python scripts/plots_to_parquet.py 05_      # just the 05 pair

Reads `data/plots/*.tsv` (fetched by `scripts/fetch_plot_data.sh`) and writes
`data/plots/parquet/<stem>.parquet`. Both directories are gitignored: this is
derived output, and the Parquet is a cache of a file that is itself a download.

**Why this exists.** `05_hprc_multisample.tsv` is 561 MB of text with 163
columns. DuckDB re-parses all of it for every query, so a single
`count(*) FILTER (...)` over one column costs about 40 seconds; the same query
over the Parquet costs under a second, because Parquet is columnar and the scan
touches only the columns named. `build_web_tables.py` reads a dozen columns and
does four passes, and the exploratory queries that decide what the web layer
should even show are read-many by nature. Converting once is the difference
between "run a query" and "go and do something else".

**The one thing this changes about the data**, and it is deliberate: the
sentinels `NA`, `.` and the empty string become real NULLs (`_NULLSTR`). See the
note there for why that is a fix rather than a liberty.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = REPO_ROOT / "data" / "plots"
OUT_DIR = SOURCE_DIR / "parquet"

#: Written where a value is absent. AnnotSV writes `NA`, the TRF/novelty screen
#: writes `NA`, and VCF-derived columns write `.`.
#:
#: Turning these into NULL at conversion time is what makes type inference work
#: at all. One `NA` anywhere in a column is enough to make DuckDB type the whole
#: column VARCHAR, so `ucsc_copy_num` arrives as the string "77.2" and
#: `Overlapped_CDS_percent_merged` as the string "0" — and every consumer that
#: does arithmetic on them breaks. (The web interface did, with
#: `hit.copyNum.toFixed is not a function`.) NULL is also the more honest value:
#: "AnnotSV found no transcript here" is absence, not zero.
#:
#: Verified safe against this data before being applied blanket: no sequence,
#: sample, motif or verdict column carries a bare `NA` or `.` as a legitimate
#: whole-field value. The 24 `NA19835`-style sample names do not match — DuckDB
#: compares the whole field, not a prefix.
_NULLSTR = ["NA", ".", ""]


def _convert(source: Path, out: Path, con: duckdb.DuckDBPyConnection) -> None:
    """One TSV to one Parquet, with a line saying what it cost."""
    started = time.monotonic()
    con.execute(
        f"COPY (SELECT * FROM read_csv('{source}', delim='\t', header=true, "
        # sample_size=-1: type inference reads the whole file rather than the
        # first 20,480 rows. These tables put their `NA`s a long way down —
        # AnnotSV's unannotated rows are 5 loci on an unplaced scaffold — and a
        # sampled sniff types a column INTEGER and then fails the real scan.
        f"sample_size=-1, nullstr={_NULLSTR!r})) "
        f"TO '{out}' (FORMAT parquet, COMPRESSION zstd)"
    )
    rows = con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
    before = source.stat().st_size / 1e6
    after = out.stat().st_size / 1e6
    print(
        f"[plots] {source.name}\n"
        f"        {rows:,} rows · {before:,.0f} MB TSV -> {after:,.0f} MB parquet "
        f"({before / after:.0f}x smaller, {time.monotonic() - started:.0f}s)"
    )


def main(argv: list[str]) -> int:
    prefix = argv[1] if len(argv) > 1 else ""

    if not SOURCE_DIR.is_dir():
        print(f"[plots] no {SOURCE_DIR.relative_to(REPO_ROOT)} — fetch it with:\n"
              "  just plot-data", file=sys.stderr)
        return 1

    sources = sorted(p for p in SOURCE_DIR.glob("*.tsv") if p.name.startswith(prefix))
    if not sources:
        where = f" matching {prefix!r}" if prefix else ""
        print(f"[plots] no TSVs{where} in {SOURCE_DIR.relative_to(REPO_ROOT)} — "
              "fetch them with `just plot-data`", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()

    for source in sources:
        out = OUT_DIR / f"{source.stem}.parquet"
        # Skip work already done, but not work the source has outrun. A re-fetched
        # TSV must not keep serving the Parquet built from the previous one.
        if out.exists() and out.stat().st_mtime >= source.stat().st_mtime:
            print(f"[plots] {source.name} — current, skipping")
            continue
        _convert(source, out, con)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
