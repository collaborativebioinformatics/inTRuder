"""Build reference tandem-repeat catalogues for the novelty screen to read.

A file-in/file-out step like any other: it takes Tandem Repeats Finder ``.dat``
output and writes the BED4 catalogue that
``novelty --platform bed --repeats bed=<path>`` consumes. Building one locally is
what lets the screen use a reference annotation produced at this pipeline's own
TRF parameters, instead of only the published UCSC and TRExplorer catalogues.

``scripts/catalog/build_hg38_trf.sh`` drives the whole hg38 build -- download,
TRF, then :mod:`intruder.pipeline.catalog.dat2bed`. See
``docs/tools/HG38_TRF_CATALOGUE.md``.
"""
