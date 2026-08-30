"""One scatter function, so both steps draw the same figure.

Deliberately thin. Publication figures belong in a notebook where they can be
iterated on; what a CLI needs is the plot you look at *while* deciding whether
the run is worth keeping, and for that the important properties are that the
colouring is honest (a categorical variable never gets a continuous colour bar)
and that 6,000 overlapping points stay readable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

#: Above this many distinct values a categorical colouring is unreadable as a
#: legend, so the largest groups are named and the rest become one grey "other".
MAX_LEGEND = 12


def scatter(
    coords: np.ndarray,
    design: pd.DataFrame | None = None,
    colour_by: str | None = None,
    title: str = "",
    path: str | None = None,
    size: float = 12.0,
    alpha: float = 0.75,
):
    """Scatter the first two components, coloured by one design column.

    Returns the matplotlib figure. Writes it to ``path`` when given.
    """
    import matplotlib
    if path is not None:
        matplotlib.use("Agg")  # no display on a cluster or in CI
    import matplotlib.pyplot as plt

    coords = np.asarray(coords, dtype=float)
    if coords.shape[1] < 2:
        raise ValueError("need at least two components to scatter")

    fig, ax = plt.subplots(figsize=(7.5, 6.5), constrained_layout=True)
    x, y = coords[:, 0], coords[:, 1]

    if colour_by is None or design is None or colour_by not in design:
        ax.scatter(x, y, s=size, alpha=alpha, linewidths=0, color="#3b6ea5")
    elif _is_continuous(design[colour_by]):
        values = pd.to_numeric(design[colour_by], errors="coerce").to_numpy(float)
        dots = ax.scatter(x, y, c=values, s=size, alpha=alpha, linewidths=0,
                          cmap="viridis")
        fig.colorbar(dots, ax=ax, label=colour_by)
    else:
        _categorical(ax, x, y, design[colour_by].astype(str), colour_by, size, alpha)

    ax.set_xlabel("component 1")
    ax.set_ylabel("component 2")
    ax.set_title(title or (f"coloured by {colour_by}" if colour_by else ""))
    ax.spines[["top", "right"]].set_visible(False)

    if path is not None:
        fig.savefig(path, dpi=150)
    return fig


def _is_continuous(column: pd.Series) -> bool:
    """Numeric with enough distinct values to be worth a gradient.

    ``cropped`` is stored as bool and ``pos`` as int; the first wants two
    colours and a legend, the second a colour bar. Distinct-count is what
    separates them, not dtype.
    """
    if column.dtype == bool or not pd.api.types.is_numeric_dtype(column):
        return False
    return column.nunique() > MAX_LEGEND


def _categorical(ax, x, y, values: pd.Series, name: str, size: float, alpha: float):
    import matplotlib.pyplot as plt

    order = values.value_counts().index.tolist()
    shown, rest = order[:MAX_LEGEND], set(order[MAX_LEGEND:])
    if rest:
        mask = values.isin(rest).to_numpy()
        ax.scatter(x[mask], y[mask], s=size, alpha=alpha * 0.5, linewidths=0,
                   color="#b0b0b0", label=f"other ({len(rest)})")
    palette = plt.get_cmap("tab20").colors
    for i, key in enumerate(shown):
        mask = (values == key).to_numpy()
        ax.scatter(x[mask], y[mask], s=size, alpha=alpha, linewidths=0,
                   color=palette[i % len(palette)], label=key)
    ax.legend(title=name, fontsize="small", markerscale=1.8,
              loc="center left", bbox_to_anchor=(1.02, 0.5), frameon=False)
