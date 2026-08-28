"""Hyperparameter search over the screen, driven by Optuna.

The screen has a dozen thresholds and no ground truth, so "search" here means
two different things and it is worth keeping them apart:

*enumeration* (``--sampler grid``, the default)
    Run every combination and tabulate what each produces. This is a sensitivity
    analysis -- it says which conclusions survive the choice of thresholds and
    which are an artefact of them. Nothing is being optimised.

*optimisation* (``--sampler tpe`` / ``random``)
    Needs an objective. Two are available:

    ``agreement``
        The Jaccard index of the sets of loci that each catalogue independently
        calls novel. Thresholds where UCSC and TRExplorer flag *the same* loci
        are thresholds where the call is a property of the data rather than of
        the cutoff. Needs at least two platforms. Note it is deliberately scored
        on the novel sets, not on overall agreement -- otherwise a huge
        ``--window`` wins by making everything ``known`` in both catalogues.

    ``truth``
        Balanced accuracy against a labelled set of loci (``--truth``), which is
        the only honest way to optimise if you have one.

Optuna gives all of this trial storage, resumable studies and its dashboard for
free; pass ``--storage sqlite:///study.db`` to keep them.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import pandas as pd

OBJECTIVES = ("none", "agreement", "truth")
SAMPLERS = ("grid", "tpe", "random")


# --------------------------------------------------------------------------- #
# search space
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Axis:
    """One dimension of the search space, parsed from a command-line value.

    ``0,1,10`` is categorical; ``0:50`` is a range; ``0:50:5`` is a range with a
    step, which is the form a grid can enumerate. ``none`` turns a threshold off
    and is a perfectly good categorical value.
    """

    name: str
    kind: Callable[[str], object]
    values: tuple | None = None
    low: float | None = None
    high: float | None = None
    step: float | None = None

    @property
    def is_range(self) -> bool:
        return self.values is None

    @property
    def is_fixed(self) -> bool:
        return self.values is not None and len(self.values) == 1

    def suggest(self, trial):
        if self.values is not None:
            if len(self.values) == 1:            # nothing to search
                return self.values[0]
            return trial.suggest_categorical(self.name, list(self.values))
        if self.kind is int:
            return trial.suggest_int(self.name, int(self.low), int(self.high),
                                     step=int(self.step or 1))
        return trial.suggest_float(self.name, float(self.low), float(self.high),
                                   step=self.step)

    def grid_values(self) -> list:
        if self.values is not None:
            return list(self.values)
        if not self.step:
            raise ValueError(
                f"--{self.name.replace('_', '-')} is the range "
                f"{self.low}:{self.high}, which a grid cannot enumerate; give a "
                f"step ({self.low}:{self.high}:1) or a comma-separated list, or "
                f"use --sampler tpe"
            )
        values, current = [], self.low
        while current <= self.high + 1e-9:
            values.append(self.kind(current) if self.kind is not int else int(current))
            current += self.step
        return values


def parse_axis(name: str, kind: Callable[[str], object], raw: str, *,
               optional: Callable[[Callable], Callable]) -> Axis:
    """Parse one ``--flag`` value into an :class:`Axis`."""
    text = str(raw).strip()
    if ":" in text:
        parts = text.split(":")
        if len(parts) not in (2, 3):
            raise ValueError(f"--{name.replace('_', '-')}: expected lo:hi[:step], "
                             f"got {text!r}")
        low, high = float(parts[0]), float(parts[1])
        step = float(parts[2]) if len(parts) == 3 else None
        if high < low:
            raise ValueError(f"--{name.replace('_', '-')}: {low} > {high}")
        return Axis(name, kind, low=low, high=high, step=step)
    parser = optional(kind)
    return Axis(name, kind, values=tuple(parser(part) for part in text.split(",")))


# --------------------------------------------------------------------------- #
# objectives
# --------------------------------------------------------------------------- #

def agreement(loci: pd.DataFrame, platforms: Sequence[str]) -> float:
    """Jaccard index of the novel-locus sets the platforms independently produce.

    ``1.0`` means every catalogue flags exactly the same loci; ``0.0`` means they
    share none -- or that none of them flagged anything, which is equally
    uninformative and must not look like a win.
    """
    if len(platforms) < 2:
        raise ValueError("the `agreement` objective needs at least two --platform "
                         "entries; use --objective truth or none")
    sets = [set(loci.index[loci[name] != "known"]) for name in platforms]
    union = set().union(*sets)
    if not union:
        return 0.0
    return len(set.intersection(*sets)) / len(union)


def read_truth(path: str, locus_cols: Sequence[str], column: str | None) -> pd.Series:
    """Labelled loci: the locus key columns plus a known/novel status column."""
    frame = pd.read_csv(path, sep="\t")
    missing = [c for c in locus_cols if c not in frame.columns]
    if missing:
        raise ValueError(f"{path}: truth table is missing locus column(s) {missing}")
    if column is None:
        for candidate in ("novelty", "status", "label"):
            if candidate in frame.columns:
                column = candidate
                break
        else:
            raise ValueError(f"{path}: no novelty/status/label column; pass "
                             f"--truth-col")
    if column not in frame.columns:
        raise ValueError(f"{path}: no column {column!r}")

    labels = frame[column].astype(str).str.strip().str.lower()
    novel = ~labels.isin(("known", "false", "0", "no"))
    return pd.Series(novel.to_numpy(), index=pd.MultiIndex.from_frame(frame[locus_cols]),
                     name="truth_novel")


def balanced_accuracy(loci: pd.DataFrame, truth: pd.Series) -> float:
    """Mean of the per-class recalls over the labelled loci; 0.5 is chance."""
    predicted = (loci["novelty"] != "known").rename("predicted_novel")
    joined = pd.concat([predicted, truth], axis=1, join="inner")
    if joined.empty:
        raise ValueError("no locus in the truth table matches the screened table; "
                         "check the chrom/pos columns and the coordinate base")
    recalls = []
    for label in (True, False):
        actual = joined[joined["truth_novel"] == label]
        if len(actual):
            recalls.append(float((actual["predicted_novel"] == label).mean()))
    return sum(recalls) / len(recalls) if recalls else 0.0


# --------------------------------------------------------------------------- #
# the study
# --------------------------------------------------------------------------- #

def build_sampler(name: str, axes: Sequence[Axis], seed: int | None):
    import optuna

    if name == "grid":
        space = {axis.name: axis.grid_values() for axis in axes if not axis.is_fixed}
        return optuna.samplers.GridSampler(space, seed=seed), _grid_size(space)
    if name == "random":
        return optuna.samplers.RandomSampler(seed=seed), None
    return optuna.samplers.TPESampler(seed=seed), None


def _grid_size(space: dict[str, list]) -> int:
    total = 1
    for values in space.values():
        total *= len(values)
    return total


def run_study(axes: Sequence[Axis], evaluate: Callable[[dict], tuple[dict, float]], *,
              sampler: str = "grid", trials: int | None = None, seed: int | None = None,
              storage: str | None = None, study_name: str | None = None,
              direction: str = "maximize") -> list[dict]:
    """Run the search; returns one metrics row per completed trial.

    ``evaluate`` receives the parameter dict and returns ``(metrics_row, score)``.
    """
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    chosen, grid_size = build_sampler(sampler, axes, seed)
    if sampler == "grid":
        trials = grid_size if trials is None else min(trials, grid_size)
    elif trials is None:
        trials = 50
    print(f"[novelty] optuna: {sampler} sampler, {trials:,} trial(s)", file=sys.stderr)

    study = optuna.create_study(
        sampler=chosen, direction=direction, storage=storage,
        study_name=study_name, load_if_exists=storage is not None,
    )

    rows: list[dict] = []

    def objective(trial) -> float:
        params = {axis.name: axis.suggest(trial) for axis in axes}
        row, score = evaluate(params)
        for key, value in row.items():
            trial.set_user_attr(key, value)
        rows.append(row)
        return score

    study.optimize(objective, n_trials=trials)
    return rows
