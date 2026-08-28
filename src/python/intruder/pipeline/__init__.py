"""Pipeline steps.

Every step reads files and writes files, with no shared in-process state, so it
can be driven from Nextflow, a shell loop or a notebook without change. Steps do
not import one another -- anything genuinely common belongs in
``intruder.trcore``.
"""
