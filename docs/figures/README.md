# Public result charts

These two images let readers see the main findings without installing the
project or obtaining the source data. They were generated on **2026-10-24**
from the existing study database, without refreshing Zillow or Census data.

## Data and interpretation

- Housing values: Zillow ZIP-level ZHVI, **2025-03-31** observation.
- Commuting and controls: **2022 ACS five-year estimates**. The housing and ACS
  periods differ; this is a cross-sectional comparison, not a time-series study.
- Sample: **248 observations**—Chicago 55, New York City 171, Washington, DC 22.
  Of the 250 source records, `10037` and `60602` are excluded because ACS median
  home value is unavailable. The existing complete-case rules are unchanged.
- The proxy weights walking, transit and bicycle commute shares by 0.5, 0.4 and
  0.1. It does not directly measure street design or pedestrian conditions.
- ZIP/ZCTA assignments approximate city boundaries; these are selected cases,
  not a representative sample of U.S. cities. No chart establishes causality.

| File | What it shows |
|---|---|
| `city_relationships.png` | The same score/log-ZHVI observations pooled and split by city, on shared axes. Pearson correlations are unadjusted; no regression lines or additional models are fitted. |
| `geographic_transfer.png` | Predictions from the established nested Lasso procedure. Each city's predictions come from models that excluded it during training and penalty selection. The diagonal marks perfect predictions. |

The comparison chart uses the eligible SQL features. The transfer chart uses
`predictions.csv` from the analysis export, not in-sample fitted values. Combined
R² uses the overall outcome mean as its benchmark; individual-city evaluation
uses the respective city's mean. A negative combined R² is a result to explain,
not a reason to hide or retune the model.

## Regenerate

1. Follow the root [setup and loading guide](../../README.md) and start the
   already loaded PostgreSQL database. Use the same trusted inputs if comparing
   against these figures; fresh Zillow downloads may revise historical values.
2. Activate the project environment and run
   `python -m walkability.analysis --output-dir outputs/readme-refresh`.
   Choose another unused destination if that path already exists. No geometry,
   Census request or notebook is needed for these two charts.
3. Inspect `metrics.csv`, `source_audit.csv` and the rendered images. Confirm the
   sample, periods and findings before replacing a public image. A genuine input
   change requires investigation and updated explanations, not forced counts.
4. Copy **only** `city_relationships.png` and `geographic_transfer.png` from that
   completed output folder into this directory. Review the copies and README
   captions together. Do not set this tracked directory as `--output-dir` or
   copy the whole run here.
5. Run `python -m ruff check src tests`,
   `python -m ruff format --check src tests` and
   `python -m unittest discover -s tests -v` before committing. Database tests
   additionally need the explicitly selected disposable test server described
   in the root guide.

The images are PNGs exported at 160 dpi. They contain public statistical results,
not source downloads, credentials or connection details. Most run outputs remain
ignored under `outputs/`; only these selected figures are tracked. Rendering can
vary slightly across platforms or Matplotlib versions without changing results.