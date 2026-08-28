"""Post-hoc analysis of pipeline output.

Reads the tables the pipeline writes; nothing here runs as a pipeline step. Its
plotting and stats dependencies live in the ``analysis`` uv group, so
``uv sync --group analysis`` is needed before these modules import.
"""
