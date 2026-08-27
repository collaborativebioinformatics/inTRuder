"""Dimensionality reduction of Evo 2 embedding views.

8192 dimensions per window, a few thousand windows. Reduction here serves two
different purposes that want different settings, and conflating them is the
usual way to end up with a picture nobody can defend:

*To look at it.* UMAP or t-SNE into 2-D. Neither preserves distance, density or
cluster size, so the output is a hypothesis generator and never evidence on its
own -- pair it with :mod:`analysis.diagnostics`.

*To feed something else.* PCA into 30-50 dimensions, as a denoising step before
clustering or neighbour search. Linear, invertible, and its
``explained_variance_ratio_`` tells you how much you threw away, which is the
property the non-linear methods cannot offer.

:func:`reduce` covers both; the CLI is :mod:`analysis.dim_reduc.cli`
(``analysis-reduce``).
"""

from analysis.dim_reduc.reduce import METHODS, Reduction, reduce

__all__ = ["METHODS", "Reduction", "reduce"]
