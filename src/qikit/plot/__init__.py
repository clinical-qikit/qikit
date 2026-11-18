"""
qikit.plot — Plotly figures for qikit's results. Imported only when .plot() is called,
so the analysis itself never needs plotly (as in a Snowpark UDTF).

    charts.py       SPCResult and FunnelResult → a Drawing (plot_spc, plot_funnel)
    drawing.py      the Drawing, plot() options, styles= and point roles
    render.py       one renderer for every Drawing: points, lines, labels, tooltips
    layout.py       axes, ranges, legend, captions
    caterpillar.py  shrunk estimates with their intervals
    pareto.py       Pareto and Bernoulli CUSUM
    doe.py          design-of-experiments figures
    options.py      styles= roles and display-option checks
    theme.py        palette and Tufte theme
"""
