# qikit in Snowflake

qikit's analysis needs only numpy and pandas, which every Snowflake Python runtime
provides. `import qikit` does not load plotly, so a stored procedure or UDTF can compute
limits without the plotting extra. Streamlit in Snowflake adds plotly for `.plot()`.

The pattern everywhere is the same: one call, `.data` out.

```python
from qikit import qic, funnel

qic(df, x="MONTH", y="NUM", n="DEN", chart="p", facets=["MEASURE", "SERVICE"]).data
funnel(df, y="OBS", n="EXP", measure="oe", unit="NPI", facets="MEASURE").data
```

`facets=` takes one column or a list. Each combination gets its own center line,
limits, τ and FDR step, and the facet columns lead the output, so the result joins back
to the source table on them.

## 1. Getting the package into Snowflake

qikit is pure Python, so either route works.

**From PyPI, through the artifact repository.** Where your account has Snowflake's
shared PyPI repository enabled:

```sql
CREATE OR REPLACE PROCEDURE ...
  ARTIFACT_REPOSITORY = snowflake.snowpark.pypi_shared_repository
  PACKAGES = ('snowflake-snowpark-python', 'clinical-qikit')
  ...
```

**From a stage.** Build or download the wheel and upload it once:

```bash
uv build --wheel                      # dist/clinical_qikit-1.1.0-py3-none-any.whl
```

```sql
CREATE STAGE IF NOT EXISTS QI.PUBLIC.PY_LIBS;
PUT file://dist/clinical_qikit-1.1.0-py3-none-any.whl @QI.PUBLIC.PY_LIBS
  AUTO_COMPRESS = FALSE OVERWRITE = TRUE;
```

Then list it in `IMPORTS` and keep `numpy` and `pandas` in `PACKAGES`. A pure-Python
wheel is a zip archive, which Python imports from directly.

## 2. Stored procedure: add limits to a metrics table

The simplest deployment. The procedure reads a pre-aggregated table, computes every
chart in one faceted call, and writes the limits back.

```sql
CREATE OR REPLACE PROCEDURE QI.PUBLIC.ADD_SPC_LIMITS(SOURCE STRING, TARGET STRING)
  RETURNS STRING
  LANGUAGE PYTHON
  RUNTIME_VERSION = '3.11'
  PACKAGES = ('snowflake-snowpark-python', 'numpy', 'pandas')
  IMPORTS = ('@QI.PUBLIC.PY_LIBS/clinical_qikit-1.1.0-py3-none-any.whl')
  HANDLER = 'run'
AS
$$
from qikit import qic

def run(session, source, target):
    df = session.table(source).to_pandas()           # MEASURE, SERVICE, MONTH, NUM, DEN
    out = qic(df, x="MONTH", y="NUM", n="DEN", chart="p",
              facets=["MEASURE", "SERVICE"]).data
    out.columns = [c.upper() for c in out.columns]
    session.write_pandas(out, target, auto_create_table=True, overwrite=True)
    return f"{len(out)} rows written to {target}"
$$;

CALL QI.PUBLIC.ADD_SPC_LIMITS('QI.METRICS.MONTHLY', 'QI.METRICS.MONTHLY_LIMITS');
```

The same body with `funnel()` writes one row per provider per measure: limits, `signal`,
`p_value`, `q_value`, `min_detectable` and the shrinkage columns.

```python
out = funnel(df, y="OBS", n="EXP", measure="oe", unit="NPI", label="PROVIDER_NAME",
             facets="MEASURE", worse="higher").data
```

A faceted call is the same as one call per partition: `tests/test_public_api.py`
checks that row for row.

## 3. UDTF: limits inside a SQL pipeline

When the limits belong in a SQL statement rather than a separate table, a vectorized
UDTF runs `qic()` once per partition. Each partition is one chart.

```sql
CREATE OR REPLACE FUNCTION QI.PUBLIC.QIC_P(MONTH DATE, NUM FLOAT, DEN FLOAT)
  RETURNS TABLE (MONTH DATE, Y FLOAT, CL FLOAT, UCL FLOAT, LCL FLOAT,
                 SIGNAL STRING, RUNS_SIGNAL BOOLEAN)
  LANGUAGE PYTHON
  RUNTIME_VERSION = '3.11'
  PACKAGES = ('numpy', 'pandas')
  IMPORTS = ('@QI.PUBLIC.PY_LIBS/clinical_qikit-1.1.0-py3-none-any.whl')
  HANDLER = 'QicP'
AS
$$
import pandas as pd
from _snowflake import vectorized
from qikit import qic

class QicP:
    @vectorized(input=pd.DataFrame)
    def end_partition(self, df):
        df.columns = ["MONTH", "NUM", "DEN"]
        d = qic(df, x="MONTH", y="NUM", n="DEN", chart="p").data
        return d[["x", "y", "cl", "ucl", "lcl", "signal", "runs_signal"]]
$$;

SELECT m.MEASURE, m.SERVICE, l.*
FROM QI.METRICS.MONTHLY m,
     TABLE(QI.PUBLIC.QIC_P(m.MONTH, m.NUM, m.DEN)
           OVER (PARTITION BY m.MEASURE, m.SERVICE ORDER BY m.MONTH)) l;
```

**Keep the returned columns fixed.** `RETURNS TABLE` needs a stable schema, and some of
`.data`'s columns appear only with the option that makes them (`part` with `part=`,
`variation` with `method="nhs"`, `target` with `target=`). Select the columns the UDTF
declares, as above.

**Rows come back one per subgroup.** `qic()` aggregates rows that share an `x`, so a
partition with two rows for one month returns one. Aggregate in SQL first if the
pipeline expects one output row per input row.

## 4. Choosing settings in a pipeline

- **Charts by measure type.** Proportions (`chart="p"`) and O/E or rates (`chart="u"`)
  need different calls. Run one call per chart type, faceted by measure.
- **Rules.** `method="anhoej"` (the default) for run charts and general use;
  `method="nhs"` with `chart="i"` and `worse=` where boards use Making Data Count.
  `.data` then carries `variation` and `special_cause` per point, and the summary
  carries the assurance verdict when `target=` is given.
- **Baselines.** A pipeline that recomputes monthly should fix the baseline with
  `freeze=`, so new points are judged against limits that do not move with them.
- **Funnels.** `tau_method="spiegelhalter"` is the default and the right screen.
  `funnel_sensitivity()` returns one row per provider with the tier under each τ
  option; writing it alongside the funnel shows which flags depend on the model.

## 5. Performance

| Case | Time |
|---|---|
| `qic()` p chart, 104 points | about 1 ms |
| 200 charts of 36 points, one faceted call | about 0.15 s |
| O/E funnel, 5,000 providers | about 0.2 s |
| Proportion funnel, 5,000 providers | about 1 s |

These are laptop timings; a Snowflake warehouse is in the same range. A faceted call
runs the facets one after another, so a very large pipeline gains from the UDTF's
parallel partitions.

## 6. Streamlit in Snowflake

Streamlit apps keep using `.plot()`, which returns a Plotly figure:

```python
st.plotly_chart(qic(df, x="MONTH", y="NUM", n="DEN", chart="p").plot(title="H&P in 24 h"),
                use_container_width=True)
```

The app needs `plotly` as well as qikit. On the warehouse runtime, add `plotly` to the
app's packages and place the `qikit` package folder (from the wheel or `src/qikit`)
next to the app's main file in its stage. On the container runtime, add
`clinical-qikit[plot]` to `requirements.txt`.

**Upgrading an app to 1.0.** Display options moved from `qic()` and `funnel()` to
`.plot()`, and a few arguments were renamed. Every removed or renamed argument raises a
`TypeError` that names its replacement, so running the app once lists every change to
make. The CHANGELOG has the full table.
