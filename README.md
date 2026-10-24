# Does the Walkability–Housing Value Relationship Hold Within Cities?

A ZIP/ZCTA-level comparison of New York City, Washington, DC, and Chicago using
Zillow housing values and Census commuting and socioeconomic estimates.

**Main finding:** the positive pooled relationship does not hold consistently
within cities, and models trained in two cities transfer poorly to the third.
These are associations, not evidence that walkability causes housing values to
rise or fall.

This is an inherited exploratory project. Data definitions and research framing
were refined after preliminary results had been examined; it is not a
preregistered confirmatory study.

## Results and Study Scope

| Comparison | Result |
|---|---|
| Pooled correlation: proxy vs. log housing value | 0.39 |
| Within-city correlations | Chicago 0.11; New York City 0.07; Washington, DC −0.54 |
| City-controlled OLS proxy coefficient | −1.9095; HC3 p≈0.001; R²≈0.783 |
| Leave-one-city-out Lasso | Overall R²≈−1.879: worse than the overall-mean benchmark |
| Sample-based walkable/affordable comparison | 51 of 248 observations |

The relationship differs by city and changes with the controls included in the
model. A positive pooled correlation alone is not evidence of a universal
walkability premium.

### What is measured?

- **ZHVI:** Zillow Home Value Index, an estimate of typical home value. The
  outcome is its natural logarithm, using the **2025-03-31** observation.
- **ACS:** **2022 five-year** Census estimates of commuting, income, tenure,
  education and population. The periods do not align exactly with Zillow.
- **Walkability proxy:** `0.5 × walk share + 0.4 × transit share + 0.1 × bicycle share`.
  This is not official Walk Score or a direct measure of sidewalks, destinations
  or street connectivity. The weights are analytical choices.
- **Affordability flag:** housing value strictly below the eligible sample's
  median and proxy score strictly above its median. This uses the full sample,
  not city-specific medians or an external affordability standard.

All 250 source observations are retained in PostgreSQL. Two ZCTAs, `10037` and
`60602`, lack ACS median home-value estimates and are excluded from the common
analytical sample. The remaining 248 observations include Chicago 55, New York
City 171, and Washington, DC 22.

### Why these cities?

The three cities were selected in the original project, not randomly sampled.
Their established transit systems and differing housing and commuting patterns
make the comparison useful, but they are neither matched cases nor a
representative sample of U.S. cities.

The study covers core-city assignments, **not metropolitan areas**:

- New York City: New York State ZIPs in its five borough counties.
- Washington, DC: state `DC`, Zillow city `Washington`.
- Chicago: state `IL`, Zillow city `Chicago`, Cook County.

Postal ZIPs and Census ZIP Code Tabulation Areas (ZCTAs) are approximate
counterparts, not identical boundaries. These assignments do not precisely
follow municipal boundaries or include the surrounding suburbs.

## How the Project Runs

**Zillow CSV + Census ACS → Python preparation → PostgreSQL source tables → SQL
features and rankings → Python models → saved tables and figures**

The command-line workflow needs no notebook. GeoPandas reads optional map
geometry locally; PostgreSQL stores no polygons and needs no PostGIS.

## Setup

### 1. Install Python dependencies

Python 3.13 is the tested runtime; the package requires Python 3.13 or newer.
From the repository root, create and activate a virtual environment:

- macOS/Linux: `python3 -m venv .venv`, then `source .venv/bin/activate`.
- Windows PowerShell: `py -3.13 -m venv .venv`, then `.\.venv\Scripts\Activate.ps1`.

Install with `python -m pip install -e .`. Runtime dependencies are pinned in
`requirements.txt`. Keep this checkout in place: the package reads its SQL and
local data paths from the repository.

### 2. Download the source files

**Zillow:** open [Zillow Research Data](https://www.zillow.com/research/data/),
select Home Values → ZHVI All Homes (SFR, Condo/Co-op), Smoothed, Seasonally
Adjusted → ZIP Code. Save the CSV as:

`data/housing/Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv`

The file must contain `2025-03-31`. Zillow may revise historical values, so a
fresh download can differ from the input used for the reported results.

**Census ACS:** the loader downloads two 2022 ACS tables. Request a free
[Census API key](https://api.census.gov/data/key_signup.html), copy `.env.example`
to `.env`, and fill in `CENSUS_API_KEY`. A successful API-based load saves an
inspectable extract to `data/acs/acs_zip_2022.csv`.

**Optional maps:** from the [Census shapefile downloader](https://www.census.gov/cgi-bin/geo/shapefiles/index.php),
choose 2024 → ZIP Code Tabulation Areas. Extract the national
`tl_2024_us_zcta520.zip` into `data/geo/`. Keep the `.shp`, `.dbf`, `.shx`, `.prj`
and `.cpg` files together. The expected main file is
`data/geo/tl_2024_us_zcta520.shp`, with the `ZCTA5CE20` key field.

Source files, `.env`, generated results and the virtual environment are ignored
by Git. Never commit passwords or API keys.

### 3. Start PostgreSQL

Install and start [Docker Desktop](https://www.docker.com/products/docker-desktop/).
Fill in the PostgreSQL settings in `.env`, preserving the Census key, then run
`docker compose up -d --wait`.

The PostgreSQL 17 service binds only to `127.0.0.1` and keeps data in a named
volume. Default user/database names are `walkability`. `POSTGRES_PASSWORD` is a
separate local database password—not your operating-system or Census password.

Exported environment variables override `.env`. Keep `.env` private; on macOS,
restrict it to owner read/write access. Do not print resolved Compose settings.
Stopping with `docker compose stop` preserves the volume. Editing `.env` alone
does **not** rotate an existing database password: update the database role and
local setting together. Do not delete the volume merely to change a password.

An existing PostgreSQL 17 server can use the same connection settings. Use a
dedicated study database and a role able to create tables/views and
read/insert/update rows in `public`. This localhost setup uses the image's
bootstrap administrator; it is not a production deployment design.

## Load Data

Run `python -m walkability.pipeline`. To reuse a trusted cached extract without
contacting Census, run
`python -m walkability.pipeline --acs-file data/acs/acs_zip_2022.csv`.
The cached format has no vintage column: the caller must confirm it is 2022 data.
There is no automatic cache fallback after API failure.

Add `--validate-only` to check inputs without connecting to PostgreSQL or writing
files. Without an explicit cached extract, validation still calls Census.

| Source table | Primary key | Contents |
|---|---|---|
| `dim_geography` | `zcta` | Study area and Zillow city/county/state |
| `fact_housing` | `(zcta, observation_date)` | Positive finite ZHVI |
| `fact_acs` | `(zcta, acs_year)` | Commuting and socioeconomic estimates |

Keys remain five-digit text. Constraints enforce valid values and foreign keys.
Unavailable estimates remain NULL, never zero. Source percentages stay in 0–100
units; SQL converts them to shares. Double precision avoids extra currency rounding.
Boolean values such as `True` and `False` are rejected in numeric source fields,
not converted into estimates of 1 and 0.

Tables, upserts, coverage checks and view setup share one transaction. Failures
roll everything back. Repeated loads update matching keys without duplicates;
unexpected current-study keys cause failure rather than deletion. Historical
fact periods are preserved. `CREATE TABLE IF NOT EXISTS` is repeatable setup,
not a schema-migration framework.

### SQL features and rankings

- `vw_analysis_features`: pinned-period joins, complete-case filtering, natural
  logs, ratios, shares, proxy score and the global-median flag.
- `vw_city_rankings`: within-city ranks, percent-ranks, means and deviations,
  plus deterministic top/bottom selection orders. Ties share statistical ranks;
  selection orders break ties by ZCTA. Housing rank 1 means **most expensive**.

For loaded tables, install just the views with
`python -m walkability.pipeline --views-only`. This makes no source requests or
source writes and cannot be combined with source-file options or validation mode.
`sql/analysis.sql` supplies four standalone SELECT examples. Its city-mean
comparison is supplemental, not a replacement for the global-median flag.

## Run the Analysis

Run `python -m walkability.analysis --output-dir outputs/my-run`.
Add `--maps` for all three city maps; `--geometry-file` can select another copy
of the same source geometry. Without `--maps`, geometry is not read.
The installed aliases are `walkability-load` and `walkability-analyze`.

Model fitting requires eligible observations from all three study areas. If a
city is missing after filtering, analysis stops before fitting rather than
silently running a different study. Check source coverage and unavailable
estimates; do not remove the check just to obtain results. The SQL reader still
supports smaller samples for inspection and tests.

If maps cannot be read, the error points to `--geometry-file` and the required
shapefile sidecars. Geometry problems are reported separately from output-saving
failures. Raw file-reader and database exception details are not printed.

The reader fetches features, rankings and a source audit in one read-only,
repeatable-read snapshot. It checks keys, periods, finite analytical values and
matching membership, then closes the connection before modeling. Analysis makes
no Census requests and does not read either notebook or source CSVs.

Exports include OLS coefficients and fit diagnostics, cluster assignments and
stability scores, city-held-out predictions and errors, Lasso coefficients, SQL
rankings, source audit and summary metrics. Five statistical images are saved:
correlations, clustering diagnostics, cluster profiles, Lasso coefficients and
geographic transfer. Optional maps bring the total to **eight PNGs**. All maps
use the same color range and require one geometry per observation.

**Output safety:** the destination must not exist, even as an empty folder or
symlink. Exports go into a temporary sibling folder and are published by rename
only after every export succeeds. Ordinary failures clean up their temporary
files. A forced kill or power loss can leave a hidden `.<name>-incomplete-*`
folder; parent directories may remain empty. Previous results are never deleted.
Concurrent runs into the same destination are not supported.

## Tests and Verification

Run `python -m unittest discover -s tests -v` for the offline tests. They check
source parsing and preparation, the three-city requirement, model setup, safe
errors, output cleanup, figure rendering and map coverage. Invented records and
mocked Census responses cover ZIP formatting, city filters, missing-value codes,
bicycle-share calculations and malformed API responses. No database, API key,
external data request or downloaded study data is needed for these tests.

Eight PostgreSQL tests are skipped unless `TEST_DATABASE_DSN` is explicitly set.
Point it at a **dedicated disposable server**, never production. The role must
be allowed to create and drop databases. Each test creates a random
`walkability_test_*` database and registers cleanup to drop only that database.
Tests never read `.env` or fall back to the study connection. They cover formulas,
ties, strict median rules, missing data, historical periods, repeat loads and rollback.

[GitHub Actions](https://github.com/mqhaji/walkability-project/actions) runs the
suite on pushes and pull requests with Python 3.13 and temporary PostgreSQL 17.
Its password is a disposable test value. The runner needs internet to install
dependencies, but tests make no external data requests. The first hosted run
[passed for commit `164445a`](https://github.com/mqhaji/walkability-project/actions/runs/40127631604).

Local checks passed all **42 tests** (34 offline and eight PostgreSQL tests).
The new tests have not yet been verified on GitHub; check this commit's workflow
after pushing. The earlier passing run above does not verify these new changes.
Separately, real-input SQL features matched
the reference's 35-column contract within `1e-12`. Script regression estimates,
HC3 errors, all 248 transfer predictions, bootstrap scores and Lasso coefficients
matched notebook calculations within `1e-10`. Cluster partitions agreed exactly
and all 248 observations mapped. Synthetic CI checks code behavior; it does not
independently reproduce the research from real data.

## Methods and Limitations

Primary OLS uses the proxy, log median income, commute time, renter share,
college-graduate share, log population and city indicators. HC3 standard errors
address unequal residual variance, not spatial dependence or omitted variables.
Large condition numbers remain a scaling/multicollinearity caution. The ACS
home-value-to-income ratio is sensitivity-only because it overlaps with the outcome.

KMeans is exploratory: four standardized features, candidate k=2–6, selected
k=3, and 100 bootstrap resamples. Nested Lasso holds out one whole city at a
time and chooses its penalty in grouped inner folds, with scaling inside the
pipeline. A final full-sample fit describes coefficients; it is not an additional
independent performance test.

The main limits are the commute-based proxy, three selected cities, approximate
boundaries, spatial dependence, mismatched periods and omitted variables. More
cities, better built-environment measures and longitudinal data are research next
steps, not reasons to tune away the current negative transfer result.

## Repository Guide

| Path | Purpose |
|---|---|
| `src/walkability/config.py` | Paths, fixed periods and connection settings |
| `src/walkability/extract.py`, `prepare.py`, `pipeline.py` | Source extraction, validation and loading command |
| `src/walkability/database.py` | Transactional loading and read-only analytical reader |
| `src/walkability/analysis.py`, `figures.py` | Model command and figure exports |
| `sql/schema.sql`, `views.sql`, `analysis.sql` | Source tables, analytical views and example queries |
| `tests/` | Offline and opt-in PostgreSQL tests |
| `.github/workflows/tests.yml` | Automated test workflow |
| `compose.yaml` | Local PostgreSQL service |
| `data/README.md` | Local input directory guide |
| `outputs/` | Generated results, ignored by Git |

### Reference notebooks

Neither notebook is required by the main workflow. Both are preserved for comparison.

- `notebooks/walkability_analysis_postgres.ipynb` reads SQL views and local
  geometry. Select the `.venv` kernel and restart/run all cells to inspect it.
- `notebooks/walkability_analysis.ipynb` is the original reference. Running it
  contacts Census and rewrites the cached ACS extract; it is not needed to
  execute the current analysis.

A focused Power BI dashboard remains planned. No additional models are required.