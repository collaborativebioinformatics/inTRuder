"""inTRuder -- novel tandem repeats from long-read SV insertion calls.

Three subpackages, kept deliberately separate:

- ``intruder.trcore``    shared primitives (coordinates, motifs, downloads). The
                         only code a pipeline step may import from outside
                         itself; steps never import each other.
- ``intruder.pipeline``  the pipeline steps.
- ``intruder.analysis``  post-hoc analysis of their output.

One owned top-level name rather than several generic ones: ``pipeline`` or
``analysis`` installed bare into site-packages would collide with real packages.
"""
