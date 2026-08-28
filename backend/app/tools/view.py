"""The tool that moves the interface.

`set_view` is what makes chat and the charts two views of one state rather than
two panels: it writes the same filter state the chips and the sort control write,
so an answer in prose leaves the screen showing the loci it is about.

Its arguments mirror `frontend/lib/types.ts`; adding a filter means adding it in
both places.
"""

from __future__ import annotations

from typing import Annotated, Literal

from langchain_core.tools import tool

from app.tools.payload import dump


@tool
def set_view(
    page: Annotated[
        Literal["catalog", "strchive"] | None,
        "Which surface to show. 'catalog' is this cohort's candidate loci; "
        "'strchive' is the curated disease-locus reference and our screen against it.",
    ] = None,
    novel_only: Annotated[bool | None, "Show only loci absent from every catalog."] = None,
    novelty: Annotated[
        Literal["known", "novel_motif", "novel_locus"] | None,
        "The screen's three-valued verdict. 'novel_motif' means the reference has "
        "repeats here but none with this motif; 'novel_locus' means it annotates "
        "nothing here. Prefer this over novel_only when the user's question "
        "distinguishes the two.",
    ] = None,
    platform_agreement: Annotated[
        Literal["both", "ucsc_only", "trexplorer_only", "neither"] | None,
        "Restrict by how the reference catalogs compare. 'both' means UCSC and "
        "TRExplorer independently call it novel — the case worth trusting.",
    ] = None,
    chrom: Annotated[str | None, "Restrict to one chromosome, e.g. 'chr4'. Use null to clear."] = None,
    region: Annotated[
        str | None,
        "Restrict to a genomic range, e.g. 'chr3:1000-50000' (GRCh38, both ends "
        "inclusive). Keeps the loci whose insertion site falls inside it. Use "
        "chrom for a whole chromosome — this needs a range.",
    ] = None,
    motif_class: Annotated[
        Literal["homopolymer", "STR", "VNTR"] | None,
        "Restrict to one motif class. Homopolymer is a 1bp motif, STR is 2-6bp, "
        "VNTR is 7bp or longer.",
    ] = None,
    min_motif_len: Annotated[int | None, "Minimum motif length in bp."] = None,
    min_samples: Annotated[int | None, "Minimum number of carrier samples, out of 68."] = None,
    min_purity: Annotated[float | None, "Minimum mean repeat purity, 0-1."] = None,
    min_insertion_purity: Annotated[
        float | None,
        "Minimum fraction of the insertion that is tandem repeat at all, 0-1. "
        "Low values mean the insertion is mostly something else.",
    ] = None,
    disease_gene_only: Annotated[
        bool | None,
        "Show only loci in a gene carrying an OMIM disease entry (2,201 of "
        "17,270). Weaker than strchive_status: 'in a gene linked to some "
        "disease', not 'at a known repeat-expansion locus'.",
    ] = None,
    genic_only: Annotated[
        bool | None,
        "Show only loci inside an annotated gene (9,043 of 17,270). The other "
        "half are intergenic, which is a real finding and not missing data.",
    ] = None,
    exonic_only: Annotated[
        bool | None,
        "Show only loci where a breakpoint lands inside an exon (265). This is "
        "the strong claim about coding impact — NOT gene_region='CDS', which "
        "merely means the insertion sits between the start and stop codons and "
        "is true of thousands of intronic loci.",
    ] = None,
    constrained_only: Annotated[
        bool | None,
        "Show only loci in a gene with gnomAD pLI >= 0.9 — intolerant of loss "
        "of function (1,867 loci).",
    ] = None,
    gene_region: Annotated[
        Literal["CDS", "UTR", "5'UTR", "3'UTR"] | None,
        "Which transcript region the insertion sits WITHIN. Read the caveat on "
        "exonic_only before using 'CDS' to mean coding impact.",
    ] = None,
    gene: Annotated[str | None, "Restrict to one gene symbol, e.g. 'XYLT1'."] = None,
    gene_query: Annotated[
        str | None,
        "Free-text gene search: keeps loci whose gene symbol contains this "
        "text, case-insensitively. Use it when the user is searching rather "
        "than naming a gene ('anything in the SYNE family'); prefer the exact "
        "`gene` when you know the symbol.",
    ] = None,
    sample: Annotated[str | None, "Restrict to one sample, e.g. 'HG00290'."] = None,
    strchive_status: Annotated[
        Literal[
            "pathogenic_expansion", "pathogenic_motif", "locus_novel_motif",
            "locus_known_motif", "no_locus_match",
        ] | None,
        "Restrict by the STRchive disease verdict.",
    ] = None,
    strchive_novel_only: Annotated[
        bool | None,
        "On the strchive page: show only the disease loci whose pathogenic motif "
        "is absent from hg38 (11 of 82).",
    ] = None,
    sort: Annotated[
        Literal["position", "novel", "size", "support", "arrays", "motif_len", "purity"]
        | None,
        "How to order the catalog list. 'position' is genomic order (the "
        "default), 'size' is median inserted-allele length, 'support' is how "
        "many samples carry it, 'arrays' is how many separate repeat blocks the "
        "drawn allele is built from (compound loci first), 'novel' puts loci "
        "absent from every catalog on top. Use this when the user asks for the "
        "biggest, the most common, or the most complex loci.",
    ] = None,
    sort_dir: Annotated[
        Literal["asc", "desc"] | None,
        "Sort direction. Omit for the natural one — descending for every sort "
        "except position, where ascending means the start of the chromosome.",
    ] = None,
    focus_locus_id: Annotated[str | None, "Open one locus in the detail view, e.g. 'TRL000123'."] = None,
    focus_strchive_id: Annotated[
        str | None,
        "Open one disease locus on the strchive page, e.g. 'CANVAS_RFC1'. "
        "Sets page to 'strchive' implicitly on the frontend.",
    ] = None,
) -> str:
    """Change what the user is looking at in the browser.

    Call this whenever the user asks to see, show, filter, highlight, or open
    something — the interface is a view onto the same data you query with SQL, and
    this is how you move it. Pass only the fields you intend to change; omitted
    fields are left as they are. Explicitly pass null to clear a filter.

    Prefer calling this alongside your answer rather than instead of it: set the
    view so the user sees the loci, and say what they are looking at.

    A filter needing a column the registered tables do not have is reported back
    as inactive in the interface rather than silently matching everything, so it
    is safe to set one before the screened callset exists — but say so.
    """
    view = {
        key: value
        for key, value in {
            "page": page,
            "novel_only": novel_only,
            "novelty": novelty,
            "platform_agreement": platform_agreement,
            "chrom": chrom,
            "region": region,
            "motif_class": motif_class,
            "min_motif_len": min_motif_len,
            "min_samples": min_samples,
            "min_purity": min_purity,
            "min_insertion_purity": min_insertion_purity,
            "disease_gene_only": disease_gene_only,
            "genic_only": genic_only,
            "exonic_only": exonic_only,
            "constrained_only": constrained_only,
            "gene_region": gene_region,
            "gene": gene,
            "gene_query": gene_query,
            "sample": sample,
            "strchive_status": strchive_status,
            "strchive_novel_only": strchive_novel_only,
            "sort": sort,
            "sort_dir": sort_dir,
            "focus_locus_id": focus_locus_id,
            "focus_strchive_id": focus_strchive_id,
        }.items()
        if value is not None
    }
    if not view:
        return dump({"applied": {}, "note": "No fields supplied; the view was left unchanged."})
    return dump({"applied": view})

