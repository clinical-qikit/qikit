"""
Coverage of the shrunk-estimate intervals eb_low / eb_high (docs/methods.md §4.14, §5).

Each provider's true value is drawn from the chart's own mixture distribution (mean
center, SD tau): gamma for O/E counts, beta for proportions. Then each provider's data
is drawn given its true value. Coverage is the share of (provider, cohort) pairs whose
true value lies inside [eb_low, eb_high], with tau passed as known (tau=) and with tau
estimated (the default: maximum likelihood around the center line, methods §4.14). It is reported overall and by volume
tercile, together with the median interval width and how often estimate_flag says
"worse".

    O/E counts      K = 200, expected events 5-100 (log-uniform), Poisson counts
    proportions     K = 200, cases 50-1000, base rate 13%, binomial counts
    O/E LOS days    K = 100, 20-200 stays each, gamma expected days, lognormal noise
                    (phi near 2), within_dispersion="estimate"

    uv run python scripts/simulate_eb_intervals.py [--reps 200]
"""
from __future__ import annotations

import argparse
import itertools
import warnings
from multiprocessing import Pool

import numpy as np
import pandas as pd

from qikit import funnel

TAUS = (0.1, 0.2, 0.3)          # relative SD of the true values around the center
# "estimated": the default, the ML τ̂ the estimate columns use whatever the chart's
# tau_method; "known": tau= passed as the true value.
METHODS = ("known", "estimated")


def cohort(rng, scenario, tau):
    """(data, funnel kwargs, true values per unit, volume per unit)."""
    if scenario == "oe":
        k = 200
        e = np.exp(rng.uniform(np.log(5), np.log(100), k))
        theta = rng.gamma(1 / tau ** 2, tau ** 2, k)                  # mean 1, SD tau
        o = rng.poisson(theta * e)
        df = pd.DataFrame({"u": np.arange(k), "o": o, "e": e})
        return df, dict(y="o", n="e", measure="oe", unit="u"), theta, e, tau
    if scenario == "proportion":
        k, p0 = 200, 0.13
        sd = p0 * tau
        s = p0 * (1 - p0) / sd ** 2 - 1
        theta = rng.beta(p0 * s, (1 - p0) * s, k)
        n = np.round(np.exp(rng.uniform(np.log(50), np.log(1000), k)))
        y = rng.binomial(n.astype(int), theta)
        df = pd.DataFrame({"u": np.arange(k), "y": y, "n": n})
        return df, dict(y="y", n="n", measure="proportion", unit="u"), theta, n, sd
    k = 100
    theta = rng.gamma(1 / tau ** 2, tau ** 2, k)
    sizes = rng.integers(20, 200, k)
    unit = np.repeat(np.arange(k), sizes)
    e = rng.gamma(2.0, 2.0, len(unit))
    sigma = 0.6
    obs = e * theta[unit] * rng.lognormal(-sigma ** 2 / 2, sigma, len(unit))
    df = pd.DataFrame({"u": unit, "o": obs, "e": e})
    vol = df.groupby("u")["e"].sum().to_numpy()
    return (df, dict(y="o", n="e", measure="oe", unit="u", within_dispersion="estimate"),
            theta, vol, tau)


def cell(args):
    scenario, tau, method, reps, seed = args
    rng = np.random.default_rng(seed)
    hit, width, worse, vol_all, hit_all = [], [], [], [], []
    unavailable = 0
    for _ in range(reps):
        df, kw, theta, vol, tau_nat = cohort(rng, scenario, tau)
        if method == "known":
            kw = {**kw, "tau": tau_nat}

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            r = funnel(df, **kw)
        d = r.data.set_index("unit").loc[np.arange(len(theta))]
        lo, hi = d["eb_low"].to_numpy(), d["eb_high"].to_numpy()
        if not np.isfinite(lo).any():
            unavailable += 1
            continue
        inside = (theta >= lo) & (theta <= hi)
        hit.append(inside.mean())
        width.append(np.median(hi - lo))
        worse.append((d["estimate_flag"] != "no different").mean())
        vol_all.append(vol)
        hit_all.append(inside)
    if not hit:
        return {"scenario": scenario, "tau": tau, "tau_from": method, "coverage": np.nan,
                "low_vol": np.nan, "mid_vol": np.nan, "high_vol": np.nan,
                "median_width": np.nan, "flagged": np.nan, "no_interval": 1.0}
    vol_all, hit_all = np.concatenate(vol_all), np.concatenate(hit_all)
    terciles = np.quantile(vol_all, [1 / 3, 2 / 3])
    band = np.digitize(vol_all, terciles)
    return {
        "scenario": scenario, "tau": tau, "tau_from": method,
        "coverage": float(np.mean(hit)),
        "low_vol": float(hit_all[band == 0].mean()),
        "mid_vol": float(hit_all[band == 1].mean()),
        "high_vol": float(hit_all[band == 2].mean()),
        "median_width": float(np.median(width)),
        "flagged": float(np.mean(worse)),   # share with an interval clear of the center
        "no_interval": unavailable / reps,
    }


def two_questions(reps=10, k=500, seed=77):
    """
    methods §4.16: the share of providers flagged by signal (one-sided 95%: alert or
    outlier, worse="higher"), by prob_worse > 0.975, and truly more than 20% above
    average, as the true spread grows. K = 500, E ~ U(3, 30).
    """
    rng = np.random.default_rng(seed)
    rows = []
    for tau in (0.0, 0.15, 0.30):
        sig, pw, ew, truly = [], [], [], []
        for _ in range(reps):
            e = rng.uniform(3, 30, k)
            theta = rng.gamma(1 / tau ** 2, tau ** 2, k) if tau > 0 else np.ones(k)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                d = funnel(y=rng.poisson(theta * e), n=e, measure="oe",
                           worse="higher").data.sort_index()
            sig.append((d["signal"] != "none").mean())
            pw.append((d["prob_worse"] > 0.975).mean())
            ew.append((d["estimate_flag"] == "worse").mean())
            truly.append((theta > 1.2).mean())
        rows.append({"true tau": tau, "signal": np.mean(sig), "prob_worse > 0.975": np.mean(pw),
                     "estimate_flag worse": np.mean(ew), "truly > 1.2": np.mean(truly)})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=200)
    reps = ap.parse_args().reps
    jobs = []
    for i, (sc, tau, meth) in enumerate(itertools.product(
            ("oe", "proportion", "oe_los"), TAUS, METHODS)):
        n = reps if sc != "oe_los" else max(reps // 4, 20)
        jobs.append((sc, tau, meth, n, 500 + i))
    with Pool() as pool:
        rows = pool.map(cell, jobs)
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    print(f"Coverage of the 95% eb_low/eb_high interval ({reps} cohorts; LOS {max(reps // 4, 20)})")
    print(df.round(3).to_string(index=False))
    print("\nTwo questions (methods §4.16): share of providers flagged, 10 cohorts of K = 500")
    print(two_questions().round(3).to_string(index=False))


if __name__ == "__main__":
    main()
