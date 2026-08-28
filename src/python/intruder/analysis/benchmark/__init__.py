"""Benchmarking a TRF callset against a published reference catalogue.

Reads the TSV the TRF step writes and the intersections ``bedtools`` found
against a catalogue, and labels each call as in or out of that catalogue. It
scores work the pipeline has already done, so it never runs as a pipeline step.
Its polars dependency is in the ``analysis`` uv group: ``uv sync --group
analysis`` before importing.
"""
