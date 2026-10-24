"""Source cleaning and relational table preparation, not statistical features.

The reference notebook's city filters and source definitions are preserved.
Missing ACS estimates remain missing in the source tables; analytical sample
selection and derived features belong to the SQL layer.
"""

import numpy as np
import pandas as pd

from walkability.config import ACS_YEAR, DETAILED_VARIABLES, PROFILE_VARIABLES, ZHVI_DATE

NYC_COUNTIES = {
    "Bronx County", "Kings County", "New York County", "Queens County", "Richmond County"
}
STUDY_AREAS = {"Chicago", "New York City", "Washington DC"}
PERCENT_COLUMNS = [
    "Percent_Car", "Percent_Public_Transit", "Percent_Walk", "Percent_Bike",
    "Percent_Renter", "Percent_Owner", "Percent_Bachelors_Plus",
]
ACS_COLUMNS = [
    "ZIP", "NAME", "Median_Income", "Median_Rent", "Median_Home_Value",
    "Percent_Car", "Percent_Public_Transit", "Percent_Walk", "Percent_Bike",
    "Commute_Time_Min", "Percent_Renter", "Percent_Owner",
    "Percent_Bachelors_Plus", "Total_Population",
]
ACS_DB_NAMES = {
    "ZIP": "zcta", "Median_Income": "median_income", "Median_Rent": "median_rent",
    "Median_Home_Value": "median_home_value", "Percent_Car": "percent_car",
    "Percent_Public_Transit": "percent_public_transit", "Percent_Walk": "percent_walk",
    "Percent_Bike": "percent_bike", "Commute_Time_Min": "commute_minutes",
    "Percent_Renter": "percent_renter", "Percent_Owner": "percent_owner",
    "Percent_Bachelors_Plus": "percent_bachelors_plus", "Total_Population": "population",
}


def require_columns(frame: pd.DataFrame, columns: list[str], label: str) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing or frame.columns.duplicated().any():
        raise ValueError(f"{label}: missing columns {missing} or duplicate column names.")


def normalize_zcta(values: pd.Series) -> pd.Series:
    """Pad short digit-only keys; reject nulls, decimals, and overlong keys."""
    keys = values.astype("string").str.strip()
    if not keys.str.fullmatch(r"[0-9]{1,5}", na=False).all():
        raise ValueError("ZCTA keys must contain one to five digits without missing values.")
    return keys.str.zfill(5)


def require_unique_keys(frame: pd.DataFrame, label: str) -> None:
    if frame["ZIP"].duplicated().any():
        raise ValueError(f"{label}: duplicate ZCTA keys.")


def _numeric(values: pd.Series, label: str) -> pd.Series:
    """Reject malformed and infinite values while retaining genuine missing data."""
    if values.map(lambda value: isinstance(value, (bool, np.bool_))).any():
        raise ValueError(f"{label}: Boolean values are not numeric estimates.")
    try:
        result = pd.to_numeric(values, errors="raise")
    except (ValueError, TypeError):
        raise ValueError(f"{label}: nonnumeric values.") from None
    if not np.isfinite(result.dropna().astype(float)).all():
        raise ValueError(f"{label}: infinite values.")
    return result


def prepare_zillow(source: pd.DataFrame) -> pd.DataFrame:
    observation = ZHVI_DATE.isoformat()
    require_columns(source, ["RegionName", "City", "CountyName", "State", observation], "Zillow")
    nyc = source["State"].eq("NY") & source["CountyName"].isin(NYC_COUNTIES)
    dc = source["State"].eq("DC") & source["City"].eq("Washington")
    chicago = (
        source["State"].eq("IL") & source["CountyName"].eq("Cook County")
        & source["City"].eq("Chicago")
    )
    selected = []
    for mask, area in [(nyc, "New York City"), (dc, "Washington DC"), (chicago, "Chicago")]:
        rows = source.loc[mask].copy()
        rows["Study_Area"] = area
        selected.append(rows)
    result = pd.concat(selected, ignore_index=True).rename(
        columns={"RegionName": "ZIP", "CountyName": "County", observation: "ZHVI"}
    )
    result["ZIP"] = normalize_zcta(result["ZIP"])
    result["ZHVI"] = _numeric(result["ZHVI"], "ZHVI")
    if result["ZHVI"].isna().any() or result["ZHVI"].le(0).any():
        raise ValueError("Zillow requires nonmissing, positive ZHVI values.")
    require_unique_keys(result, "Zillow")
    if set(result["Study_Area"]) != STUDY_AREAS:
        raise ValueError("Zillow must contain all three study areas.")
    if set(result.loc[result["Study_Area"].eq("New York City"), "County"]) != NYC_COUNTIES:
        raise ValueError("NYC coverage must include all five borough counties.")
    if result[["City", "County", "State"]].isna().any().any():
        raise ValueError("Zillow geography assignments cannot be missing.")
    result["ZHVI_Date"] = ZHVI_DATE
    return result[["ZIP", "City", "County", "State", "Study_Area", "ZHVI", "ZHVI_Date"]].sort_values(
        ["Study_Area", "ZIP"]
    ).reset_index(drop=True)


def _prepare_acs_table(
    source: pd.DataFrame, variables: dict[str, str], selected_zctas: set[str]
) -> pd.DataFrame:
    require_columns(source, ["NAME", "zip code tabulation area", *variables.values()], "ACS")
    result = source.rename(columns={"zip code tabulation area": "ZIP"}).copy()
    result["ZIP"] = normalize_zcta(result["ZIP"])
    result = result.loc[result["ZIP"].isin(selected_zctas)].copy()
    require_unique_keys(result, "ACS")
    if set(result["ZIP"]) != selected_zctas:
        raise ValueError("ACS table does not cover every selected Zillow ZCTA.")
    for label, variable in variables.items():
        values = _numeric(result.pop(variable), label)
        result[label] = values.mask(values.lt(0))  # Census negative sentinels mean unavailable.
    return result


def prepare_acs(
    profile: pd.DataFrame, detailed: pd.DataFrame, selected_zctas: set[str]
) -> pd.DataFrame:
    profile = _prepare_acs_table(profile, PROFILE_VARIABLES, selected_zctas)
    detailed = _prepare_acs_table(detailed, DETAILED_VARIABLES, selected_zctas)
    result = profile.merge(
        detailed[["ZIP", "Workers_16_Plus", "Bicycle_Workers"]],
        on="ZIP", how="left", validate="one_to_one",
    )
    workers = result["Workers_16_Plus"]
    bicycles = result["Bicycle_Workers"]
    for values in [workers, bicycles]:
        if values.dropna().mod(1).ne(0).any():
            raise ValueError("ACS worker counts must be integers.")
    if bicycles.gt(workers).any():
        raise ValueError("Bicycle workers cannot exceed total workers.")
    result["Percent_Car"] = result["Percent_Drove_Alone"] + result["Percent_Carpooled"]
    result["Percent_Bike"] = 100 * bicycles / workers.where(workers.gt(0))
    return validate_acs(result[ACS_COLUMNS], selected_zctas)


def validate_acs(source: pd.DataFrame, selected_zctas: set[str]) -> pd.DataFrame:
    """Validate API-prepared data or an explicitly supplied local ACS extract."""
    require_columns(source, ACS_COLUMNS, "ACS extract")
    result = source[ACS_COLUMNS].copy()
    result["ZIP"] = normalize_zcta(result["ZIP"])
    require_unique_keys(result, "ACS extract")
    if set(result["ZIP"]) != selected_zctas:
        raise ValueError("ACS and Zillow ZCTA sets must match exactly.")
    for name in ACS_COLUMNS[2:]:
        result[name] = _numeric(result[name], name)
    for name in PERCENT_COLUMNS:
        if result[name].isna().any() or not result[name].between(0, 100).all():
            raise ValueError(f"{name}: expected nonmissing percentages between 0 and 100.")
    for name in ["Median_Income", "Median_Rent", "Median_Home_Value", "Total_Population"]:
        if result[name].dropna().le(0).any():
            raise ValueError(f"{name}: available estimates must be positive.")
    if result["Commute_Time_Min"].dropna().lt(0).any():
        raise ValueError("Commute minutes cannot be negative.")
    if result["Total_Population"].dropna().mod(1).ne(0).any():
        raise ValueError("Population must be an integer.")
    return result.sort_values("ZIP").reset_index(drop=True)


def prepare_tables(zillow: pd.DataFrame, acs: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Produce the three source tables, retaining unavailable ACS estimates as NULL."""
    require_unique_keys(zillow, "Zillow")
    acs = validate_acs(acs, set(zillow["ZIP"]))
    # This explicit join audit guards against a future many-to-many merge.
    coverage = zillow[["ZIP"]].merge(acs[["ZIP"]], on="ZIP", validate="one_to_one", how="outer", indicator=True)
    if not coverage["_merge"].eq("both").all():
        raise ValueError("Zillow/ACS merge must match one-to-one.")
    geography = zillow[["ZIP", "Study_Area", "City", "County", "State"]].rename(columns={
        "ZIP": "zcta", "Study_Area": "study_area", "City": "zillow_city",
        "County": "zillow_county", "State": "state",
    })
    housing = zillow[["ZIP", "ZHVI_Date", "ZHVI"]].rename(columns={
        "ZIP": "zcta", "ZHVI_Date": "observation_date", "ZHVI": "zhvi",
    })
    demographics = acs[list(ACS_DB_NAMES)].rename(columns=ACS_DB_NAMES)
    demographics.insert(1, "acs_year", ACS_YEAR)
    demographics["population"] = demographics["population"].astype("Int64")
    return {
        "dim_geography": geography.reset_index(drop=True),
        "fact_housing": housing.reset_index(drop=True),
        "fact_acs": demographics.reset_index(drop=True),
    }