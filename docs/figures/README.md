# Public result charts

These two images let readers see the main findings without installing the
project or obtaining the source data. They were generated on **2026-10-24**
from the existing study database, without refreshing Zillow or Census data.
They support **Housing Values and Commuting Patterns Across Three Cities**:
the first compares the combined and within-city patterns; the second checks
predictions for a city left out of training. The adjusted models are explained
separately in the root README.

**Data Provided by Zillow Group** — [Zillow Research ZHVI](https://www.zillow.com/research/data/).
Commuting and other estimates: [U.S. Census Bureau ACS](https://www.census.gov/programs-surveys/acs).
This is an independent analysis, with no Zillow affiliation or endorsement.

## Data and interpretation

- Housing values: Zillow ZIP-level ZHVI, **2025-03-31** observation.
- Commuting and controls: **2022 ACS five-year estimates**. The housing and ACS
   periods differ. The charts compare places using one set of estimates, not
   changes over time.
- Sample: **248 observations**—Chicago 55, New York City 171, Washington, DC 22.
  Of the 250 source records, `10037` and `60602` are excluded because ACS median
   home value is unavailable. The shared rule requiring all needed estimates is
   unchanged; this missing ACS measure is separate from Zillow's ZHVI.
- The proxy weights walking, transit and bicycle commute shares by 0.5, 0.4 and
  0.1. It does not directly measure street design or pedestrian conditions.
- ZIP/ZCTA assignments approximate city boundaries; these are selected cases,
  not a representative sample of U.S. cities. No chart establishes causality.

| File | What it shows |
|---|---|
| `city_relationships.png` | The same score/log-ZHVI observations together and split by city, on shared axes. The correlations do not account for other factors; no regression lines or new models are fitted. |
| `geographic_transfer.png` | Lasso predictions for cities left out of training. Each city's data was excluded from both model fitting and penalty selection. The diagonal marks perfect predictions. |

The comparison chart uses rows kept by the SQL analysis rules. The prediction
chart uses `predictions.csv` from the script output, not values predicted by a
model trained on the same rows. Combined R² compares prediction errors with
errors from using the overall mean of log ZHVI; per-city R² uses that city's
mean. The negative combined R² is part of the reported findings.

## Regenerate

1. Follow the root [setup and loading guide](../../README.md) and start the
   already loaded PostgreSQL database. Use the same trusted inputs if comparing
   against these figures; fresh Zillow downloads may revise historical values.
2. Activate the project environment and run
   `python -m walkability.analysis --output-dir outputs/readme-refresh`.
   Choose another unused destination if that path already exists. No geometry,
   Census request or notebook is needed for these two charts.
3. Inspect `metrics.csv`, `source_audit.csv` and the rendered images. Confirm the
   sample, periods and findings before replacing a public image. If inputs have
   changed, investigate and update the explanation rather than forcing the old counts.
4. Copy **only** `city_relationships.png` and `geographic_transfer.png` from that
   completed output folder into this directory. Review the copies and README
   captions together. Do not set this tracked directory as `--output-dir` or
   copy the whole run here.
5. Run `python -m ruff check src tests`,
   `python -m ruff format --check src tests` and
   `python -m unittest discover -s tests -v` before committing. Database tests
   additionally need the separate, explicitly selected test server described
   in the root guide.

The images are PNGs exported at 160 dpi. They contain public statistical results,
not source downloads, credentials or connection details. Most run outputs remain
ignored under `outputs/`; only these selected figures are tracked. Rendering can
vary slightly across platforms or Matplotlib versions without changing results.