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
