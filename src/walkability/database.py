"""Save a whole study load together and read consistent analysis results."""

from typing import Any

import numpy as np
import pandas as pd
import psycopg
from psycopg import IsolationLevel, sql

from walkability.config import (
    ACS_YEAR,
    SCHEMA_PATH,
    VIEWS_PATH,
    ZHVI_DATE,
    database_settings,
)
from walkability.prepare import ACS_DB_NAMES

TABLE_KEYS = {
    "dim_geography": ["zcta"],
    "fact_housing": ["zcta", "observation_date"],
    "fact_acs": ["zcta", "acs_year"],
}
TABLE_COLUMNS = {
    "dim_geography": ["zcta", "study_area", "zillow_city", "zillow_county", "state"],
    "fact_housing": ["zcta", "observation_date", "zhvi"],
    "fact_acs": ["zcta", "acs_year", *list(ACS_DB_NAMES.values())[1:]],
}


def _database_value(value: Any) -> Any:
    """Convert missing values to NULL and NumPy values to Python values."""
    if pd.isna(value):
        return None
    return value.item() if isinstance(value, np.generic) else value


def _validate_batch(tables: dict[str, pd.DataFrame]) -> None:
    if set(tables) != set(TABLE_KEYS):
        raise ValueError("A load must supply all three source tables.")
    for table, frame in tables.items():
        if frame.empty or list(frame.columns) != TABLE_COLUMNS[table]:
            raise ValueError(
                f"{table}: data is empty or columns do not match the expected order."
            )
        if (
            frame[TABLE_KEYS[table]].isna().any().any()
            or frame.duplicated(TABLE_KEYS[table]).any()
        ):
            raise ValueError(f"{table}: missing or duplicate primary keys.")
        if (
            not frame["zcta"]
            .astype("string")
            .str.fullmatch(r"[0-9]{5}", na=False)
            .all()
        ):
            raise ValueError(f"{table}: ZCTA keys must be five-digit strings.")
    expected = set(tables["dim_geography"]["zcta"])
    if any(set(frame["zcta"]) != expected for frame in tables.values()):
        raise ValueError("Every source table must cover exactly the same ZCTAs.")
    if not tables["fact_housing"]["observation_date"].eq(ZHVI_DATE).all():
        raise ValueError("Housing records must use the configured study date.")
    if not tables["fact_acs"]["acs_year"].eq(ACS_YEAR).all():
        raise ValueError("ACS records must use the configured five-year end year.")


def _upsert(connection: psycopg.Connection, table: str, frame: pd.DataFrame) -> None:
    columns = TABLE_COLUMNS[table]
    keys = TABLE_KEYS[table]
    updates = sql.SQL(", ").join(
        sql.SQL("{column} = EXCLUDED.{column}").format(column=sql.Identifier(column))
        for column in columns
        if column not in keys
    )
    statement = sql.SQL(
        "INSERT INTO {table} ({columns}) VALUES ({values}) "
        "ON CONFLICT ({keys}) DO UPDATE SET {updates}"
    ).format(
        table=sql.Identifier(table),
        columns=sql.SQL(", ").join(map(sql.Identifier, columns)),
        values=sql.SQL(", ").join(sql.Placeholder() for _ in columns),
        keys=sql.SQL(", ").join(map(sql.Identifier, keys)),
        updates=updates,
    )
    rows = (
        tuple(_database_value(value) for value in row)
        for row in frame.itertuples(index=False, name=None)
    )
    with connection.cursor() as cursor:
        cursor.executemany(statement, rows)


def load_tables(
    tables: dict[str, pd.DataFrame], settings: dict[str, str] | None = None
) -> dict[str, int]:
    """Set up tables and views, insert/update rows, then save the whole load.

    Check stored ZIP coverage before saving. Any failure rolls back the load,
    including earlier table updates. Unexpected existing keys cause failure,
    not silent deletion. This loader is for the fixed study, not general imports.
    """
    _validate_batch(tables)
    expected = set(tables["dim_geography"]["zcta"])
    with psycopg.connect(
        **(database_settings() if settings is None else settings)
    ) as connection:
        connection.execute("SET LOCAL search_path TO public")
        connection.execute(SCHEMA_PATH.read_text())
        for table in TABLE_KEYS:
            _upsert(connection, table, tables[table])
        queries = {
            "dim_geography": ("SELECT zcta FROM dim_geography", ()),
            "fact_housing": (
                "SELECT zcta FROM fact_housing WHERE observation_date = %s",
                (ZHVI_DATE,),
            ),
            "fact_acs": ("SELECT zcta FROM fact_acs WHERE acs_year = %s", (ACS_YEAR,)),
        }
        counts = {}
        for table, (query, params) in queries.items():
            rows = connection.execute(query, params).fetchall()
            if len(rows) != len(expected) or {row[0] for row in rows} != expected:
                raise ValueError(
                    f"{table}: stored ZCTAs do not match this load; no changes were saved."
                )
            counts[table] = len(rows)
        _apply_views(connection)
    return counts


def _apply_views(connection: psycopg.Connection) -> None:
    """Run the repository's view definitions in the current transaction."""
    connection.execute(VIEWS_PATH.read_text(encoding="utf-8"))


def apply_views(settings: dict[str, str] | None = None) -> None:
    """Set up views on existing tables without fetching or changing source rows."""
    with psycopg.connect(
        **(database_settings() if settings is None else settings)
    ) as connection:
        _apply_views(connection)


# Keep the 35 column names and order expected by the analysis.
FEATURE_NAMES = {
    "zcta": "ZIP",
    "zillow_city": "City",
    "zillow_county": "County",
    "state": "State",
    "study_area": "Study_Area",
    "observation_date": "ZHVI_Date",
    "zhvi": "ZHVI",
    "median_income": "Median_Income",
    "median_rent": "Median_Rent",
    "median_home_value": "Median_Home_Value",
    "percent_car": "Percent_Car",
    "percent_public_transit": "Percent_Public_Transit",
    "percent_walk": "Percent_Walk",
    "percent_bike": "Percent_Bike",
    "commute_minutes": "Commute_Time_Min",
    "percent_renter": "Percent_Renter",
    "percent_owner": "Percent_Owner",
    "percent_bachelors_plus": "Percent_Bachelors_Plus",
    "population": "Total_Population",
    "log_zhvi": "Log_ZHVI",
    "log_median_income": "Log_Median_Income",
    "log_population": "Log_Population",
    "income_to_rent": "Income_to_Rent",
    "home_value_to_income": "Home_Value_to_Income",
    "walk_share": "Walk_Share",
    "transit_share": "Transit_Share",
    "bike_share": "Bike_Share",
    "car_share": "Car_Share",
    "rent_share": "Rent_Share",
    "owner_share": "Owner_Share",
    "college_grad_share": "College_Grad_Share",
    "population_k": "Population_k",
    "commute_min": "Commute_Min",
    "walkability_score": "Walkability_Score",
    "is_walkable_and_affordable": "Is_Walkable_and_Affordable",
}
RANKING_COLUMNS = [
    "zcta",
    "study_area",
    "zillow_city",
    "zillow_county",
    "state",
    "observation_date",
    "acs_year",
    "zhvi",
    "walkability_score",
    "is_walkable_and_affordable",
    "walkability_rank",
    "housing_value_rank",
    "walkability_percent_rank",
    "housing_value_percent_rank",
    "city_mean_walkability",
    "city_mean_zhvi",
    "walkability_minus_city_mean",
    "zhvi_minus_city_mean",
    "walkability_top_order",
    "walkability_bottom_order",
]

# A missing estimate is not the same as a missing record: check record keys first.
# Keep the matching example in sql/analysis.sql consistent with this query.
SOURCE_AUDIT_QUERY = """
WITH audited AS (
    SELECT g.zcta, g.study_area,
           h.zcta IS NOT NULL AS housing_present,
           a.zcta IS NOT NULL AS acs_present,
           concat_ws(', ',
               CASE WHEN h.zcta IS NOT NULL AND h.zhvi IS NULL THEN 'zhvi' END,
               CASE WHEN a.zcta IS NOT NULL AND a.median_income IS NULL THEN 'median_income' END,
               CASE WHEN a.zcta IS NOT NULL AND a.median_rent IS NULL THEN 'median_rent' END,
               CASE WHEN a.zcta IS NOT NULL AND a.median_home_value IS NULL THEN 'median_home_value' END,
               CASE WHEN a.zcta IS NOT NULL AND a.commute_minutes IS NULL THEN 'commute_minutes' END,
               CASE WHEN a.zcta IS NOT NULL AND a.population IS NULL THEN 'population' END
           ) AS missing_required_fields,
           f.zcta IS NOT NULL AS included_in_analysis
    FROM public.dim_geography g
    LEFT JOIN public.fact_housing h ON h.zcta=g.zcta AND h.observation_date=%s
    LEFT JOIN public.fact_acs a ON a.zcta=g.zcta AND a.acs_year=%s
    LEFT JOIN public.vw_analysis_features f ON f.zcta=g.zcta
)
SELECT zcta, study_area, housing_present, acs_present, missing_required_fields,
       included_in_analysis,
       CASE WHEN NOT housing_present THEN 'missing_housing_record'
            WHEN NOT acs_present THEN 'missing_acs_record'
            WHEN missing_required_fields <> '' THEN 'missing_required_estimate'
            WHEN NOT included_in_analysis THEN 'excluded_by_rules'
            ELSE 'included' END AS status
FROM audited ORDER BY study_area, zcta
"""


def _fetch_frame(connection, statement, params=None) -> pd.DataFrame:
    with connection.cursor() as cursor:
        cursor.execute(statement, params)
        if cursor.description is None:
            raise ValueError("Expected a table of analysis results from the query.")
        return pd.DataFrame.from_records(
            cursor.fetchall(), columns=[column.name for column in cursor.description]
        )


def _view_select(view: str, columns: list[str]):
    """Build a SELECT from fixed view/column names, never user-supplied SQL."""
    return sql.SQL("SELECT {columns} FROM {view} ORDER BY study_area, zcta").format(
        columns=sql.SQL(", ").join(map(sql.Identifier, columns)),
        view=sql.Identifier("public", view),
    )


def _check_keys(frame: pd.DataFrame, label: str) -> None:
    if frame.empty or frame["zcta"].duplicated().any():
        raise ValueError(f"{label}: empty data or duplicate ZCTA keys.")
    if not frame["zcta"].astype("string").str.fullmatch(r"[0-9]{5}", na=False).all():
        raise ValueError(f"{label}: expected five-digit ZCTA strings.")
    if (
        not frame["study_area"]
        .isin({"Chicago", "New York City", "Washington DC"})
        .all()
    ):
        raise ValueError(f"{label}: unexpected study-area assignment.")


def _check_boolean(values: pd.Series, label: str) -> None:
    if (
        values.isna().any()
        or not values.map(lambda value: isinstance(value, (bool, np.bool_))).all()
    ):
        raise ValueError(f"{label}: expected nonmissing Boolean values.")


def read_analysis_data(
    settings: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return analysis columns, city rankings and a source-coverage check table.

    All three reads see the same database snapshot. No source files, Census
    key, view setup or database writes are needed. Close the connection before
    returning so model fitting does not hold a database transaction open.
    """
    try:
        with psycopg.connect(
            **(database_settings() if settings is None else settings)
        ) as connection:
            connection.isolation_level = IsolationLevel.REPEATABLE_READ
            connection.read_only = True
            raw = _fetch_frame(
                connection,
                _view_select("vw_analysis_features", [*FEATURE_NAMES, "acs_year"]),
            )
            rankings = _fetch_frame(
                connection, _view_select("vw_city_rankings", RANKING_COLUMNS)
            )
            audit = _fetch_frame(connection, SOURCE_AUDIT_QUERY, (ZHVI_DATE, ACS_YEAR))
    except psycopg.errors.UndefinedTable:
        raise RuntimeError(
            "Load the source tables, then run python -m walkability.pipeline --views-only."
        ) from None
    except psycopg.Error:
        raise RuntimeError(
            "Cannot read PostgreSQL analysis data; check service, credentials, permissions and SQL definitions."
        ) from None

    for label, frame in [
        ("Features", raw),
        ("Rankings", rankings),
        ("Source audit", audit),
    ]:
        _check_keys(frame, label)
    for frame in [raw, rankings]:
        if (
            not frame["observation_date"].eq(ZHVI_DATE).all()
            or not frame["acs_year"].eq(ACS_YEAR).all()
        ):
            raise ValueError(
                "The analysis dates or ACS year do not match the study settings."
            )
        _check_boolean(
            frame["is_walkable_and_affordable"], "Higher-proxy/lower-value flag"
        )
    for column in ["housing_present", "acs_present", "included_in_analysis"]:
        _check_boolean(audit[column], column)
    if not audit[["housing_present", "acs_present"]].all().all():
        raise ValueError(
            "Required source facts are missing; check housing and ACS records for the study periods."
        )
    key_columns = ["zcta", "study_area"]
    keys = set(map(tuple, raw[key_columns].to_numpy()))
    if keys != set(map(tuple, rankings[key_columns].to_numpy())):
        raise ValueError(
            "Rankings and analysis rows must cover the same ZCTAs and cities."
        )
    included = audit.loc[audit["included_in_analysis"], key_columns]
    if keys != set(map(tuple, included.to_numpy())):
        raise ValueError(
            "Source checks and analysis results disagree about which rows are included."
        )
    for column in [
        "zillow_city",
        "zillow_county",
        "state",
        "zhvi",
        "walkability_score",
        "is_walkable_and_affordable",
    ]:
        if not raw[column].equals(rankings[column]):
            raise ValueError(
                f"Ranking and analysis views have different values for {column}."
            )
    numeric_rankings = rankings[RANKING_COLUMNS[10:]].apply(
        pd.to_numeric, errors="raise"
    )
    if not np.isfinite(numeric_rankings.to_numpy(dtype=float)).all():
        raise ValueError("Ranking values cannot be missing or infinite.")
    for column in [
        "walkability_rank",
        "housing_value_rank",
        "walkability_top_order",
        "walkability_bottom_order",
    ]:
        if not rankings[column].gt(0).all() or rankings[column].mod(1).ne(0).any():
            raise ValueError("Ranks and row orders must be positive integers.")
    for column in ["walkability_percent_rank", "housing_value_percent_rank"]:
        if not rankings[column].between(0, 1).all():
            raise ValueError("Percent-ranks must be within 0–1.")

    features = raw[list(FEATURE_NAMES)].rename(columns=FEATURE_NAMES).copy()
    text_columns = ["ZIP", "City", "County", "State", "Study_Area"]
    for column in text_columns:
        if features[column].isna().any():
            raise ValueError(f"Missing analysis label: {column}")
        features[column] = features[column].astype("string")
    features["ZHVI_Date"] = features["ZHVI_Date"].map(lambda value: value.isoformat())
    features["Is_Walkable_and_Affordable"] = features[
        "Is_Walkable_and_Affordable"
    ].astype(bool)
    nonnumeric = {*text_columns, "ZHVI_Date", "Is_Walkable_and_Affordable"}
    numeric_columns = [column for column in features if column not in nonnumeric]
    features[numeric_columns] = (
        features[numeric_columns].apply(pd.to_numeric, errors="raise").astype("float64")
    )
    if not np.isfinite(features[numeric_columns].to_numpy()).all():
        raise ValueError("Numeric analysis values cannot be missing or infinite.")
    return (
        features.reset_index(drop=True),
        rankings.reset_index(drop=True),
        audit.reset_index(drop=True),
    )
