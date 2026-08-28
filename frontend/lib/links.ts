/**
 * Identifiers in the callset, turned into the pages that explain them.
 *
 * Almost every annotation this project carries is a code that means something
 * only if you can look it up: `XM_017012475.1`, `HGNC:9677`, `610652`,
 * `7q36.3`. A page that prints them and stops is asking the reader to copy a
 * string into a search box. A page that links them is one click from the source.
 *
 * The rule this file follows is that **a link is only built where the identifier
 * is unambiguous**. `buildLinks` returns entries only for the fields actually
 * present, so a locus with no OMIM entry gets no dead OMIM link — an external
 * link that lands on a 404 is worse than no link, because the reader cannot tell
 * our missing data from the other site's.
 *
 * Every URL here is a stable, documented permalink form. They are opened with
 * `rel="noreferrer noopener"` at the call site.
 */

import type { Locus } from "@/lib/types";

/** The genome build every coordinate in this project is on. */
const BUILD = "hg38";

/** How much context to put around a locus in the UCSC browser, in bp. An
    insertion is a point, and a point-width view shows nothing around it; 10 kb
    is wide enough to see the neighbouring exons at a glance. */
const UCSC_FLANK = 5_000;

export interface ExternalLink {
  /** Short label — this is a dense row, not a list of sentences. */
  label: string;
  href: string;
  /** Shown on hover, where the label alone does not say what the code is. */
  title?: string;
}

/** The insertion point in the UCSC genome browser, with flanking context. */
export function ucscRegion(chrom: string, pos: number, flank = UCSC_FLANK): string {
  const start = Math.max(1, pos - flank);
  return `https://genome.ucsc.edu/cgi-bin/hgTracks?db=${BUILD}&position=${chrom}%3A${start}-${pos + flank}`;
}

/** A RefSeq transcript. `tx` is the bare accession; the version is appended
    where we have it, because an unversioned accession resolves to the current
    version, which may not be the one AnnotSV annotated against. */
export function refseqTranscript(tx: string, version?: number | null): string {
  const accession = version != null ? `${tx}.${version}` : tx;
  return `https://www.ncbi.nlm.nih.gov/nuccore/${encodeURIComponent(accession)}`;
}

export function ncbiGene(id: number): string {
  return `https://www.ncbi.nlm.nih.gov/gene/${id}`;
}

/** HGNC ids arrive already prefixed (`HGNC:9677`), which is also the URL form. */
export function hgnc(id: string): string {
  return `https://www.genenames.org/data/gene-symbol-report/#!/hgnc_id/${encodeURIComponent(id)}`;
}

export function omim(id: string): string {
  return `https://www.omim.org/entry/${encodeURIComponent(id)}`;
}

export function pubmed(pmid: string): string {
  return `https://pubmed.ncbi.nlm.nih.gov/${encodeURIComponent(pmid)}/`;
}

/** A gene symbol in GeneCards — the fallback when we have a name but no id. */
export function geneCards(symbol: string): string {
  return `https://www.genecards.org/cgi-bin/carddisp.pl?gene=${encodeURIComponent(symbol)}`;
}

/** A STRchive disease locus, e.g. `fraxe_aff2`. */
export function strchiveLocus(id: string): string {
  return `https://strchive.org/loci/${encodeURIComponent(id)}`;
}

/**
 * PubMed ids out of a GenCC citation string.
 *
 * The field is not a clean list. Real values include
 * `15130495;17357069;17357069PMID;18235093` — semicolon-separated, with a
 * `PMID` suffix stuck to some entries, occasional `_`-joined pairs, and at least
 * one OMIM number mixed in among the citations. So this extracts digit runs of
 * plausible PMID length rather than trusting the separator, and de-duplicates:
 * the same id appears twice in that example once the suffix is stripped.
 *
 * Capped because a gene can cite dozens and this renders as a row of chips.
 */
export function parsePmids(raw: string | null | undefined, limit = 6): string[] {
  if (!raw) return [];
  const seen = new Set<string>();
  for (const match of raw.matchAll(/\d{6,8}/g)) {
    seen.add(match[0]);
    if (seen.size >= limit) break;
  }
  return [...seen];
}

/**
 * Every external reference a locus supports, in the order they should be read:
 * the position first, then the gene, then the transcript, then the disease
 * entries. Only the ones whose identifier is actually present.
 */
export function buildLinks(locus: Locus): ExternalLink[] {
  const links: ExternalLink[] = [
    {
      label: "UCSC",
      href: ucscRegion(locus.chrom, locus.pos),
      title: `${locus.chrom}:${locus.pos.toLocaleString("en-US")} ±${UCSC_FLANK / 1000} kb in the ${BUILD} browser`,
    },
  ];

  if (locus.gene) {
    // Prefer the numeric id: a symbol can be an alias that resolves to the
    // wrong record, an NCBI Gene ID cannot.
    links.push(
      locus.ncbi_gene_id != null
        ? { label: locus.gene, href: ncbiGene(locus.ncbi_gene_id), title: `NCBI Gene ${locus.ncbi_gene_id}` }
        : { label: locus.gene, href: geneCards(locus.gene), title: "GeneCards" },
    );
  }
  if (locus.hgnc_id) {
    links.push({ label: locus.hgnc_id, href: hgnc(locus.hgnc_id), title: "HGNC gene symbol report" });
  }
  if (locus.tx) {
    const accession = locus.tx_version != null ? `${locus.tx}.${locus.tx_version}` : locus.tx;
    links.push({
      label: accession,
      href: refseqTranscript(locus.tx, locus.tx_version),
      // The exon count is a property of THIS transcript, and AnnotSV's pick is
      // not stable within a gene. Saying so on the link is what makes the count
      // drawn in the gene track checkable rather than merely asserted.
      title: locus.exon_count
        ? `RefSeq transcript AnnotSV annotated against — ${locus.exon_count} exons`
        : "RefSeq transcript AnnotSV annotated against",
    });
  }
  if (locus.omim_id) {
    links.push({ label: `OMIM ${locus.omim_id}`, href: omim(locus.omim_id), title: locus.omim_phenotype ?? undefined });
  }
  if (locus.strchive_id) {
    links.push({
      label: "STRchive",
      href: strchiveLocus(locus.strchive_id),
      title: locus.strchive_disease ?? "Curated repeat-expansion locus",
    });
  }
  for (const pmid of parsePmids(locus.gencc_pmid, 3)) {
    links.push({ label: `PMID ${pmid}`, href: pubmed(pmid), title: locus.gencc_disease ?? undefined });
  }
  return links;
}
