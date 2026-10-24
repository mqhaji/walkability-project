"""Load a complete study snapshot into PostgreSQL in one transaction."""

from typing import Any

import numpy as np
import pandas as pd
import psycopg
from psycopg import sql

from walkability.config import ACS_YEAR, SCHEMA_PATH, ZHVI_DATE, database_settings
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
    """Adapt pandas missing values and NumPy scalars to PostgreSQL parameters."""
    if pd.isna(value):
        return None
    return value.item() if isinstance(value, np.generic) else value


def _validate_batch(tables: dict[str, pd.DataFrame]) -> None:
    if set(tables) != set(TABLE_KEYS):
        raise ValueError("A load must supply all three source tables.")
    for table, frame in tables.items():
        if frame.empty or list(frame.columns) != TABLE_COLUMNS[table]:
            raise ValueError(f"{table}: empty data or unexpected column layout.")
        if frame[TABLE_KEYS[table]].isna().any().any() or frame.duplicated(TABLE_KEYS[table]).any():
            raise ValueError(f"{table}: missing or duplicate primary keys.")
        if not frame["zcta"].astype("string").str.fullmatch(r"[0-9]{5}", na=False).all():
            raise ValueError(f"{table}: ZCTA keys must be five-digit strings.")
    expected = set(tables["dim_geography"]["zcta"])
    if any(set(frame["zcta"]) != expected for frame in tables.values()):
        raise ValueError("Every source table must cover exactly the same ZCTAs.")
    if not tables["fact_housing"]["observation_date"].eq(ZHVI_DATE).all():
        raise ValueError("Housing records must use the pinned observation date.")
    if not tables["fact_acs"]["acs_year"].eq(ACS_YEAR).all():
        raise ValueError("ACS records must use the pinned five-year vintage.")


def _upsert(connection: psycopg.Connection, table: str, frame: pd.DataFrame) -> None:
    columns = TABLE_COLUMNS[table]
    keys = TABLE_KEYS[table]
    updates = sql.SQL(", ").join(
        sql.SQL("{column} = EXCLUDED.{column}").format(column=sql.Identifier(column))
        for column in columns if column not in keys
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
    rows = (tuple(_database_value(value) for value in row) for row in frame.itertuples(index=False, name=None))
    with connection.cursor() as cursor:
        cursor.executemany(statement, rows)


def load_tables(
    tables: dict[str, pd.DataFrame], settings: dict[str, str] | None = None
) -> dict[str, int]:
    """Set up tables, upsert the batch, verify coverage, then commit atomically.

    A failure rolls back the entire transaction, including earlier table updates.
    Unexpected existing keys cause failure rather than silent deletion. This
    loader targets the project's fixed study sample, not arbitrary data imports.
    """
    _validate_batch(tables)
    expected = set(tables["dim_geography"]["zcta"])
    with psycopg.connect(**(database_settings() if settings is None else settings)) as connection:
        connection.execute("SET LOCAL search_path TO public")
        connection.execute(SCHEMA_PATH.read_text())
        for table in TABLE_KEYS:
            _upsert(connection, table, tables[table])
        queries = {
            "dim_geography": ("SELECT zcta FROM dim_geography", ()),
            "fact_housing": ("SELECT zcta FROM fact_housing WHERE observation_date = %s", (ZHVI_DATE,)),
            "fact_acs": ("SELECT zcta FROM fact_acs WHERE acs_year = %s", (ACS_YEAR,)),
        }
        counts = {}
        for table, (query, params) in queries.items():
            rows = connection.execute(query, params).fetchall()
            if len(rows) != len(expected) or {row[0] for row in rows} != expected:
                raise ValueError(f"{table}: stored ZCTA coverage differs; no changes committed.")
            counts[table] = len(rows)
    return counts