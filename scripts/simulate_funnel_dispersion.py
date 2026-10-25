"""
Reproduce the simulation table in docs/methods.md, section 5.

For counts (oe vs oep) and proportions (p vs pp funnels), draw cohorts whose true
provider effects spread with relative SD tau, plant one genuine outlier, and report how
often each chart flags an in-distribution provider above its 99.8% limit (nominal 0.1%)
and how often it catches the outlier. Also checks that the adjusted limits equal the
unadjusted ones whenever tau-hat comes out 0.

    uv run python scripts/simulate_funnel_dispersion.py
"""
import numpy as np

from qikit.spc.compute import compute

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


if __name__ == "__main__":
    for fam, lo, hi in (("counts", 3, 30), ("props", 20, 200)):
        for k in (30, 150):
            for tau in (0.0, 0.15, 0.3):
                run(fam, k, tau, 300, lo, hi)
