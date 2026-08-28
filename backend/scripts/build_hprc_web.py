"""Turn the screened HPRC callset into the two tables the web layer draws from.

Input is one file: `hprc_multisample.trf.noveltyFiltered.tsv`, the output of
`pyTRF identification | novelty annotate | filter` run over the Sniffles
multisample VCF of 67 HPRC long-read genomes. It is a *per-allele* table — one
row per repeat block found inside one sample's inserted sequence — and the
interface needs a per-locus catalog and a per-segment allele structure.

    cd backend && uv run python scripts/build_hprc_web.py

Writes `data/hprc/loci.parquet` and `data/hprc/segments.parquet`, described by
`data/web/hprc-loci.yaml` and `data/web/hprc-segments.yaml`. The raw TSV stays
registered as-is (`hprc-calls.yaml`) so the agent can still query the screen at
its native grain; nothing here replaces it.

Three decisions in here are judgement calls rather than mechanics, and each is
argued at the code that makes it:

* what counts as one locus (`LOCI_SQL`) — the insertion *site*, not the SV
  record, because Sniffles emits co-located records for alleles of different
  length and those are the same locus;
* how a locus inherits a novelty verdict from its alleles (`_NOVELTY_ROLLUP`) —
  conservatively, least-novel-wins;
* why the segment structure is three blocks at most (`SEGMENTS_SQL`) — because
  that is all the upstream TRF call reports, and inventing more would be fiction.

A fourth thing worth knowing before reading any number out of this: the input
carries exact duplicate rows (221,405 rows, 162,441 distinct), so everything
below reads from a DISTINCT view. See `_dedupe_report`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "data" / "web" / "hprc_multisample.trf.noveltyFiltered.tsv"
OUT = REPO_ROOT / "data" / "hprc"
STRCHIVE = REPO_ROOT / "data" / "web" / "strchive" / "loci.parquet"

#: How far from a STRchive disease locus an insertion may sit and still be
#: called a hit. The same 10 bp window the novelty screen uses against UCSC and
#: TRExplorer, so "near a disease locus" and "near a reference repeat" mean the
#: same thing on one page.
STRCHIVE_WINDOW = 10


# --------------------------------------------------------------------------- #
# Reading the input
# --------------------------------------------------------------------------- #

#: The reference-screen columns are written `NA` where there is no reference
#: repeat to describe — every `novel_locus` call, 10,178 rows for UCSC and 2,086
#: for TRExplorer. One `NA` is enough to make DuckDB type the whole column
#: VARCHAR, so `ucsc_copy_num` arrives as the string "77.2" and every consumer
#: that does arithmetic on it breaks. (The web interface did: `hit.copyNum
#: .toFixed is not a function`.)
#:
#: So the sentinel is turned into a real NULL once, here, and the columns get the
#: types their documentation claims. NULL is also the more honest value: "no
#: reference repeat exists at this position" is absence, not a distance of zero.
_INTEGER = (
    "ucsc_start", "ucsc_end", "ucsc_distance", "ucsc_motif_edits",
    "ucsc_period", "ucsc_consensus_size",
    "trexplorer_start", "trexplorer_end", "trexplorer_distance",
    "trexplorer_motif_edits",
)
_DOUBLE = ("ucsc_copy_num", "ucsc_per_match", "ucsc_per_indel")
#: Text columns carrying the same sentinel. A motif literally called "NA" would
#: be drawn as a two-base repeat.
_TEXT = (
    "ucsc_motif", "ucsc_canonical", "ucsc_match",
    "trexplorer_motif", "trexplorer_canonical", "trexplorer_match",
)


def _clean_columns() -> str:
    """The `REPLACE` list that retypes the reference block. See `_INTEGER`."""
    casts = [f"TRY_CAST({c} AS BIGINT) AS {c}" for c in _INTEGER]
    casts += [f"TRY_CAST({c} AS DOUBLE) AS {c}" for c in _DOUBLE]
    casts += [f"nullif({c}, 'NA') AS {c}" for c in _TEXT]
    return ", ".join(casts)


# --------------------------------------------------------------------------- #
# The locus verdict
# --------------------------------------------------------------------------- #

#: A locus can hold several alleles, and they need not agree about novelty: a
#: common allele may sit on a catalogued repeat while a rarer one at the same
#: site carries a motif no catalog has. Rolling those up least-novel-first — the
#: locus is `known` if ANY allele is known — is the conservative direction, and
#: it is the rule `novelty` already follows across catalogs ("a locus is only
#: novel when no catalog knows it"). Extending the same rule across alleles
#: keeps one word meaning one thing on the page.
#:
#: The cost is real and is why `n_novel_alleles` is carried alongside: a locus
#: whose dominant allele is catalogued but which also holds a novel-motif allele
#: reads as `known` here, and that column is how you find it again.
_NOVELTY_ROLLUP = """
    CASE WHEN bool_or({col} = 'known')       THEN 'known'
         WHEN bool_or({col} = 'novel_motif') THEN 'novel_motif'
         WHEN bool_or({col} = 'novel_locus') THEN 'novel_locus'
         ELSE 'unscreened' END
"""


def _rollup(column: str) -> str:
    return _NOVELTY_ROLLUP.format(col=column)


# --------------------------------------------------------------------------- #
# Loci
# --------------------------------------------------------------------------- #

#: One row per insertion site.
#:
#: **What a locus is.** The key is (chrom, ins_coord), not SVID. 21,424 SV
#: records collapse to 17,270 sites, and the records that share a site are
#: alleles of different length at the same insertion point — which is precisely
#: what a locus is. Keying on SVID instead would be tidier (one motif, one
#: length, no diploid samples) and would also make every per-locus allele
#: histogram a single bar, because `insert_size` is constant within an SV record:
#: the multisample VCF carries one ALT sequence per record, so all 67 carriers of
#: a record share its length. All the cohort-level allele variation this callset
#: has lives *between* co-located records. Grouping by site is what exposes it.
#:
#: **The representative allele.** `motif`, `motif_len` and the whole reference
#: block are single-valued on a locus row but multi-valued in the data, so they
#: are read off the allele with the most carriers (ties broken by the longer
#: insertion, then the SVID, so the pick is deterministic). Reported as
#: `n_alleles` and `n_motifs` so a row never implies it is the whole story.
LOCI_SQL = f"""
WITH alleles AS (
    -- One row per (site, SV record, sample): a carrier's allele. The DISTINCT
    -- in `calls` has already removed the duplicated rows.
    SELECT chrom, ins_coord, SVID, sample,
           insert_size, canonical_motif, motif_length, purity, insertion_purity,
           repeat_coverage, rep_units, depth,
           novelty, ucsc_novelty, trexplorer_novelty,
           ucsc_start, ucsc_end, ucsc_distance, ucsc_motif, ucsc_canonical,
           ucsc_motif_edits, ucsc_n_nearby, ucsc_period, ucsc_copy_num,
           ucsc_consensus_size, ucsc_per_match, ucsc_per_indel,
           trexplorer_start, trexplorer_end, trexplorer_distance,
           trexplorer_motif, trexplorer_canonical, trexplorer_motif_edits,
           trexplorer_n_nearby
    FROM calls
),
record_support AS (
    -- Carriers per SV record, which is what "dominant allele" is ranked on.
    SELECT chrom, ins_coord, SVID, count(DISTINCT sample) AS n_carriers
    FROM alleles GROUP BY 1, 2, 3
),
representative AS (
    SELECT chrom, ins_coord, SVID FROM (
        SELECT r.chrom, r.ins_coord, r.SVID,
               row_number() OVER (
                   PARTITION BY r.chrom, r.ins_coord
                   ORDER BY r.n_carriers DESC, a.insert_size DESC, r.SVID
               ) AS rn
        FROM record_support r
        JOIN (SELECT DISTINCT chrom, ins_coord, SVID, insert_size FROM alleles) a
          ON a.chrom = r.chrom AND a.ins_coord = r.ins_coord AND a.SVID = r.SVID
    ) WHERE rn = 1
),
rep_row AS (
    -- The representative record's own screen result. DISTINCT because every
    -- carrier of a record repeats it identically.
    SELECT DISTINCT a.* EXCLUDE (sample, purity, insertion_purity,
                                 repeat_coverage, rep_units, depth)
    FROM alleles a JOIN representative p USING (chrom, ins_coord, SVID)
),
agg AS (
    SELECT chrom, ins_coord,
           count(DISTINCT sample)      AS n_samples,
           count(*)                    AS n_carrier_alleles,
           count(DISTINCT SVID)        AS n_alleles,
           count(DISTINCT canonical_motif) AS n_motifs,
           median(insert_size)         AS median_len,
           min(insert_size)            AS min_len,
           max(insert_size)            AS max_len,
           -- Rounded, and it is load-bearing. The input is floored at exactly
           -- 0.80 and 107 loci average to within a ulp of it, 10 of them landing
           -- at 0.7999999999999998 - so an unrounded `avg` puts them on either
           -- side of the interface's own `mean_purity >= 0.80` stage depending
           -- on what order DuckDB happened to sum them in, and the funnel count
           -- moves by a couple of loci between two builds of the same file. Six
           -- decimals is three more than the input carries.
           round(avg(purity), 6)             AS mean_purity,
           round(avg(insertion_purity), 6)   AS mean_insertion_purity,
           round(avg(repeat_coverage), 6)    AS mean_repeat_coverage,
           median(rep_units)           AS median_units,
           median(depth)               AS median_depth,
           {_rollup('novelty')}             AS novelty,
           {_rollup('ucsc_novelty')}        AS ucsc_novelty,
           {_rollup('trexplorer_novelty')}  AS trexplorer_novelty,
           count(DISTINCT SVID) FILTER (WHERE novelty <> 'known') AS n_novel_alleles
    FROM alleles GROUP BY 1, 2
)
SELECT
    a.chrom || ':' || a.ins_coord           AS locus_id,
    a.chrom,
    a.ins_coord                             AS pos,
    r.canonical_motif                       AS motif,
    CAST(r.motif_length AS INTEGER)         AS motif_len,
    CASE WHEN r.motif_length = 1 THEN 'homopolymer'
         WHEN r.motif_length <= 6 THEN 'STR'
         ELSE 'VNTR' END                    AS motif_class,
    a.n_samples, a.n_carrier_alleles, a.n_alleles, a.n_motifs, a.n_novel_alleles,
    a.median_len, a.min_len, a.max_len,
    a.mean_purity, a.median_units, a.median_depth,
    a.mean_insertion_purity                 AS insertion_purity,
    a.mean_repeat_coverage                  AS repeat_coverage,
    a.novelty,
    a.novelty <> 'known'                    AS novel,
    -- `catalogs` mirrors the demo column: which catalogs contain this repeat,
    -- empty when none do. Derived from the per-catalog verdicts rather than
    -- stored upstream, so it cannot drift from them.
    nullif(concat_ws(';',
        CASE WHEN a.ucsc_novelty = 'known' THEN 'UCSC simpleRepeat' END,
        CASE WHEN a.trexplorer_novelty = 'known' THEN 'TRExplorer' END), '')
                                            AS catalogs,
    a.ucsc_novelty, a.trexplorer_novelty,
    r.ucsc_n_nearby, r.ucsc_start, r.ucsc_end, r.ucsc_distance,
    r.ucsc_motif, r.ucsc_canonical, r.ucsc_motif_edits, r.ucsc_period,
    r.ucsc_copy_num, r.ucsc_consensus_size, r.ucsc_per_match, r.ucsc_per_indel,
    r.trexplorer_n_nearby, r.trexplorer_start, r.trexplorer_end,
    r.trexplorer_distance, r.trexplorer_motif, r.trexplorer_canonical,
    r.trexplorer_motif_edits,
    r.SVID                                  AS representative_svid
FROM agg a JOIN rep_row r USING (chrom, ins_coord)
"""


# --------------------------------------------------------------------------- #
# Segments
# --------------------------------------------------------------------------- #

#: One row per structural segment inside one carrier's inserted allele.
#:
#: **Why at most three segments.** The upstream table reports exactly one repeat
#: block per (record, sample) — verified, not assumed: after de-duplication every
#: one of the 162,441 (SVID, sample) pairs has a single row. So an allele is
#: `[flank] repeat [flank]`, with the flanks present only when the block does not
#: start at 0 or end at `insert_size` (40% of alleles have one or both). Emitting
#: a richer structure would mean inventing blocks TRF never called.
#:
#: **The allele key.** 4,110 (site, sample) pairs carry two or three co-located
#: SV records — a diploid sample whose haplotypes differ in length, which is a
#: real finding and not a merge artifact. They are kept as separate alleles and
#: numbered `allele` 1..n by decreasing length, so the barcode draws two strips
#: for such a carrier instead of stacking two haplotypes into one allele and
#: drawing it as though it were a compound repeat.
SEGMENTS_SQL = """
WITH allele AS (
    SELECT DISTINCT chrom || ':' || ins_coord AS locus_id, sample, SVID,
           insert_size, rep_start, rep_end, canonical_motif, purity, rep_units
    FROM calls
),
numbered AS (
    SELECT *, row_number() OVER (
               PARTITION BY locus_id, sample ORDER BY insert_size DESC, SVID
           ) AS allele
    FROM allele
),
parts AS (
    SELECT locus_id, sample, allele, 0 AS ord, 'flank' AS seg_type,
           0 AS start, rep_start AS "end", NULL AS motif, NULL AS purity, NULL AS units
    FROM numbered WHERE rep_start > 0
    UNION ALL
    SELECT locus_id, sample, allele, 1, 'repeat',
           rep_start, rep_end, canonical_motif, purity, rep_units
    FROM numbered
    UNION ALL
    SELECT locus_id, sample, allele, 2, 'flank',
           rep_end, insert_size, NULL, NULL, NULL
    FROM numbered WHERE rep_end < insert_size
)
SELECT locus_id, sample, allele,
       CAST(row_number() OVER (
           PARTITION BY locus_id, sample, allele ORDER BY ord
       ) - 1 AS INTEGER)             AS seg_index,
       seg_type,
       CAST(start AS INTEGER)        AS start,
       CAST("end" AS INTEGER)        AS "end",
       motif, purity, units
FROM parts
"""


# --------------------------------------------------------------------------- #
# Disease-gene annotation
# --------------------------------------------------------------------------- #

#: `gene` and `disease_gene` exist because the catalog surface reads them — the
#: funnel's last stage and two filters. This callset carries no gene annotation,
#: so rather than leave them empty (a funnel stage reading 0 looks like a
#: negative result, not a missing one) they are filled from the one gene source
#: the repository actually has: STRchive's 82 curated disease loci.
#:
#: That makes `gene` NON-NULL ONLY at a disease locus. It is not a general gene
#: annotation and the manifest says so in as many words — an insertion in the
#: middle of some ordinary gene has `gene = NULL` here, which means "not a
#: STRchive locus", not "intergenic". `disease_gene` is then exactly `gene IS
#: NOT NULL`, and is the honest version of the column: every locus it marks
#: really is a known repeat-expansion locus.
STRCHIVE_SQL = f"""
WITH hit AS (
    SELECT l.locus_id, s.gene, s.id AS strchive_id, s.disease AS strchive_disease,
           s.inheritance AS strchive_inheritance, s.evidence AS strchive_evidence,
           s.novel_in_reference AS strchive_novel_in_ref,
           greatest(0, greatest(s.start_hg38 - l.pos, l.pos - s.stop_hg38)) AS distance_bp,
           row_number() OVER (
               PARTITION BY l.locus_id
               ORDER BY greatest(0, greatest(s.start_hg38 - l.pos, l.pos - s.stop_hg38))
           ) AS rn
    FROM loci l JOIN strchive s
      ON s.chrom = l.chrom
     AND l.pos BETWEEN s.start_hg38 - {STRCHIVE_WINDOW} AND s.stop_hg38 + {STRCHIVE_WINDOW}
)
SELECT l.*,
       h.gene,
       h.gene IS NOT NULL AS disease_gene,
       h.strchive_id, h.strchive_disease, h.strchive_inheritance,
       h.strchive_evidence, h.strchive_novel_in_ref,
       h.distance_bp AS strchive_distance_bp
FROM loci l LEFT JOIN (SELECT * FROM hit WHERE rn = 1) h USING (locus_id)
"""


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

def _dedupe_report(con: duckdb.DuckDBPyConnection) -> None:
    """Say out loud how many duplicate rows the input carried.

    The screen emits a row per (record, sample) twice for some records. Silently
    dropping them would be the right thing done invisibly — and the counts in
    this file are the ones people quote, so the difference between 221,405 and
    162,441 needs to be on the terminal, not just in the parquet.
    """
    raw, distinct = con.execute(
        "SELECT (SELECT count(*) FROM raw), (SELECT count(*) FROM calls)"
    ).fetchone()
    if raw != distinct:
        pct = 100.0 * (raw - distinct) / raw
        print(f"[hprc] input has {raw:,} rows, {distinct:,} distinct "
              f"— dropped {raw - distinct:,} exact duplicates ({pct:.1f}%)")


def main() -> int:
    if not SOURCE.exists():
        print(f"[hprc] missing input: {SOURCE}", file=sys.stderr)
        print("[hprc] fetch it with:\n"
              "  dx download file-JB8Xg900pzXPjXvpYXg29fYB -o "
              f"{SOURCE.relative_to(REPO_ROOT)}", file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()

    con.execute(
        "CREATE VIEW raw AS SELECT * FROM "
        f"read_csv('{SOURCE}', delim='\t', header=true, sample_size=-1)"
    )
    con.execute(
        f"CREATE VIEW calls AS SELECT DISTINCT * REPLACE ({_clean_columns()}) FROM raw"
    )
    _dedupe_report(con)

    con.execute(f"CREATE TABLE loci AS {LOCI_SQL}")

    if STRCHIVE.exists():
        con.execute(f"CREATE VIEW strchive AS SELECT * FROM read_parquet('{STRCHIVE}')")
        con.execute(f"CREATE TABLE loci_annotated AS {STRCHIVE_SQL}")
        con.execute("DROP TABLE loci")
        con.execute("ALTER TABLE loci_annotated RENAME TO loci")
        hits = con.execute("SELECT count(*) FROM loci WHERE disease_gene").fetchone()[0]
        print(f"[hprc] {hits} loci within {STRCHIVE_WINDOW} bp of a STRchive disease locus")
    else:
        # Without the catalog the columns still have to exist, or /api/summary
        # and two filters query a column that is not there.
        con.execute("ALTER TABLE loci ADD COLUMN gene VARCHAR")
        con.execute("ALTER TABLE loci ADD COLUMN disease_gene BOOLEAN DEFAULT false")
        print("[hprc] no STRchive catalog — gene/disease_gene left empty. "
              "Run scripts/fetch_strchive.py first to fill them.",
              file=sys.stderr)

    con.execute(f"CREATE TABLE segments AS {SEGMENTS_SQL}")

    for name in ("loci", "segments"):
        path = OUT / f"{name}.parquet"
        con.execute(f"COPY {name} TO '{path}' (FORMAT parquet)")
        n = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        print(f"[hprc] {n:,} rows -> {path.relative_to(REPO_ROOT)}")

    novel, total = con.execute(
        "SELECT count(*) FILTER (WHERE novel), count(*) FROM loci"
    ).fetchone()
    print(f"[hprc] {novel:,} of {total:,} loci novel ({100.0 * novel / total:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
