"""Finding the repository checkout a module is running from.

Catalogues and bundled data live under the repo's ``data/``, not inside the
installed package, so several steps need the checkout root. Deriving it by
counting ``Path.parents`` hardcodes how deep the module sits and silently
returns the wrong directory the moment anything moves -- which is exactly what
happened when the packages went under ``src/python/intruder/``. So walk up
looking for a marker instead, and let the layout change freely.
"""

from __future__ import annotations

from pathlib import Path

#: A directory is the repo root when it holds all of these.
MARKERS = ("pyproject.toml", "data")


def repo_root(start: Path | str) -> Path | None:
    """The checkout ``start`` sits in, or ``None`` when installed outside one.

    Callers pass their own ``__file__`` rather than letting this default to
    ``paths.py``: the answer is then about where the *caller* lives, which is
    what the caller means, and it stays monkeypatchable in tests that simulate
    running from outside a checkout.

    Returns ``None`` rather than raising -- every caller has a non-checkout
    fallback (a user cache directory, or a required CLI flag), and running from
    a wheel in a venv is a supported way to use these steps.
    """
    here = Path(start).resolve()
    for candidate in (here, *here.parents):
        if all((candidate / marker).exists() for marker in MARKERS):
            return candidate
    return None
