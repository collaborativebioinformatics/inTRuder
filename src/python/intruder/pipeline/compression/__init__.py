"""Compressibility annotation for SV insertion sequences.

A repetitive sequence compresses well, so the ratio of raw bytes to
zlib-compressed bytes is a cheap proxy for "is this insertion a tandem repeat?"
-- the idea behind superSTR. The step reads a VCF and writes the same VCF with
an ``SVCOMP`` INFO field per ALT allele.

    compression.annotate   the `uv run compression` command line
"""
