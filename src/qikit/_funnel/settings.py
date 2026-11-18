"""
_funnel/settings.py — the validated settings a funnel runs with (_Settings), and one
facet's fitted model (_Fit).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ..core.dispersion import TAU_METHODS, transform_scale
from ..validate import (
    WORSE,
    check_choice,
    check_facet_names,
    check_levels,
    check_number,
    split_facets,
)
from .constants import _COLUMNS, _LIMIT_METHODS, _SIDES, BENCHMARKS, COMPARE_TO, MEASURES, SIGNALS


@dataclass(frozen=True)
class _Settings:
    measure: str
    overdispersion: bool
    tau_method: str
    tau_fixed: Any                 # τ² fixed in advance: a number, a dict per facet, or None
    tau: Any                       # tau= as the caller passed it, for the summary
    worse: str | None
    signal: str
    limits: tuple[float, float]
    fdr_levels: tuple[float, float]
    fdr_min: float | None
    multiply: float
    center: float | None
    facets: tuple[str, ...]
    benchmark: str | None = None
    benchmark_share: float = 0.10
    hover: tuple[str, ...] = ()
    limit_method: str = "exact"
    compare_to: str | None = None   # as the caller passed it
    interval: float = 0.95          # coverage of eb_low / eb_high

    @property
    def question(self) -> str:
        """Which question the settings answer: "peers", "model" or "custom"."""
        if self.center is None and self.overdispersion:
            return "peers"
        if self.measure == "oe" and self.center == 1.0 and not self.overdispersion:
            return "model"
        return "custom"

    @property
    def center_user_fixed(self) -> bool:
        """A center line the caller fixed, other than through compare_to="model"."""
        return self.center is not None and self.compare_to != "model"

    @property
    def family(self) -> str:
        return "binomial" if self.measure == "proportion" else "poisson"

    @property
    def side(self) -> str:
        return _SIDES[self.worse]


def _settings(*, measure, overdispersion, tau_method, tau, worse, signal, limits,
              fdr_levels, fdr_min, multiply, center, facets, benchmark=None,
              benchmark_share=0.10, limit_method="exact", compare_to=None,
              interval=0.95) -> _Settings:
    measure = check_choice("measure", measure, MEASURES)
    compare_to = check_choice("compare_to", compare_to, COMPARE_TO)
    center, overdispersion = _compare_to(compare_to, measure, center, overdispersion)
    worse = check_choice("worse", worse, WORSE)
    signal = check_choice("signal", signal, SIGNALS)
    tau_method = check_choice("tau_method", tau_method, TAU_METHODS)
    limit_method = check_choice("limit_method", limit_method, _LIMIT_METHODS)
    benchmark = check_choice("benchmark", benchmark, BENCHMARKS)
    if benchmark is not None and worse is None:
        raise ValueError(
            f"benchmark={benchmark!r} needs worse='higher' or 'lower': the benchmark is what "
            "the best providers achieve, so it needs to know which direction is better."
        )
    if not check_number("benchmark_share", benchmark_share, 0.0, strict=True) < 1.0:
        raise ValueError(f"benchmark_share is a share strictly between 0 and 1, got {benchmark_share!r}.")
    if tau_method == "shmi" and measure == "proportion":
        transform_scale("shmi", "binomial")  # raises with the fix
    check_number("multiply", multiply, 0.0, strict=True)
    if fdr_min is not None:
        check_number("fdr_min_denominator", fdr_min)
    if not check_number("interval", interval, 0.0, strict=True) < 1.0:
        raise ValueError(f"interval is a coverage strictly between 0 and 1, e.g. 0.95; got {interval!r}.")
    if center is not None:
        check_number("center", center, 0.0, strict=True)
        if measure == "proportion" and not center < 1.0:
            raise ValueError(f"center= on a proportion lies strictly between 0 and 1, got {center!r}.")
    check_facet_names(split_facets(facets), _COLUMNS, "funnel")
    return _Settings(
        measure=measure, overdispersion=bool(overdispersion), tau_method=tau_method,
        tau_fixed=_tau_fixed(tau, facets, overdispersion,
                             model=measure == "oe" and center == 1.0 and not overdispersion),
        tau=tau, worse=worse,
        signal=signal, limits=check_levels("limits", limits, outer_wider=True),
        fdr_levels=check_levels("fdr_levels", fdr_levels, outer_wider=False),
        fdr_min=fdr_min, multiply=float(multiply),
        center=None if center is None else float(center),
        facets=tuple(split_facets(facets)), benchmark=benchmark,
        benchmark_share=float(benchmark_share), limit_method=limit_method,
        compare_to=compare_to, interval=float(interval),
    )


def _compare_to(compare_to, measure, center, overdispersion) -> tuple[Any, bool]:
    """
    (center, overdispersion) resolved from compare_to=. Settings that agree with it may be
    passed too; one that contradicts it is an error naming the fix (methods §2, §4.2).
    """
    if compare_to is None:
        return center, True if overdispersion is None else bool(overdispersion)
    if compare_to == "peers":
        if center is not None:
            raise ValueError(
                f"compare_to='peers' judges each provider against the pooled value of its "
                f"peers, so it cannot take center={center!r}. Drop center=, or drop "
                f"compare_to= to keep a fixed center line."
            )
        if overdispersion is False:
            raise ValueError(
                "compare_to='peers' allows for the spread between providers "
                "(overdispersion=True). Drop overdispersion=False, or drop compare_to= for "
                "an unadjusted chart around the pooled center."
            )
        return None, True
    if measure != "oe":
        raise ValueError(
            f"compare_to='model' compares observed with a risk model's expected (O/E against "
            f"1.0); measure={measure!r} has no model value. For a fixed target pass "
            f"center=<target> and overdispersion=False instead."
        )
    if center is not None and center != 1.0:
        raise ValueError(
            f"compare_to='model' sets center=1.0 (observed equals expected), so it cannot "
            f"take center={center!r}. Drop center=, or drop compare_to= to use that center."
        )
    if overdispersion is True:
        raise ValueError(
            "compare_to='model' asks whether each provider differs from the risk model, so "
            "it allows no spread between providers (overdispersion=False). Drop "
            "overdispersion=True, or use compare_to='peers' to ask whether a provider is "
            "unusual among its peers."
        )
    return 1.0, False


def _tau_fixed(tau: Any, facets: Any, overdispersion: bool, model: bool = False) -> Any:
    """
    tau= as τ² (a number, or a dict of τ² per facet), validated. Against the risk model
    (model=True) it sets only the spread the shrunk estimates use (methods §4.14).
    """
    if tau is None:
        return None
    if not overdispersion and not model:
        raise ValueError(
            "tau= needs overdispersion=True: it is the spread the adjusted chart judges "
            "providers against, and the unadjusted chart has none. (Against the risk "
            "model, compare_to='model', it sets the spread of the shrunk estimates.)"
        )
    if isinstance(tau, dict):
        if not split_facets(facets):
            raise ValueError("tau= as a dict (one value per facet) needs facets=.")
        return {fv: check_number(f"tau=[{fv!r}]", v) ** 2 for fv, v in tau.items()}
    return check_number("tau=", tau) ** 2


@dataclass(frozen=True)
class _Fit:
    """One facet's fitted model: what every step after the limits reads."""
    family: str            # "poisson" or "binomial"
    cl: float              # the center line θ₀
    ratio: np.ndarray      # each provider's value, numerator / denominator
    n_model: np.ndarray    # the denominator the model sees (÷ φ)
    mask: np.ndarray       # providers in the model (not excluded)
    tau2: float            # the spread the limits allow for (0 without the allowance)
    scale: str             # the scale that τ² is on
