"""
within.py — how much more variable one case is than its count model allows (φ).

A day of stay is not an independent event: one patient adds many. within_dispersion=
tells funnel() how much to widen for that (docs/methods.md §4.12). This module reads it
from the data funnel() was given, per facet:

    within()            the φ a facet uses, and where it came from
    estimate_within()   φ̂ from case-level rows, or from SQL totals (cases=, sum_sq=)
    within_check()      the clustering check behind the "counts look clustered" warning

It works on funnel()'s normalized frame (pandas), so it sits beside the front door
rather than in core/.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

# Working columns of funnel()'s normalized frame.
UNIT, Y, N, EXCL = "__unit", "__y", "__n", "__exclude"
CASES, SS, PHI = "__cases", "__sum_sq", "__phi"

# Fewer residual degrees of freedom than this and the rows say little about clumping.
_ROWS_MIN_DF = 30


@dataclass(frozen=True)
class Within:
    phi: float                      # the scalar φ the model divides by (1 under a column)
    phi_units: dict | None          # {unit: φᵢ} under a within_dispersion column
    source: str                     # default | supplied | estimated | column
    check: tuple | None             # the case-level clustering check (φ̂, p), or None


def within(rows, measure: str, within_dispersion, aggregated, phi_column) -> Within:
    """Within-case dispersion for one facet; excluded providers never enter the estimate."""
    kept = rows[~rows[EXCL]] if EXCL in rows else rows
    if phi_column is not None:
        return Within(1.0, unit_phi(rows, phi_column), "column", None)
    if within_dispersion == "estimate":
        return Within(estimate_within(kept, measure, aggregated), None, "estimated", None)
    phi = float(within_dispersion)
    if phi != 1.0:
        return Within(phi, None, "supplied", None)
    return Within(1.0, None, "default", within_check(kept, measure, aggregated))


def estimate_within(rows: pd.DataFrame, measure: str, aggregated: bool = False) -> float:
    """
    within_dispersion="estimate" for one facet: φ̂ of _row_phi (or _agg_phi from
    cases=/sum_sq=), from the providers that are not excluded.
    """
    binomial = measure == "proportion"
    if binomial and _one_item_per_case(rows, aggregated):
        raise ValueError(
            "within_dispersion='estimate' found one item per row (every n is 1). A "
            "row that is a single yes/no cannot show clustering, so there is nothing "
            "to estimate. If several rows belong to one case (the questions of one "
            "survey), sum them to one row per case: y = items meeting the measure, "
            "n = items answered. If each row really is one independent case, leave "
            "within_dispersion at 1."
        )
    found = _agg_phi(rows, binomial) if aggregated else _row_phi(rows, binomial)
    if found is None and aggregated:
        raise ValueError(
            "within_dispersion='estimate' found no provider with more than one case "
            "(cases= is 1 everywhere), so it cannot measure how much single cases "
            "vary. Pass a known within_dispersion= number instead."
        )
    if found is None:
        raise ValueError(
            "within_dispersion='estimate' needs several rows per unit: one per case "
            "(stay-level data, or one row per survey), so it can measure how much "
            "single cases vary. Every unit here has one row. Pass case-level rows, "
            "or a known within_dispersion= number instead."
        )
    return found[0]


def within_check(rows: pd.DataFrame, measure: str, aggregated: bool = False):
    """
    (φ̂, p) from one facet's case-level rows for the clustering warning, with p the
    Pearson χ² test of φ = 1 on N − K degrees of freedom (Wilson–Hilferty); None where the
    rows are providers, carry fewer than _ROWS_MIN_DF residual degrees of freedom, or are
    single yes/no items, which cannot show clustering.
    """
    binomial = measure == "proportion"
    if binomial and _one_item_per_case(rows, aggregated):
        return None
    found = _agg_phi(rows, binomial) if aggregated else _row_phi(rows, binomial)
    if found is None or found[1] < _ROWS_MIN_DF:
        return None
    phi, df = found
    h = 2.0 / (9.0 * df)
    z = ((max(phi, 0.0)) ** (1.0 / 3.0) - (1.0 - h)) / math.sqrt(h)
    return phi, 0.5 * math.erfc(z / math.sqrt(2.0))


def _row_phi(rows: pd.DataFrame, binomial: bool) -> tuple[float, int] | None:
    """
    (φ̂, N − K) from case-level rows, around each provider's own rate θ̂ⱼ = Σy/Σn, so
    real differences between providers stay out of φ̂; those are τ²'s job.

    Counts (oe, rate): φ̂ = Σⱼ Σᵢ (yᵢⱼ − θ̂ⱼnᵢⱼ)² / (θ̂ⱼnᵢⱼ) / (N − K).

    Proportions: φ̂ = Σⱼ Σᵢ (yᵢⱼ − θ̂ⱼnᵢⱼ)² / nᵢⱼ / [θ̄(1 − θ̄)(N − K)], the design
    effect of items clustered in cases, with the pooled θ̄ in the variance. Each
    provider's own θ̂ⱼ(1 − θ̂ⱼ) there would drop every provider at 0% or 100%, common
    at a few surveys each, and would read N/(N − K) rather than 1 on yes/no rows.

    None when no unit has a second row.
    """
    rows = rows[(rows[N] > 0) & np.isfinite(rows[Y]) & np.isfinite(rows[N])]
    theta = rows.groupby(UNIT)[Y].transform("sum") / rows.groupby(UNIT)[N].transform("sum")
    if not binomial:
        usable = theta > 0
        rows, theta = rows[usable], theta[usable]
    df = len(rows) - rows[UNIT].nunique()
    if df < 1:
        return None
    if not binomial:
        mu = theta * rows[N]
        return float(np.sum((rows[Y] - mu) ** 2 / mu) / df), df
    pooled = float(rows[Y].sum() / rows[N].sum())
    if not (0.0 < pooled < 1.0):
        return 1.0, df
    resid = (rows[Y] - theta * rows[N]) ** 2 / rows[N]
    return float(np.sum(resid) / (pooled * (1.0 - pooled) * df)), df


def _agg_phi(rows: pd.DataFrame, binomial: bool) -> tuple[float, int] | None:
    """
    _row_phi from one row per provider aggregated in SQL (cases=, sum_sq=). With
    θ̂ⱼ = Yⱼ/Nⱼ the Pearson sum over a provider's cases expands to its sufficient
    statistics, so the stays never need to leave the database:

      counts:      Σᵢ (yᵢ − θ̂nᵢ)²/(θ̂nᵢ) = Σᵢ yᵢ²/nᵢ / θ̂ − Y
      proportions: Σᵢ (yᵢ − θ̂nᵢ)²/nᵢ   = Σᵢ yᵢ²/nᵢ − θ̂·Y

    on Σkⱼ − K degrees of freedom, so it equals the case-row estimate to rounding
    (methods §4.12). None when no provider has a second case.
    """
    rows = rows[(rows[N] > 0) & np.isfinite(rows[Y]) & np.isfinite(rows[N])]
    theta = rows[Y] / rows[N]
    if not binomial:
        usable = theta > 0
        rows, theta = rows[usable], theta[usable]
    df = int(round(float(rows[CASES].sum()))) - len(rows)
    if df < 1:
        return None
    if not binomial:
        return float(np.sum(rows[SS] / theta - rows[Y]) / df), df
    pooled = float(rows[Y].sum() / rows[N].sum())
    if not (0.0 < pooled < 1.0):
        return 1.0, df
    return float(np.sum(rows[SS] - theta * rows[Y]) / (pooled * (1.0 - pooled) * df)), df


def _one_item_per_case(rows: pd.DataFrame, aggregated: bool) -> bool:
    """Every case is a single yes/no item: n = 1 per row, or cases = n per provider."""
    if not len(rows):
        return False
    if aggregated:
        return bool(np.all(rows[CASES] == rows[N]))
    return bool(np.all(rows[N] == 1))


def check_aggregated(frame: pd.DataFrame, facets) -> None:
    """cases=/sum_sq= rows must be providers: one row each, k ≥ 1, Σy²/n ≥ 0."""
    if frame.groupby([*facets, UNIT]).size().max() > 1:
        raise ValueError(
            "cases= and sum_sq= describe one provider per row, but some unit appears in "
            "several rows. Aggregate to one row per provider (per facet) in SQL, or drop "
            "cases=/sum_sq= and pass the case-level rows instead."
        )
    k = frame[CASES].to_numpy(dtype=float)
    if not (np.all(np.isfinite(k)) and np.all(k >= 1)):
        raise ValueError("cases= must be a whole number of cases >= 1 on every row.")
    ss = frame[SS].to_numpy(dtype=float)
    if not (np.all(np.isfinite(ss)) and np.all(ss >= 0)):
        raise ValueError(
            "sum_sq= must be finite and >= 0: SUM(POWER(y, 2) / n) over each provider's cases."
        )


def unit_phi(frame: pd.DataFrame, column: str) -> dict:
    """{unit: φᵢ} from a within_dispersion column (one facet's rows), validated."""
    phi = frame[PHI].to_numpy(dtype=float)
    if not (np.all(np.isfinite(phi)) and np.all(phi > 0)):
        raise ValueError(
            f"within_dispersion column {column!r} must be a positive, finite number on every "
            "row (each provider's phi_i; 1 means independent counts)."
        )
    if (frame.groupby(UNIT)[PHI].nunique() > 1).any():
        raise ValueError(
            f"within_dispersion column {column!r} varies within a provider. It is one phi_i "
            "per provider (SUM(phi_g * e) / SUM(e) over its cases); repeat that value on "
            "each row."
        )
    first = frame.groupby(UNIT, sort=False)[PHI].first()
    return {u: float(v) for u, v in first.items()}
