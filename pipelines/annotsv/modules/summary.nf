/*
================================================================================
  Nextflow DSL2 Module: GENERATE_SUMMARY
  Generate a formatted summary table from all AnnotSV annotated TSVs
================================================================================
  Author  : Taimoor
  Project : novelTRs / bcm-hackathon26
  Date    : 2026-08-27
================================================================================
*/

process GENERATE_SUMMARY {

    label 'process_low'
    container 'quay.io/biocontainers/annotsv:3.5.10--hdfd78af_0'

    publishDir path: "${params.outdir}/summary",
               mode: params.publish_dir_mode ?: 'copy',
               pattern: 'annotsv_summary_report.*'

    input:
    path tsv_files

    output:
    path "annotsv_summary_report.txt", emit: txt
    path "annotsv_summary_report.tsv", emit: tsv

    script:
    """
    #!/usr/bin/env python3
    import csv
    import glob
    import os
    import sys
    from collections import Counter

    files = sorted(glob.glob("*.annotated.tsv"))
    if not files:
        # Check all tsv files if not named with .annotated.tsv
        files = sorted(glob.glob("*.tsv"))

    records = []

    for fpath in files:
        fname = os.path.basename(fpath)
        sample = fname.replace(".annotated.tsv", "").replace(".tsv", "")

        total_lines = 0
        full_svs = 0
        split_genes = 0
        sv_types = Counter()
        acmg_counts = Counter()
        genes = set()

        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f, delimiter="\\t")
                for row in reader:
                    total_lines += 1
                    mode = row.get("Annotation_mode", "").lower()
                    if mode == "full":
                        full_svs += 1
                        svt = row.get("SV_type", "UNKNOWN").upper()
                        sv_types[svt] += 1
                    elif mode == "split":
                        split_genes += 1

                    acmg = row.get("ACMG_class", "NA").replace("full=", "").strip()
                    if not acmg:
                        acmg = "NA"
                    acmg_counts[acmg] += 1

                    gene = row.get("Gene_name", "").strip()
                    if gene and gene != "NA":
                        for g in gene.split(";"):
                            if g.strip():
                                genes.add(g.strip())
        except Exception as e:
            sys.stderr.write(f"Error parsing {fpath}: {e}\\n")

        del_cnt = sv_types.get("DEL", 0)
        dup_cnt = sv_types.get("DUP", 0)
        ins_cnt = sv_types.get("INS", 0)
        inv_cnt = sv_types.get("INV", 0)
        bnd_cnt = sv_types.get("BND", 0)
        other_cnt = sum(cnt for k, cnt in sv_types.items() if k not in ("DEL", "DUP", "INS", "INV", "BND"))

        c1 = acmg_counts.get("1", 0)
        c2 = acmg_counts.get("2", 0)
        c3 = acmg_counts.get("3", 0)
        c4 = acmg_counts.get("4", 0)
        c5 = acmg_counts.get("5", 0)
        cNA = acmg_counts.get("NA", 0)

        records.append({
            "Sample": sample,
            "Total_Rows": total_lines,
            "Unique_SVs": full_svs,
            "Split_Genes": split_genes,
            "DEL": del_cnt,
            "DUP": dup_cnt,
            "INS": ins_cnt,
            "INV": inv_cnt,
            "BND": bnd_cnt,
            "OTHER": other_cnt,
            "Unique_Genes": len(genes),
            "ACMG_1_Benign": c1,
            "ACMG_2_LikelyBenign": c2,
            "ACMG_3_VUS": c3,
            "ACMG_4_LikelyPathogenic": c4,
            "ACMG_5_Pathogenic": c5,
            "ACMG_NA": cNA
        })

    # 1. Write Machine-Readable TSV Report
    tsv_out = "annotsv_summary_report.tsv"
    fieldnames = [
        "Sample", "Total_Rows", "Unique_SVs", "Split_Genes",
        "DEL", "DUP", "INS", "INV", "BND", "OTHER", "Unique_Genes",
        "ACMG_1_Benign", "ACMG_2_LikelyBenign", "ACMG_3_VUS",
        "ACMG_4_LikelyPathogenic", "ACMG_5_Pathogenic", "ACMG_NA"
    ]
    with open(tsv_out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\\t")
        writer.writeheader()
        for r in records:
            writer.writerow(r)

    # 2. Write Human-Readable Formatted TXT Report
    txt_out = "annotsv_summary_report.txt"
    with open(txt_out, "w", encoding="utf-8") as f:
        f.write("=" * 115 + "\\n")
        f.write(" " * 38 + "AnnotSV Annotation Pipeline Summary\\n")
        f.write("=" * 115 + "\\n")
        f.write(f"{'Sample / File':<24} | {'Total':<6} | {'SVs':<6} | {'DEL':<5} | {'DUP':<5} | {'INS':<5} | {'INV':<5} | {'BND':<5} | {'Genes':<6} | {'ACMG (1/2/3/4/5/NA)':<20}\\n")
        f.write("-" * 115 + "\\n")

        for r in records:
            acmg_str = f"{r['ACMG_1_Benign']}/{r['ACMG_2_LikelyBenign']}/{r['ACMG_3_VUS']}/{r['ACMG_4_LikelyPathogenic']}/{r['ACMG_5_Pathogenic']}/{r['ACMG_NA']}"
            f.write(f"{r['Sample']:<24} | {r['Total_Rows']:<6} | {r['Unique_SVs']:<6} | {r['DEL']:<5} | {r['DUP']:<5} | {r['INS']:<5} | {r['INV']:<5} | {r['BND']:<5} | {r['Unique_Genes']:<6} | {acmg_str:<20}\\n")

        f.write("=" * 115 + "\\n")
        f.write(f"Total files processed: {len(records)}\\n")
        total_svs = sum(r['Unique_SVs'] for r in records)
        f.write(f"Total unique structural variants: {total_svs}\\n")
        f.write("=" * 115 + "\\n")

    # Print report to stdout for Nextflow execution log
    with open(txt_out, "r") as f:
        print(f.read())
    """

    stub:
    """
    touch annotsv_summary_report.txt
    touch annotsv_summary_report.tsv
    """
}
