"""
Calibrate the fixed-center gap guard (docs/methods.md §4.2.1, §5).

A caller who fixes center= and leaves overdispersion=True lets τ̂ absorb any
system-wide gap between the providers' pooled value and that center, widening every
limit. funnel() warns when the gap is beyond chance and the spread between providers
(p < _GAP_MAX_P) and widens the limits at the median volume by at least _GAP_MIN_WIDEN.

The script draws cohorts whose system value sits a stated offset from the fixed center,
with real spread between providers (relative SD tau) and within-case clumping phi, and
reports how often the guard warns, with the median widening of the limits, for each cell
of the grid:

    K (providers)  x  volume (physician: 5-50 expected events; hospital: 50-500)
    x  tau  x  phi  x  measure (oe, rate, proportion)  x  offset

At offset 0 the warning rate is the false-warning rate (target: at most 0.5% in every
cell). The second table checks that rate under the other tau_method estimators.

    uv run python scripts/simulate_center_gap.py [--reps 500]
"""
from __future__ import annotations

import argparse
import itertools
import warnings
from multiprocessing import Pool

import numpy as np
import pandas as pd

from qikit import funnel
from qikit.core.dispersion import overdispersion, tau2_ml
from qikit.funnel import _center_gap, _Fit, _settings

KS = (20, 50, 200, 1000)
VOLUMES = {"physician": (5.0, 50.0), "hospital": (50.0, 500.0)}
TAUS = (0.0, 0.1, 0.2)
PHIS = (1.0, 2.0)
MEASURES = ("oe", "rate", "proportion")
OFFSETS = (0.0, 0.025, 0.05, 0.10)
BASE = {"oe": 1.0, "rate": 0.002, "proportion": 0.10}


def draw(rng, measure, k, volume, tau, phi, offset):
    """(y, n, center): one cohort, the system value (1 + offset) times the center."""
    center = BASE[measure]
    lo, hi = VOLUMES[volume]
    expected = np.exp(rng.uniform(np.log(lo), np.log(hi), k))   # events at the center
    z = rng.standard_normal(k)
    if measure == "proportion":
        p_sys = center * (1 + offset)
        logit = np.log(p_sys / (1 - p_sys)) + tau * z
        p = 1 / (1 + np.exp(-logit))
        cases = np.maximum(np.round(expected / center), 2.0)
        m = np.maximum(np.round(cases / phi), 1.0)                # Rao–Scott effective cases
        y = rng.binomial(m.astype(int), p) * cases / m
        return y, cases, center
    theta = center * (1 + offset) * np.exp(tau * z - tau * tau / 2)
    n = expected / center
    y = phi * rng.poisson(theta * n / phi)
    return y, n, center


def guard(y, n, measure, center, phi, method):
    """
    The guard as funnel() runs it, without the contours and columns it does not need:
    the same settings, φ scaling, τ̂ around the fixed center, and _center_gap() itself.
    check() confirms it matches funnel() on a sample of cohorts.
    """
    st = _settings(measure=measure, overdispersion=True, tau_method=method, tau=None,
                   worse=None, signal="limits", limits=(0.998, 0.95),
                   fdr_levels=(0.05, 0.10), fdr_min=None, multiply=1.0, center=center,
                   facets=None)
    n_model = n / phi
    ratio = y / n
    mask = np.ones(len(y), dtype=bool)
    family = st.family
    estimator = "winsorized" if method == "ml" else method
    disp = overdispersion(estimator, family, center, ratio, n_model, mask, True)
    tau2 = tau2_ml(center, ratio, n_model, mask, family)[0] if method == "ml" else disp.tau2
    notes: list[str] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = _Fit(family, center, ratio, n_model, mask, tau2, disp.scale)
        out = _center_gap(st, fit, "estimated", disp.scale, notes)
    return {**out, "tau": float(np.sqrt(tau2)), "notes": notes}


def check(cohorts=60, seed=7):
    """guard() agrees with funnel() exactly on oe, rate and proportion cohorts."""
    rng = np.random.default_rng(seed)
    for i in range(cohorts):
        measure = MEASURES[i % 3]
        y, n, center = draw(rng, measure, 50, "physician", 0.1, 1.0 + (i % 2), 0.05 * (i % 4))
        phi = 1.0 + (i % 2)
        a = guard(y, n, measure, center, phi, "spiegelhalter")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            b = funnel(y=y, n=n, measure=measure, center=center,
                       within_dispersion=phi).summary
        # funnel() sums providers in volume order, so agreement is to rounding.
        assert np.isclose(a["center_gap_p"], b["center_gap_p"], rtol=1e-9, atol=1e-300), i
        assert np.isclose(a["tau"], b["tau"], rtol=1e-9), i
        assert bool(a["notes"]) == any("absorbing" in x for x in b["notes"]), i


# Alternative thresholds scored from the same draws: (max p, min widening).
ALTERNATIVES = ((0.001, 1.05), (0.001, 1.10), (0.0001, 1.10))


def cell(args):
    measure, k, volume, tau, phi, offset, reps, method, seed = args
    rng = np.random.default_rng(seed)
    warned, ps, widen = 0, [], []
    for _ in range(reps):
        y, n, center = draw(rng, measure, k, volume, tau, phi, offset)
        s = guard(y, n, measure, center, phi, method)
        warned += bool(s["notes"])
        if s["tau_pooled"] is not None:
            # The guard's widening, on the natural scale (spiegelhalter/ml/winsorized).
            v = (center * (1 - center) if measure == "proportion" else center)
            v_med = v / float(np.median(n / phi))
            widen.append(np.sqrt((v_med + s["tau"] ** 2) / (v_med + s["tau_pooled"] ** 2)))
            ps.append(s["center_gap_p"])
    ps_a, widen_a = np.array(ps), np.array(widen)
    alt = {f"p<{p:g},w>={w:g}": float(np.mean((ps_a < p) & (widen_a >= w))) * len(ps) / reps
           for p, w in ALTERNATIVES}
    return {"measure": measure, "K": k, "volume": volume, "tau": tau, "phi": phi,
            "offset": offset, "method": method, "warn_rate": warned / reps,
            "median_widen": float(np.median(widen)) if widen else np.nan, **alt}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=500)
    reps = ap.parse_args().reps
    check()
    grid = list(itertools.product(MEASURES, KS, VOLUMES, TAUS, PHIS, OFFSETS))
    jobs = [(*g, reps, "spiegelhalter", 1000 + i) for i, g in enumerate(grid)]
    others = [(m, k, v, t, 1.0, 0.0, max(reps // 2, 50), meth, 9000 + i)
              for i, (m, k, v, t, meth) in enumerate(itertools.product(
                  MEASURES, KS, VOLUMES, (0.0, 0.2), ("winsorized", "ml")))]
    with Pool() as pool:
        main_rows = pool.map(cell, jobs, chunksize=4)
        other_rows = pool.map(cell, others, chunksize=4)
    df = pd.DataFrame(main_rows)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_rows", 500)

    print(f"Fixed-center gap guard, {reps} cohorts per cell (tau_method='spiegelhalter')\n")
    null = df[df.offset == 0]
    print("False warnings at offset 0: max over cells "
          f"{null.warn_rate.max():.3%}, mean {null.warn_rate.mean():.3%}")
    print(null.sort_values("warn_rate", ascending=False).head(8).to_string(index=False))

    print("\nWarning rate by offset (rows: K x volume; columns: offset), "
          "averaged over tau, phi, measure")
    print(df.pivot_table(index=["volume", "K"], columns="offset", values="warn_rate",
                         aggfunc="mean").round(3).to_string())
    print("\nMedian widening of the limits at the median volume, by offset")
    print(df.pivot_table(index=["volume", "K"], columns="offset", values="median_widen",
                         aggfunc="median").round(3).to_string())
    print("\nWarning rate at 5% and 10% offset, by tau and phi (all K, volumes, measures)")
    print(df[df.offset >= 0.05].pivot_table(index=["volume", "tau", "phi"],
                                            columns="offset", values="warn_rate",
                                            aggfunc="mean").round(3).to_string())

    alts = [c for c in df.columns if c.startswith("p<")]
    print("\nAlternative thresholds: max false-warning rate at offset 0, and mean warning "
          "rate at 5% and 10% (hospital volumes)")
    hosp = df[df.volume == "hospital"]
    print(pd.DataFrame({
        "max false (all cells)": df[df.offset == 0][alts].max(),
        "hospital 5%": hosp[hosp.offset == 0.05][alts].mean(),
        "hospital 10%": hosp[hosp.offset == 0.10][alts].mean(),
    }).round(4).to_string())

    od = pd.DataFrame(other_rows)
    print("\nFalse warnings at offset 0 under the other estimators (phi = 1)")
    print(od.pivot_table(index=["volume", "K"], columns=["method", "tau"], values="warn_rate",
                         aggfunc="max").round(3).to_string())


if __name__ == "__main__":
    main()
