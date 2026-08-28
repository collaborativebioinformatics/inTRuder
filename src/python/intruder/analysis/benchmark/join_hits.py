import argparse

import polars as pl

pl.Config(set_tbl_cols=-1)
pl.Config(set_tbl_rows=1000)

HITS_COLUMNS = ['chrom', 'ins_coord', 'end', 'SVID', 'depth', 'insert_size', 'sample', 'rep_start', 'rep_end', 'motif', 'purity', 'motif_length', 'rep_length', 'rep_units']

def main():
    p = argparse.ArgumentParser(description="Join query all query with hits set to report if a TR is or isn't in groud truth set (hit set).")
    p.add_argument("--query", required=True, help="Query file (TSV)")
    p.add_argument("--hits", required=True, help="hits file (TSV)")
    p.add_argument("--output", required=True, help="Output file (TSV)")
    args = p.parse_args()

    query = pl.scan_csv(args.query, separator="\t")
    hits = pl.scan_csv(args.hits, separator="\t", new_columns=HITS_COLUMNS).drop("end")

    keys = [c for c in query.collect_schema().names() if c in hits.collect_schema().names()]
    if not keys:
        p.error("no shared columns between query and hits")

    result = query.join(
        hits.select(keys).unique().with_columns(pl.lit(True).alias("in_catalog")),
        on=keys,
        how="left",
    ).with_columns(pl.col("in_catalog").fill_null(False))

    result.sink_csv(f"{args.output}.gz", separator="\t", compression="gzip")

if __name__ == "__main__":
    main()
