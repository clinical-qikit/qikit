"""
The machinery behind qikit.funnel: funnel(), funnel_sensitivity() and funnel_rollup()
live in funnel.py with their documentation; everything they call is here, one concern
per module.

    constants   choices, defaults and internal column names
    inputs      arguments to one normalized frame (_normalize, mean-measure inputs)
    settings    validated settings (_Settings, _settings) and a facet's fit (_Fit)
    pipeline    every facet's funnel: limits, p-values, signals (_funnel, _one_funnel)
    summary     center-gap guard, benchmarks, expected false flags, shape, power, notes
    estimates   shrunk estimates and single-case robustness
"""
