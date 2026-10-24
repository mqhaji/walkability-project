# Does the Walkability–Housing Value Relationship Hold Within Cities?

A ZIP/ZCTA-level comparison of whether the apparent relationship between commute-mode walkability and housing values remains consistent within New York City, Washington, DC, and Chicago.

> **Project status:** This repository preserves the current validated version of an inherited exploratory analysis. Data definitions and the research framing were refined during a technical audit and after preliminary results had been examined. The findings are therefore descriptive and diagnostic rather than a preregistered confirmatory test.

> **Pipeline upgrade — Stage 1:** A small Python package and PostgreSQL source-table loader are now provided alongside the unchanged reference notebook. SQL analytical views, notebook migration, pytest/CI, and Power BI are later stages; the current statistical results were not produced from PostgreSQL.

## Research Objective

The project asks:

> **Within three core-city samples, how is a commuting-based walkability proxy associated with Zillow Home Value Index (ZHVI) after accounting for city context and selected socioeconomic characteristics?**

The main analytical concern is geographic aggregation. A positive relationship in pooled data may reflect structural differences among cities rather than a relationship that holds within each city. The notebook therefore compares:

1. pooled and within-city correlations;
2. robust OLS estimates with city indicators and socioeconomic controls;
3. separate city-specific OLS estimates; and
4. leave-one-city-out Lasso performance, which tests whether relationships learned from two cities transfer to the third.

The notebook also maps the proxy, identifies sample-relative walkable-and-affordable ZIP/ZCTAs, and performs exploratory KMeans segmentation with cluster-quality and stability diagnostics.

## Why These Cities?

New York City, Washington, DC, and Chicago are treated as **purposively selected comparative cases**, not as a representative sample of U.S. cities. All three are large, established core cities with mature public-transit systems, substantial pre-automobile development, and enough walking, transit, and bicycle commuting for a commute-mode proxy to vary meaningfully across ZIP/ZCTAs.

The comparison is informative because the cities also differ in housing costs, density, transit dependence, regional context, and ZIP/ZCTA composition. Those differences create a useful test of whether a pooled relationship persists within distinct urban settings and transfers across them.

The city choices originated in the inherited project. This rationale explains why the comparison is analytically useful; it does not imply that the cases were prespecified through systematic sampling, constitute a strict matched-case design, or support claims about all U.S. cities.

## Study Areas

The samples represent **core cities, not metropolitan statistical areas**:

- **New York City:** ZIPs assigned by Zillow to the five borough counties.
- **Washington, DC:** ZIPs with state `DC` and city `Washington`.
- **Chicago:** ZIPs with city `Chicago` in Cook County.

Zillow ZIP assignments and Census ZCTAs only approximate municipal boundaries. The study does not include the broader New York, Washington, or Chicago suburbs.

## Main Finding

The pooled walkability–housing value correlation is positive (`0.39`), but it is weak within Chicago (`0.11`) and New York City (`0.07`) and negative within Washington, DC (`-0.54`). After city indicators and selected socioeconomic controls are added, the OLS walkability coefficient is negative (`-1.9095`, HC3 $p=0.001$). Leave-one-city-out Lasso performs poorly overall ($R^2=-1.879$).

The project therefore finds **geographic heterogeneity and aggregation sensitivity**, not a universal walkability premium. These cross-sectional results describe associations and do not estimate a causal effect of walkability on housing values.

## Data Sources and Setup

To run the project from the beginning, manually download the Zillow and Census geometry files, then configure a Census API key for the ACS request made by the notebook.

### 1. Zillow ZIP-Level Home Value Data (ZHVI)

- **Source:** [Zillow Research Data](https://www.zillow.com/research/data/)
- **File:** `Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv`
- **Type:** ZIP-level Zillow Home Value Index

To download it:

1. Open [Zillow Research Data](https://www.zillow.com/research/data/).
2. Scroll to **Home Values**.
3. Select **ZHVI All Homes (SFR, Condo/Co-op), Smoothed, Seasonally Adjusted**.
4. Select **ZIP Code** as the geography.
5. Download the CSV and place it at:

   ```text
   data/housing/Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv
   ```

The analysis is pinned to the Zillow observation dated `2025-03-31`, so the downloaded file must contain that column.

### 2. ACS Demographic and Commute Data (via API)

The notebook downloads the selected **2022 ACS five-year** demographic, housing, and commuting fields directly from the U.S. Census Bureau API. It then saves the result as:

```text
data/acs/acs_zip_2022.csv
```

A free Census API key is required:

1. Request a key from the [Census API Key signup page](https://api.census.gov/data/key_signup.html).
2. Copy `.env.example` to `.env`:

   **macOS or Linux**

   ```bash
   cp .env.example .env
   ```

   **Windows PowerShell**

   ```powershell
   Copy-Item .env.example .env
   ```

3. Open `.env` and enter the key after `CENSUS_API_KEY=`:

   ```text
   CENSUS_API_KEY=your-key-here
   ```

The notebook reads the key without displaying it. `.env` is ignored by Git and must never be committed.

### 3. ZIP Code Tabulation Area (ZCTA) Shapefiles

- **Source:** [Census Bureau Shapefile Downloader](https://www.census.gov/cgi-bin/geo/shapefiles/index.php)
- **Archive:** `tl_2024_us_zcta520.zip`

To download it:

1. Open the [Census Bureau Shapefile Downloader](https://www.census.gov/cgi-bin/geo/shapefiles/index.php).
2. Select year **2024**.
3. Select **ZIP Code Tabulation Areas (ZCTAs)** as the layer type.
4. Download `tl_2024_us_zcta520.zip`.
5. Extract the complete archive into `data/geo/`.

The main shapefile must be located at:

```text
data/geo/tl_2024_us_zcta520.shp
```

Keep all extracted sidecar files (`.dbf`, `.shx`, `.prj`, and `.cpg`) in the same directory.

## Install the Python Environment

Python 3.13 is recommended. Run these commands from the repository root.
The editable install makes `walkability` importable and uses `requirements.txt`
as the single source of runtime dependencies. Keep the checkout in place: the
package reads the versioned SQL and local inputs from this repository.

### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

### Windows PowerShell

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

## Stage 1: Load the PostgreSQL Source Tables

The new pipeline currently stops at **Python extraction/validation → PostgreSQL**.
The reference notebook still runs independently and is intentionally unchanged.
Geometry stays in GeoPandas; PostgreSQL stores no polygons and needs no PostGIS.

### Start a local database

1. Install and start [Docker Desktop](https://www.docker.com/products/docker-desktop/), or use an existing PostgreSQL 17 database.
2. Add the PostgreSQL entries from `.env.example` to your ignored `.env`. Preserve your existing Census key and choose a local `POSTGRES_PASSWORD`.
3. From the repository root, start the dedicated database:

   ```bash
   docker compose up -d --wait
   ```

The Compose service binds only to `127.0.0.1` and persists data in a Docker volume.
It is for local development, not a production deployment. An existing server can
be used instead by setting the same connection variables; the loader needs a
dedicated database and permission to create tables and insert/update rows in `public`.
Never print or commit connection passwords or resolved Compose configuration.

### How the local password works

- `POSTGRES_PASSWORD` is a separate password for the local PostgreSQL login, not your macOS, Docker, or Census password.
- On first initialization of an empty volume, the PostgreSQL image creates the `POSTGRES_USER` login and `POSTGRES_DB` database using that password. The default names are both `walkability`.
- Docker Compose reads `.env` when starting the service; the Python loader reads the same settings when connecting to `localhost:5432`. Exported environment variables take precedence, so avoid conflicting values.
- Keep the real password only in the ignored `.env`; `.env.example` intentionally has an empty placeholder. On macOS, restrict `.env` to owner read/write permissions. These controls do not encrypt the file or protect it from someone with access to your account or Docker.
- Stopping/restarting the container preserves credentials and tables in the named volume. Editing `.env` alone does **not** change an existing database password: a password change must update the PostgreSQL role and the local setting together. Do not delete the volume just to change a password.

This uses the PostgreSQL image's bootstrap administrator for a localhost-only
development database. A deployed database would require more restrictive roles
and a different approach to secret management.

### Extract, validate, and load

With the Python environment activated:

```bash
python -m walkability.pipeline
```

This reads the pinned Zillow month, downloads the two 2022 ACS tables, validates
the selected sources, applies `sql/schema.sql`, and upserts all three tables in
one transaction. Database errors roll back the entire load. A successful API-based
load also exports the same ignored `data/acs/acs_zip_2022.csv` for inspection.

To explicitly reuse the existing trusted **2022** ACS extract rather than make an
API request:

```bash
python -m walkability.pipeline --acs-file data/acs/acs_zip_2022.csv
```

The legacy CSV contains no vintage column: its 2022 provenance is the caller's
responsibility. There is no automatic cache fallback on API failure. To validate
inputs without PostgreSQL or any file writes, add `--validate-only` to either command.

### Table contracts and expected checks

| Table | Grain / primary key | Contents |
|---|---|---|
| `dim_geography` | `zcta` | Study area and Zillow city/county/state assignments |
| `fact_housing` | `(zcta, observation_date)` | Positive finite ZHVI; pinned load date `2025-03-31` |
| `fact_acs` | `(zcta, acs_year)` | Demographic, housing, and commuting estimates; pinned load year `2022` |

- ZCTA keys stay five-digit text. Foreign keys prevent orphan facts.
- Percentages stay in their original **0–100** units; later SQL views will derive shares and features.
- Floating-point estimates retain the notebook's precision, without extra currency rounding.
- Unavailable ACS amounts/counts remain `NULL`, never zero. Invalid available values fail validation.
- The reference inputs should load **250 rows per table**: NYC 172, Chicago 56, DC 22.
- The two unavailable ACS home-value estimates remain in the source table. The **248-row analytical filter belongs to Stage 2**, not the loader.
- Repeating the same load updates matching keys without duplicates. Unexpected existing keys for the current sample/period abort the load rather than being silently deleted. The script does not erase historical fact periods.
- `CREATE TABLE IF NOT EXISTS` makes setup repeatable; it is not a schema-migration framework. The loader targets a dedicated database with this exact schema.

Stop the local database with `docker compose stop`; the volume is retained. Changing
the password in `.env` does not change credentials in an already initialized volume.
Do not delete that volume unless you intentionally want to discard its database.

**Stage 1 verification (2026-09-10):** live ACS extraction and explicit local-CSV
preparation pass. The trusted local inputs load into PostgreSQL 17 with **250 rows
per table**, and all stored values match the prepared inputs exactly. Repeated
loads preserve keys and values without duplicates. An intentionally invalid ACS
percentage causes the entire load to roll back, including earlier geography and
housing updates. Primary/foreign keys, required values, finite housing values,
positive population, and study assignments were checked against the running
database. The two unavailable home values remain SQL `NULL`.

The existing Python environment was restored on Python 3.13.15; dependency and
scientific-library import checks pass. The reference notebook remains unchanged.
These are local verification checks, **not yet a committed pytest suite or CI**.
SQL analytical views and notebook migration remain Stage 2.

## Run the Reference Notebook

In VS Code:

1. Install the Microsoft Python and Jupyter extensions if needed.
2. Open `notebooks/walkability_analysis.ipynb`.
3. Select the interpreter inside `.venv` as the notebook kernel.
4. Choose **Restart Kernel and Run All Cells**.

The notebook will:

1. load and filter the manually downloaded Zillow CSV;
2. download and save the ACS fields for the selected ZIPs;
3. merge the Zillow and ACS data in memory;
4. validate and engineer the analysis features;
5. load and filter the manually downloaded national ZCTA shapefile;
6. create maps for the three core-city study areas;
7. compare pooled, city-controlled, and city-specific relationships;
8. validate the exploratory KMeans solution; and
9. evaluate Lasso with nested leave-one-city-out validation.

Expected execution checks are:

- 250 Zillow rows across the three core-city study areas;
- 250 matching ACS rows;
- 250 rows after the one-to-one merge;
- 248 retained analysis rows after excluding two unavailable ACS home-value estimates; and
- 248 mapped analysis rows.

## Repository Layout

```text
walkability-project/
├── data/
│   ├── README.md                              # Local data setup guide
│   ├── acs/
│   │   └── acs_zip_2022.csv                 # Generated by the notebook
│   ├── geo/
│   │   └── tl_2024_us_zcta520.*             # Downloaded and extracted manually
│   └── housing/
│       └── Zip_zhvi_uc_sfrcondo_*.csv       # Downloaded manually
├── notebooks/
│   └── walkability_analysis.ipynb
├── src/walkability/                         # Stage 1 extraction/preparation/loading
│   ├── __init__.py
│   ├── config.py
│   ├── extract.py
│   ├── prepare.py
│   ├── database.py
│   └── pipeline.py
├── sql/
│   └── schema.sql                          # Three source tables and constraints
├── compose.yaml                            # Local PostgreSQL 17 only
├── pyproject.toml                          # Editable package; deps from requirements.txt
├── .env.example
├── .gitignore
├── README.md
└── requirements.txt
```

The raw Zillow file, national ZCTA files, generated ACS CSV, local `.env`, and virtual environment are ignored by Git.

## Analysis Notes

The walkability measure is a weighted commuting-mode proxy:

$$
0.5(\text{Walk Share}) + 0.4(\text{Transit Share}) + 0.1(\text{Bike Share}).
$$

It is not an official Walk Score or a direct measurement of the built environment. The weights are analytical choices rather than externally validated values.

The primary outcome is the natural logarithm of ZIP-level ZHVI. The main OLS specification includes log median income, commute time, renter share, college-graduate share, log population, and city indicators, with HC3 heteroskedasticity-robust standard errors. An ACS home-value-to-income ratio appears only in a sensitivity model because its numerator overlaps conceptually with ZHVI.

Important limitations include the cross-sectional design, spatial dependence among nearby ZCTAs, different ACS and Zillow observation periods, imperfect municipal-boundary alignment, the use of only three cities, and the commuting proxy's limited representation of the built environment.
