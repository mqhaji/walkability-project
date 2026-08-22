# Does the Walkability–Housing Value Relationship Hold Within Cities?

A ZIP/ZCTA-level comparison of whether the apparent relationship between commute-mode walkability and housing values remains consistent within New York City, Washington, DC, and Chicago.

> **Project status:** This repository preserves the current validated version of an inherited exploratory analysis. Data definitions and the research framing were refined during a technical audit and after preliminary results had been examined. The findings are therefore descriptive and diagnostic rather than a preregistered confirmatory test.

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

### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Windows PowerShell

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Run the Notebook

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
