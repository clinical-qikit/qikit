"""
Reproduce the simulation tables in docs/methods.md, section 5.

1. Between-provider spread. For counts (oe vs oep) and proportions (p vs pp funnels),
   draw cohorts whose true provider effects spread with relative SD tau, plant one
   genuine outlier, and report how often each chart flags an in-distribution provider
   above its 99.8% limit (nominal 0.1%) and how often it catches the outlier. Also
   checks that the adjusted limits equal the unadjusted ones whenever tau-hat is 0.
2. Clustered counts. Length of stay as observed/expected days, from stay-level gamma
   draws with no true provider effect: flag rates without and with within_dispersion.
3. The dispersion-shape diagnostic: how often it warns, by scenario and K.

    uv run python scripts/simulate_funnel_dispersion.py
"""
import warnings

import numpy as np
import pandas as pd

from qikit import funnel
from qikit.spc.compute import compute
from qikit.spc.limits import dispersion_shape

rng = np.random.default_rng(2026)


def run(family, k, tau, reps, lo, hi):
    plain, adj = ("oe", "oep") if family == "counts" else ("p", "pp")
    res = {plain: [0, 0], adj: [0, 0]}
    taus, same = [], 0
    for _ in range(reps):
        n = rng.uniform(lo, hi, k)
        if family == "counts":
            th = rng.gamma(1 / tau**2, tau**2, k) if tau > 0 else np.ones(k)
            th[-1], n[-1] = 2.5, 15.0
            y = rng.poisson(th * n).astype(float)
        else:
            n, base = np.round(n), 0.12
            if tau > 0:
                s = base * (1 - base) / (tau * base) ** 2 - 1
                th = rng.beta(base * s, (1 - base) * s, k)
            else:
                th = np.full(k, base)
            th[-1], n[-1] = 2.5 * base, 120.0
            y = rng.binomial(n.astype(int), th).astype(float)
        ratio = y / n
        rp = compute(plain, ratio, n, funnel=True)
        ra = compute(adj, ratio, n, funnel=True)
        taus.append(ra["summary"]["dispersion_tau"])
        if taus[-1] == 0:
            same += np.array_equal(rp["ucl"], ra["ucl"])
        for name, r in ((plain, rp), (adj, ra)):
            flagged = ratio > r["ucl"]
            res[name][0] += flagged[:-1].sum()
            res[name][1] += flagged[-1]
    cells = " | ".join(
        f"{c}: in-dist {v[0] / (reps * (k - 1)):.2%}, outlier {v[1] / reps:.0%}"
        for c, v in res.items()
    )
    zero = sum(t == 0 for t in taus)
    print(
        f"{family:6s} K={k:<3d} tau={tau:<4} | {cells} | tau-hat median "
        f"{np.median(taus):.3f} (IQR {np.percentile(taus, 25):.3f}-"
        f"{np.percentile(taus, 75):.3f}) | identical when tau-hat=0: {same}/{zero}"
    )


def los_stays(k, phi, tau=0.0, mean_stays=60):
    """Stay-level days: gamma per stay with mean 5 and variance-to-mean phi."""
    shape = 5.0 / phi
    frames = []
    for j in range(k):
        m = max(5, int(rng.lognormal(np.log(mean_stays), 0.9)))
        effect = float(np.exp(tau * rng.standard_normal())) if tau else 1.0
        days = rng.gamma(shape, 5.0 * effect / shape, m).round()
        frames.append(pd.DataFrame({"unit": j, "los": days, "exp": 5.0}))
    return pd.concat(frames, ignore_index=True)


def run_los(k, phi, reps):
    """Share of providers flagged (one-sided, worse = higher), with no true effect."""
    rows = {"no within_dispersion": [0, 0], "within_dispersion='estimate'": [0, 0]}
    phis = []
    for _ in range(reps):
        stays = los_stays(k, phi)
        args = dict(y="los", n="exp", measure="oe", unit="unit", worse="higher")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            naive = funnel(stays, **args).summary
        fixed = funnel(stays, within_dispersion="estimate", **args).summary
        phis.append(fixed["within_dispersion"])
        for name, summ in (("no within_dispersion", naive), ("within_dispersion='estimate'", fixed)):
            rows[name][0] += summ["n_outlier"]
            rows[name][1] += summ["n_alert"]
    for name, (out, alert) in rows.items():
        print(f"LOS K={k} phi={phi:<3} {name:30s} outlier {out / (reps * k):.2%} "
              f"(nominal 0.10%), alert {alert / (reps * k):.2%} (nominal 2.40%)")
    print(f"LOS K={k} phi={phi:<3} phi-hat median {np.median(phis):.2f}")


def shape_rate(kind, k, reps):
    """How often dispersion_shape calls clumping 'within' or 'both' (a warning)."""
    fired = 0
    for _ in range(reps):
        if kind.startswith("los"):
            phi = float(kind.split("=")[1])
            agg = los_stays(k, phi).groupby("unit")[["los", "exp"]].sum()
            y, n = agg["los"].to_numpy(), agg["exp"].to_numpy()
        else:
            n = rng.lognormal(np.log(40), 0.9, k)
            if kind == "binary":
                cases = np.maximum(1, np.round(n / 0.15)).astype(int)
                y, n = rng.binomial(cases, 0.15).astype(float), cases * 0.15
            else:
                theta = np.exp(0.5 * rng.standard_normal(k)) if kind == "between" else 1.0
                y = rng.poisson(theta * n).astype(float)
        cl = y.sum() / n.sum()
        shape = dispersion_shape(cl, y / n, n, np.ones(k, dtype=bool), "poisson")
        fired += shape.get("dispersion_shape") in ("within", "both")
    return fired / reps


if __name__ == "__main__":
    for fam, lo, hi in (("counts", 3, 30), ("props", 20, 200)):
        for k in (30, 150):
            for tau in (0.0, 0.15, 0.3):
                run(fam, k, tau, 300, lo, hi)
    print()
    for phi in (3.0, 8.0):
        run_los(500, phi, 20)
    print()
    for kind in ("poisson", "between", "binary", "los phi=3", "los phi=8"):
        rates = {k: shape_rate(kind, k, 100 if k < 1000 else 20) for k in (40, 200, 1000)}
        print(f"shape warns: {kind:10s} " + "  ".join(f"K={k}: {r:.0%}" for k, r in rates.items()))
