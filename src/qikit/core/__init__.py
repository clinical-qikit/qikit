"""
qikit.core — the numbers, with no pandas and no plotting.

    shewhart.py    centre lines and control limits for time-ordered charts
    rules.py       run, trend and zone rules (anhoej, ihi, nhs, weco, nelson)
    contours.py    a funnel's probability contours at any denominator
    dispersion.py  the spread between providers (φ̂, τ̂²) by each tau_method
    pvalues.py     each provider's p-value against the contours' own model, and BH
    power.py       detectability and each provider's own exact interval
    dist.py        exact quantiles and tails, built from term ratios (no scipy)
    constants.py   SPC constants (c4, A3, B3, B4, d2, D4) and normal deviates

Every function takes and returns arrays or numbers. dist.py, contours.py, pvalues.py and
power.py have line-for-line twins in the TypeScript engine (excel-addin/packages/engine),
so the two agree to the bit; docs/methods.md and docs/qic-methods.md record each method.
"""
