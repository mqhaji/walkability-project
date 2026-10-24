"""Read manual Zillow inputs and retrieve the two required Census tables."""

from pathlib import Path

import pandas as pd
import requests

from walkability.config import ACS_YEAR, DETAILED_VARIABLES, PROFILE_VARIABLES, ZHVI_DATE


def read_zillow(file_path: Path) -> pd.DataFrame:
    """Read only location columns and the pinned month, preserving ZIP strings."""
    required = ["RegionName", "City", "CountyName", "State", ZHVI_DATE.isoformat()]
    if not file_path.is_file():
        raise FileNotFoundError("Missing Zillow source CSV; see README.md for setup.")
    header = pd.read_csv(file_path, nrows=0)
    missing = sorted(set(required) - set(header.columns))
    if missing:
        raise ValueError(f"Zillow source is missing columns: {missing}")
    return pd.read_csv(file_path, usecols=required, dtype={"RegionName": "string"})


def _fetch_table(endpoint: str, variables: dict[str, str], api_key: str) -> pd.DataFrame:
    """Fetch a Census row-array response without leaking a keyed URL on failure."""
    try:
        response = requests.get(
            endpoint,
            params={
                "get": ",".join(["NAME", *variables.values()]),
                "for": "zip code tabulation area:*",
                "key": api_key,
            },
            timeout=60,
        )
        response.raise_for_status()
    except requests.RequestException:
        raise RuntimeError("Census request failed; check connectivity and the API key.") from None
    if "application/json" not in response.headers.get("content-type", ""):
        raise ValueError("Census returned non-JSON data; check the API key.")
    try:
        payload = response.json()
    except ValueError:
        raise ValueError("Census returned invalid JSON.") from None
    if (
        not isinstance(payload, list)
        or len(payload) < 2
        or not isinstance(payload[0], list)
        or not all(isinstance(name, str) for name in payload[0])
        or len(set(payload[0])) != len(payload[0])
        or any(not isinstance(row, list) or len(row) != len(payload[0]) for row in payload[1:])
    ):
        raise ValueError("Unexpected Census response structure.")
    return pd.DataFrame(payload[1:], columns=payload[0])


def fetch_acs(api_key: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Download national ZCTA tables once; preparation filters to the study ZIPs."""
    base_url = f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5"
    return (
        _fetch_table(f"{base_url}/profile", PROFILE_VARIABLES, api_key),
        _fetch_table(base_url, DETAILED_VARIABLES, api_key),
    )