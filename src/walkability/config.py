"""Pinned source periods, repository paths, and local environment settings."""

import os
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
ZILLOW_PATH = (
    DATA_DIR / "housing" / "Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv"
)
ACS_PATH = DATA_DIR / "acs" / "acs_zip_2022.csv"
SCHEMA_PATH = PROJECT_ROOT / "sql" / "schema.sql"
VIEWS_PATH = PROJECT_ROOT / "sql" / "views.sql"
ZHVI_DATE = date(2025, 3, 31)
ACS_YEAR = 2022

PROFILE_VARIABLES = {
    "Median_Income": "DP03_0062E",
    "Median_Rent": "DP04_0134E",
    "Median_Home_Value": "DP04_0089E",
    "Percent_Drove_Alone": "DP03_0019PE",
    "Percent_Carpooled": "DP03_0020PE",
    "Percent_Public_Transit": "DP03_0021PE",
    "Percent_Walk": "DP03_0022PE",
    "Commute_Time_Min": "DP03_0025E",
    "Percent_Renter": "DP04_0047PE",
    "Percent_Owner": "DP04_0046PE",
    "Percent_Bachelors_Plus": "DP02_0068PE",
    "Total_Population": "DP05_0001E",
}
DETAILED_VARIABLES = {
    "Workers_16_Plus": "B08301_001E",
    "Bicycle_Workers": "B08301_018E",
}


def env_value(name: str, default: str | None = None) -> str | None:
    """Prefer the process environment, then the ignored repository .env file.

    Supports the project's simple KEY=value format with optional outer quotes;
    shell expansion and inline comments are deliberately not supported.
    """
    value = os.getenv(name)
    if value:
        return value
    env_path = PROJECT_ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() == name:
                return value.strip().strip("\"'") or default
    return default


def database_settings() -> dict[str, str]:
    """Connection parameters, never printed or included in an error message."""
    password = env_value("POSTGRES_PASSWORD")
    if not password:
        raise ValueError("Set POSTGRES_PASSWORD in .env before loading PostgreSQL.")
    return {
        "host": env_value("POSTGRES_HOST", "localhost") or "localhost",
        "port": env_value("POSTGRES_PORT", "5432") or "5432",
        "dbname": env_value("POSTGRES_DB", "walkability") or "walkability",
        "user": env_value("POSTGRES_USER", "walkability") or "walkability",
        "password": password,
        "connect_timeout": "10",
    }
