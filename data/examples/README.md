# QIKit Demonstration Datasets

This folder contains public domain healthcare datasets ideal for demonstrating Statistical Process Control (SPC) charting.

## Available Datasets

### 1. Hospital-Acquired Infections (`cms_hospital_infections_sample.csv`)
* **Source:** Centers for Medicare & Medicaid Services (CMS) Provider Data Catalog (public domain)
* **URL:** [Healthcare Associated Infections - Hospital](https://data.cms.gov/provider-data/topics/hospitals) (dataset `77hc-ibv8`)
* **Description:** A 100-row sample (25 California hospitals, reporting period 2024-07-01 to 2025-06-30) in the original CMS long format. For each hospital it includes CLABSI and CAUTI observed cases (`HAI_1_NUMERATOR`, `HAI_2_NUMERATOR`) and the matching device-day denominators (`HAI_1_DOPC`, `HAI_2_DOPC`). Pivot numerator/denominator pairs per hospital to demo **funnel plots** (cross-sectional infection rates with varying exposure).

### 2. Hospital Readmissions (`hospital_readmissions.csv`)
* **Source:** Synthetic Data (Modeled after standard CMS Readmission Reduction Program metrics)
* **Description:** Monthly 30-day readmission data for a hospital. Includes the total number of discharges and the number of readmissions.

### 3. Emergency Department Wait Times (`ed_wait_times.csv`)
* **Source:** Synthetic Data (Modeled after NHS A&E Attendance parameters)
* **Description:** Daily average wait times (in minutes) for an Emergency Department over a 60-day period.

### 4. CAUTI Infections (`cauti_infections.csv`)
* **Source:** Synthetic Data (Modeled after CDC National Healthcare Safety Network parameters)
* **Description:** Monthly data tracking Catheter-Associated Urinary Tract Infections (CAUTI). Includes the number of cases and the total catheter days (exposure time).

### 5. Physician Mortality O/E (`physician_mortality_oe.csv`)
* **Source:** Synthetic Data (modeled after Vizient-style risk-adjusted mortality reporting)
* **Description:** 24 surgeons × 3 years (2023–2025), with observed deaths and model-derived
  expected deaths per surgeon-year. Built for the **risk-adjusted O/E funnel**
  (`chart="oe"`) and specifically to demonstrate why physician-level comparison needs
  aggregation: **no surgeon flags in any single year** — all three annual funnels report
  `summary["underpowered"] == True` — but summing the three years makes the chart
  well-powered and surfaces three real signals, including one high performer flagging
  *below* the lower limit. `SURG-07` is the credentialing trap: consistently ~2.2×
  expected mortality on ~5 expected deaths a year, invisible annually.

```python
import pandas as pd
from qikit import qic

df = pd.read_csv("data/examples/physician_mortality_oe.csv")

# One year: nothing flags, and the summary says why.
y2025 = df[df.year == 2025]
qic(x="physician", y="observed_deaths", n="expected_deaths", data=y2025,
    chart="oe", funnel=True).summary["power_note"]

# Three years pooled: the chart now has the resolution to find them.
agg = df.groupby("physician", as_index=False)[["observed_deaths", "expected_deaths"]].sum()
qic(x="physician", y="observed_deaths", n="expected_deaths", data=agg,
    chart="oe", funnel=True).plot()
```
