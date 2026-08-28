"""Turn a screened, gene-annotated callset into the two tables the web layer draws from.

    cd backend && uv run python scripts/build_web_tables.py           # both cohorts
    cd backend && uv run python scripts/build_web_tables.py hprc      # just one

Input is one file per cohort, `data/plots/parquet/05_*.parquet` (see `COHORTS`),
written by `scripts/plots_to_parquet.py` from the TSVs `scripts/fetch_plot_data.sh`
downloads. It is the output of `pyTRF identification | novelty annotate | filter`
run over a Sniffles multisample VCF, then passed through **AnnotSV** — so every
row carries both the reference screen and the gene context.

It is a *per-allele* table — one row per repeat block found inside one sample's
inserted sequence — and the interface needs a per-locus catalog and a per-segment
allele structure. Writes `data/<cohort>/loci.parquet` and `segments.parquet`,
described by the manifests in `data/web`.

Five decisions in here are judgement calls rather than mechanics, and each is
argued at the code that makes it:

* what counts as one locus (`LOCI_SQL`) — the insertion *site*, not the SV
  record, because Sniffles emits co-located records for alleles of different
  length and those are the same locus;
* how a locus inherits a novelty verdict from its alleles (`_NOVELTY_ROLLUP`) —
  conservatively, least-novel-wins;
* why the segment structure is three blocks at most (`SEGMENTS_SQL`) — because
  that is all the upstream TRF call reports, and inventing more would be fiction;
* which gene a multi-gene locus reports (`_first`) — the first, with a count
  beside it, never a silent merge;
* why `intronic` is derived rather than read (`GENE_SQL`) — AnnotSV's own
  `Intronic` column is `NOT Exonic`, so it is TRUE at every intergenic locus.

A sixth thing worth knowing before reading any number out of this: the input
carries exact duplicate rows (221,405 rows, 162,441 distinct for HPRC), so
everything below reads from a DISTINCT view. See `_dedupe_report`.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[2]
PLOTS = REPO_ROOT / "data" / "plots" / "parquet"
STRCHIVE = REPO_ROOT / "data" / "web" / "strchive" / "loci.parquet"

#: How far from a STRchive disease locus an insertion may sit and still be
#: called a hit. The same 10 bp window the novelty screen uses against UCSC and
#: TRExplorer, so "near a disease locus" and "near a reference repeat" mean the
#: same thing on one page.
STRCHIVE_WINDOW = 10


@dataclass(frozen=True)
class Cohort:
    name: str
    source: str
    out: str
    label: str


#: The two callsets that have been through the same screen and the same AnnotSV
#: run, so one build path serves both. They are NOT two views of one cohort: HPRC
#: is 67 unrelated genomes and the trio is one family, which is why they get
#: separate tables and separate manifests rather than a `cohort` column.
COHORTS = {
    "hprc": Cohort("hprc", "05_hprc_multisample.parquet", "hprc", "67 HPRC genomes"),
    "trio": Cohort(
        "trio", "05_HG002_03_04_multisample.parquet", "trio", "GIAB HG002/03/04 trio"
    ),
}


# --------------------------------------------------------------------------- #
# Reading the multi-valued AnnotSV columns
# --------------------------------------------------------------------------- #

#: AnnotSV packs several values into one field with three different shapes, and
#: confusing them silently corrupts every gene label on the page. Each of the
#: three helpers below exists because one of those shapes needs it.
#:
#: * **`Gene_name`** is `;`-joined with exactly `Gene_count` entries, in gene
#:   order: `WDFY4;LRRC18`. → `_gene_name`.
#:
#: * **Transcript-level `*_merged`** (`Tx`, `Exon_count`, `Location`,
#:   `Location2`, `Dist_nearest_SS`, `Nearest_SS_type`) is `, `-joined with one
#:   entry per gene *per overlapping transcript occurrence*, so it is longer than
#:   the gene list and carries duplicates: `NR_188197, NR_188197` for one gene.
#:   Verified against both cohorts: no single-gene locus has more than one
#:   *distinct* entry here, so de-duplicating recovers the per-gene value
#:   exactly. Every value in this family is structured and cannot contain `, `.
#:   → `_tx`.
#:
#: * **Gene-level `*_merged`** (`OMIM_*`, `GenCC_*`, `NCBI_gene_ID`, `HGNC_*`,
#:   `LOEUF_bin`) is `, `-joined with exactly `Gene_count` entries and is NOT
#:   duplicated per transcript. Splitting it is safe only when the values cannot
#:   themselves contain `, ` — true for the IDs, false for the free text:
#:   `LRPAP1` alone carries `Myopia 23, AR, 615431 (3) AR`, and 26,962 HPRC rows
#:   have a comma inside a single gene's phenotype. Splitting that yields `AR`.
#:   → `_gene_id` for the former, `_gene_text` for the latter.
_GENE_SEP = ";"
_MERGED_SEP = ", "

#: AnnotSV writes the separators but no values when *no* gene in the list has
#: one, so a two-gene locus with no OMIM phenotype gets the literal string `,`.
#: `plots_to_parquet.py` cannot catch this — it nulls whole fields, and this
#: field is not empty, it is punctuation. Anything that is only commas and
#: spaces means "none of these genes has a value", which is NULL.
def _blank(expr: str) -> str:
    return f"nullif(regexp_replace({expr}, '^[\\s,]*$', ''), '')"


def annotsv_collapse(value: str | None) -> str | None:
    """Reduce a `, `-joined list that is an exact repetition to a single period.

    AnnotSV repeats a gene-level value once per overlapping transcript, so a gene
    with three transcripts gets its disease name three times. This finds the
    shortest period the chunk list is built from and returns just that.

    It is deliberately conservative: a period must divide the list exactly and
    match at every position, so a value whose commas are its own text — `Myopia
    23, AR, 615431 (3) AR` — has no period below its own length and is returned
    unchanged. That is the case that makes splitting on `, ` unsafe in the first
    place, and it must survive this untouched.

    Written in Python rather than SQL because detecting a repeat needs a
    backreference (`^(.+?)(, \\1)+$`) and DuckDB's RE2 engine has none.
    """
    if value is None:
        return None
    parts = value.split(_MERGED_SEP)
    n = len(parts)
    for period in range(1, n // 2 + 1):
        if n % period == 0 and all(parts[i] == parts[i % period] for i in range(n)):
            return _MERGED_SEP.join(parts[:period])
    return value


def _tx(column: str) -> str:
    """The per-gene value of a transcript-level `*_merged` column."""
    return _blank(f"list_distinct(str_split({column}, '{_MERGED_SEP}'))[1]")


def _gene_id(column: str) -> str:
    """The first gene's value of a gene-level column whose values hold no comma."""
    return _blank(f"str_split({column}, '{_MERGED_SEP}')[1]")


def _gene_text(column: str) -> str:
    """A gene-level free-text column: the whole aggregate expression, guarded.

    Free text is the one family that cannot be split on `, ` and cannot be
    attributed by position either, so it gets both of the defences below. Unlike
    the other helpers this emits its own `any_value`, because the guard has to
    wrap the aggregate rather than sit inside it.

    **Repetition.** The value is repeated once per overlapping transcript, so
    1,996 single-gene HPRC loci read `Spermatogenic failure 92, 620848 (3) AR,
    Spermatogenic failure 92, 620848 (3) AR`. `annotsv_collapse` reduces a list
    that is an exact repetition to one period; a value whose commas are its own
    (`Myopia 23, AR, 615431 (3) AR`) has no period and passes through untouched.

    **Mis-attribution.** On a multi-gene locus the entries belong to different
    genes and the free ones cannot be told apart — 53 HPRC loci begin with `, `,
    which is AnnotSV saying the FIRST gene has no value while a later one does.
    Rendering that beside `gene` would caption one gene with another's disease.
    So multi-gene loci get NULL here and the page falls back to `all_genes`.
    `disease_gene` and `pli` are unaffected: AnnotSV computes those across all
    the genes at the site, so they stay true regardless of how many there are.
    """
    return f"CASE WHEN any_value(Gene_count) = 1 THEN annotsv_collapse(any_value({_blank(column)})) END"


def _gene_name(column: str) -> str:
    """The first entry of a `;`-joined gene-order column."""
    return _blank(f"str_split({column}, '{_GENE_SEP}')[1]")


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
# Gene context
# --------------------------------------------------------------------------- #

#: The AnnotSV block, rolled up to the locus.
#:
#: **Why `any_value` is safe.** Gene annotation is a property of the insertion
#: SITE, so it cannot vary between the alleles at one site — verified on both
#: cohorts by `_invariance_report`, which fails the build if it ever does.
#:
#: **Why `intronic` is derived.** AnnotSV ships `Genic`, `Exonic` and `Intronic`,
#: and `Intronic` is unusable: it is computed as `NOT Exonic`, so it is TRUE for
#: all 79,844 intergenic rows in the HPRC callset. Recomputing it as "in a gene
#: but not in an exon" is the only reading that makes the three flags partition
#: anything. `Exonic` itself is sound — it agrees with `Location_merged` exactly.
#:
#: **What `region` does and does not say.** `Location2_merged` is which
#: transcript region the SV sits *within*, not what it hits: 45,594 HPRC rows are
#: `intron4-intron4` with region `CDS`, meaning an intron between the start and
#: stop codons. It is labelled "within the CDS span" on the page for that reason,
#: and `exonic` is the column that answers "does this land in coding sequence".
GENE_SQL = f"""
    any_value({_gene_name('Gene_name')})             AS gene,
    any_value(Gene_name)                             AS all_genes,
    any_value(Gene_count)                            AS gene_count,
    any_value(coalesce(Gene_count, 0) > 0)           AS genic,
    any_value(coalesce(Exonic, false))               AS exonic,
    any_value(coalesce(Gene_count, 0) > 0
              AND NOT coalesce(Exonic, false))       AS intronic,
    any_value({_tx('Location_merged')})              AS location,
    any_value({_tx('Location2_merged')})             AS region,
    -- "intron12-intron12" -> ('intron', 12). Both halves are the breakpoints,
    -- and for an insertion they are the same feature; `_location_report` says so
    -- out loud rather than letting the left one quietly stand for both.
    any_value(regexp_extract({_tx('Location_merged')},
                             '^([a-z]+)', 1))        AS feature,
    any_value(TRY_CAST(regexp_extract({_tx('Location_merged')},
                       '^[a-z]+([0-9]+)', 1) AS INTEGER))  AS feature_index,
    any_value(TRY_CAST({_tx('Exon_count_merged')} AS INTEGER))     AS exon_count,
    any_value({_tx('Tx_merged')})                    AS tx,
    any_value(TRY_CAST({_tx('Tx_version_merged')} AS INTEGER))     AS tx_version,
    any_value(TRY_CAST({_tx('Dist_nearest_SS_merged')} AS INTEGER))
                                                     AS dist_nearest_ss,
    any_value({_tx('Nearest_SS_type_merged')})       AS nearest_ss_type,
    -- AnnotSV writes the band without its chromosome; the page wants "7q36.3".
    any_value(replace(chrom, 'chr', '') || CytoBand) AS cytoband,
    any_value(Closest_left)                          AS closest_left,
    any_value(Closest_right)                         AS closest_right,
    any_value(coalesce(DISEASE_GENES, false))        AS disease_gene,
    any_value(coalesce(pLOF, false))                 AS plof,
    any_value(highest_PLI)                           AS pli,
    any_value(TRY_CAST({_gene_id('LOEUF_bin_merged')} AS DOUBLE))  AS loeuf_bin,
    any_value({_gene_id('OMIM_ID_merged')})          AS omim_id,
    -- The two genuinely free-text columns; everything else in this block is an
    -- enum or an id and splits safely. See `_gene_text`.
    {_gene_text('OMIM_phenotype_merged')}            AS omim_phenotype,
    {_gene_text('GenCC_disease_merged')}             AS gencc_disease,
    any_value({_gene_id('OMIM_inheritance_merged')}) AS omim_inheritance,
    any_value({_gene_id('OMIM_morbid_merged')} = 'yes')  AS omim_morbid,
    any_value({_gene_id('GenCC_classification_merged')}) AS gencc_classification,
    any_value({_gene_id('GenCC_moi_merged')})        AS gencc_moi,
    any_value({_gene_id('GenCC_pmid_merged')})       AS gencc_pmid,
    any_value(TRY_CAST({_gene_id('NCBI_gene_ID_merged')} AS BIGINT))  AS ncbi_gene_id,
    any_value({_gene_id('HGNC_gene_ID_merged')})     AS hgnc_id,
    -- Highest allele frequency of a *known benign* insertion overlapping this
    -- site, across dbVar / gnomAD-SV / PacBioCoLoRS. Present on 13.7% of HPRC
    -- rows; NULL means "no benign insertion catalogued here", not "rare".
    any_value(B_ins_AFmax)                           AS pop_ins_af,
    any_value(B_ins_source)                          AS pop_ins_source,
    any_value(AnnotSV_ID)                            AS annotsv_id
"""


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
    SELECT * FROM calls
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
    SELECT DISTINCT chrom, ins_coord, SVID, canonical_motif, motif_length,
           novelty, ucsc_novelty, trexplorer_novelty,
           ucsc_start, ucsc_end, ucsc_distance, ucsc_motif, ucsc_canonical,
           ucsc_motif_edits, ucsc_n_nearby, ucsc_period, ucsc_copy_num,
           ucsc_consensus_size, ucsc_per_match, ucsc_per_indel,
           trexplorer_start, trexplorer_end, trexplorer_distance,
           trexplorer_motif, trexplorer_canonical, trexplorer_motif_edits,
           trexplorer_n_nearby
    FROM alleles JOIN representative p USING (chrom, ins_coord, SVID)
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
           count(DISTINCT SVID) FILTER (WHERE novelty <> 'known') AS n_novel_alleles,
           {GENE_SQL}
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
    r.SVID                                  AS representative_svid,
    a.* EXCLUDE (chrom, ins_coord, n_samples, n_carrier_alleles, n_alleles,
                 n_motifs, n_novel_alleles, median_len, min_len, max_len,
                 mean_purity, median_units, median_depth,
                 mean_insertion_purity, mean_repeat_coverage, novelty,
                 ucsc_novelty, trexplorer_novelty)
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
# STRchive overlap
# --------------------------------------------------------------------------- #

#: The curated disease-locus overlap, which is a *different question* from
#: `disease_gene` and is kept in its own columns because of it.
#:
#: `disease_gene` now comes from AnnotSV and means "this insertion is in a gene
#: with an OMIM disease entry" — 2,201 HPRC loci. `strchive_locus` means "this
#: insertion is within 10 bp of one of the 82 curated *repeat-expansion* loci" —
#: 39 of them. The second is a far stronger claim about a far smaller set, and
#: collapsing the two would throw it away.
#:
#: Before this callset carried gene annotation, `gene` was filled from STRchive
#: because the alternative was an empty column; that made `gene` NON-NULL only at
#: a disease locus and the manifest had to say so in as many words. It is now a
#: real gene annotation and that caveat is gone.
STRCHIVE_SQL = f"""
WITH hit AS (
    SELECT l.locus_id, s.gene AS strchive_gene, s.id AS strchive_id,
           s.disease AS strchive_disease,
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
       h.strchive_gene,
       h.strchive_id IS NOT NULL AS strchive_locus,
       h.strchive_id, h.strchive_disease, h.strchive_inheritance,
       h.strchive_evidence, h.strchive_novel_in_ref,
       h.distance_bp AS strchive_distance_bp
FROM loci l LEFT JOIN (SELECT * FROM hit WHERE rn = 1) h USING (locus_id)
"""


# --------------------------------------------------------------------------- #
# Checks that earn their keep
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
        print(f"  input {raw:,} rows, {distinct:,} distinct "
              f"— dropped {raw - distinct:,} exact duplicates ({pct:.1f}%)")


def _invariance_report(con: duckdb.DuckDBPyConnection) -> None:
    """Fail the build if gene annotation ever varies within one insertion site.

    `GENE_SQL` reads the whole AnnotSV block with `any_value`, which is only
    honest if the block is a property of the site. It is — AnnotSV annotates a
    position, and every allele at one position gets the same answer — but that is
    an assumption about someone else's output, so it is checked rather than
    trusted. A cohort where it fails would otherwise render whichever gene DuckDB
    happened to see first, silently and differently on every rebuild.
    """
    bad = con.execute(
        """SELECT count(*) FROM (
             SELECT chrom, ins_coord FROM calls GROUP BY 1, 2
             HAVING count(DISTINCT Gene_name)      > 1
                 OR count(DISTINCT Location_merged) > 1
                 OR count(DISTINCT Tx_merged)       > 1)"""
    ).fetchone()[0]
    if bad:
        raise SystemExit(
            f"[build] {bad} loci carry more than one AnnotSV annotation. "
            "GENE_SQL's any_value() would pick one arbitrarily — fix the input "
            "or roll these up explicitly before continuing."
        )


def _location_report(con: duckdb.DuckDBPyConnection) -> None:
    """How often the two breakpoints of `Location_merged` disagree.

    `feature`/`feature_index` are parsed off the LEFT half of "intron12-intron12".
    For an insertion both halves are the same feature and the parse is exact; a
    non-zero count here means the gene track is labelling some loci by their left
    breakpoint alone, which is worth knowing rather than discovering later.
    """
    split = "str_split(list_distinct(str_split(Location_merged, ', '))[1], '-')"
    n = con.execute(
        f"SELECT count(DISTINCT chrom || ':' || ins_coord) FROM calls "
        f"WHERE Location_merged IS NOT NULL AND {split}[1] <> {split}[2]"
    ).fetchone()[0]
    if n:
        print(f"  {n:,} loci span two features — the track labels the left breakpoint")


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

def build(cohort: Cohort) -> int:
    source = PLOTS / cohort.source
    if not source.exists():
        print(f"[{cohort.name}] missing input: {source.relative_to(REPO_ROOT)}",
              file=sys.stderr)
        print(f"[{cohort.name}] build it with:\n"
              "  just plot-data      # download the TSVs\n"
              "  just plot-parquet   # convert them", file=sys.stderr)
        return 1

    out = REPO_ROOT / "data" / cohort.out
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()

    print(f"[{cohort.name}] {cohort.label} — {source.name}")
    con.execute(f"CREATE VIEW raw AS SELECT * FROM read_parquet('{source}')")
    # No column retyping here any more: `plots_to_parquet.py` turned the `NA`
    # sentinels into NULLs at conversion time, so every numeric column already
    # arrives numeric. That is the whole reason the Parquet step exists.
    con.execute("CREATE VIEW calls AS SELECT DISTINCT * FROM raw")
    con.create_function(
        "annotsv_collapse", annotsv_collapse,
        [duckdb.sqltype("VARCHAR")], duckdb.sqltype("VARCHAR"),
    )
    _dedupe_report(con)
    _invariance_report(con)
    _location_report(con)

    con.execute(f"CREATE TABLE loci AS {LOCI_SQL}")

    if STRCHIVE.exists():
        con.execute(f"CREATE VIEW strchive AS SELECT * FROM read_parquet('{STRCHIVE}')")
        con.execute(f"CREATE TABLE loci_annotated AS {STRCHIVE_SQL}")
        con.execute("DROP TABLE loci")
        con.execute("ALTER TABLE loci_annotated RENAME TO loci")
        hits = con.execute("SELECT count(*) FROM loci WHERE strchive_locus").fetchone()[0]
        print(f"  {hits} loci within {STRCHIVE_WINDOW} bp of a STRchive disease locus")
    else:
        # Without the catalog the columns still have to exist, or the STRchive
        # surface queries a column that is not there. `gene` and `disease_gene`
        # are no longer among them — those come from AnnotSV now and are always
        # present.
        con.execute("ALTER TABLE loci ADD COLUMN strchive_gene VARCHAR")
        con.execute("ALTER TABLE loci ADD COLUMN strchive_locus BOOLEAN DEFAULT false")
        print("  no STRchive catalog — strchive_* left empty. "
              "Run scripts/fetch_strchive.py first to fill them.", file=sys.stderr)

    con.execute(f"CREATE TABLE segments AS {SEGMENTS_SQL}")

    for name in ("loci", "segments"):
        path = out / f"{name}.parquet"
        con.execute(f"COPY {name} TO '{path}' (FORMAT parquet)")
        n = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        print(f"  {n:,} rows -> {path.relative_to(REPO_ROOT)}")

    novel, genic, disease, exonic, total = con.execute(
        """SELECT count(*) FILTER (WHERE novel),
                  count(*) FILTER (WHERE genic),
                  count(*) FILTER (WHERE disease_gene),
                  count(*) FILTER (WHERE exonic),
                  count(*) FROM loci"""
    ).fetchone()
    print(f"  {novel:,} of {total:,} loci novel ({100.0 * novel / total:.1f}%) · "
          f"{genic:,} in a gene · {disease:,} in a disease gene · {exonic:,} exonic")
    return 0


def main(argv: list[str]) -> int:
    wanted = argv[1:] or list(COHORTS)
    unknown = [c for c in wanted if c not in COHORTS]
    if unknown:
        print(f"[build] unknown cohort(s): {', '.join(unknown)}. "
              f"Known: {', '.join(COHORTS)}", file=sys.stderr)
        return 1
    return max(build(COHORTS[name]) for name in wanted)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
