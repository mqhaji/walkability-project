"""Check and load Zillow and Census data; do not run statistical models."""

import argparse
from pathlib import Path

import pandas as pd
import psycopg

from walkability.config import (
    ACS_PATH,
    ACS_YEAR,
    ZHVI_DATE,
    ZILLOW_PATH,
    database_settings,
    env_value,
)
from walkability.database import apply_views, load_tables
from walkability.extract import fetch_acs, read_zillow
from walkability.prepare import (
    prepare_acs,
    prepare_tables,
    prepare_zillow,
    validate_acs,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check housing and commuting data and load it into PostgreSQL."
    )
    parser.add_argument(
        "--zillow-file",
        type=Path,
        default=None,
        help="Downloaded ZIP-level Zillow CSV.",
    )
    parser.add_argument(
        "--acs-file",
        type=Path,
        help="Use a trusted saved 2022 ACS extract; otherwise request the data from Census.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--validate-only",
        action="store_true",
        help="Check and summarize inputs without connecting or writing files.",
    )
    mode.add_argument(
        "--views-only",
        action="store_true",
        help="Set up analysis views from existing tables without reading source files or calling Census.",
    )
    args = parser.parse_args()
    if args.views_only and (args.zillow_file is not None or args.acs_file is not None):
        parser.error("--views-only cannot be combined with source-file arguments")
    try:
        if args.views_only:
            apply_views(database_settings())
            print("PostgreSQL analysis views are ready.")
            return 0
        settings = None if args.validate_only else database_settings()
        zillow = prepare_zillow(read_zillow(args.zillow_file or ZILLOW_PATH))
        selected = set(zillow["ZIP"])
        if args.acs_file is not None:
            acs = validate_acs(
                pd.read_csv(args.acs_file, dtype={"ZIP": "string"}), selected
            )
            source_label = "saved ACS extract (you must confirm it contains 2022 data)"
        else:
            key = env_value("CENSUS_API_KEY")
            if not key:
                raise ValueError(
                    "Set CENSUS_API_KEY in .env or explicitly supply --acs-file."
                )
            profile, detailed = fetch_acs(key)
            acs = prepare_acs(profile, detailed, selected)
            source_label = "Census API"
        tables = prepare_tables(zillow, acs)
        print(f"Zillow observation: {ZHVI_DATE}; ACS five-year end year: {ACS_YEAR}")
        print(f"ACS source: {source_label}")
        print("ZCTAs by study area:")
        print(zillow.groupby("Study_Area", sort=True).size().to_string())
        print(f"Each of the {len(zillow)} Zillow ZCTAs has one matching ACS record.")
        missing = acs.isna().sum()
        if missing.gt(0).any():
            print("Unavailable ACS estimates (retained as database NULL):")
            print(missing[missing.gt(0)].to_string())
        if args.validate_only:
            print("Validation complete. No database or source files changed.")
            return 0
        counts = load_tables(tables, settings)
        print(
            "Saved PostgreSQL source rows and analysis views: "
            + ", ".join(f"{name}={count}" for name, count in counts.items())
        )
        if args.acs_file is None:
            # Save a CSV for inspection after the database commit succeeds.
            # A failed CSV write does not undo the saved database load.
            try:
                ACS_PATH.parent.mkdir(parents=True, exist_ok=True)
                acs.to_csv(ACS_PATH, index=False)
            except OSError:
                print(
                    "Warning: database committed, but the local ACS export could not be saved."
                )
        return 0
    except psycopg.Error:
        # Driver messages can include connection details or rejected row contents.
        print(
            "Database operation failed; transaction rolled back. Check PostgreSQL setup, permissions, and SQL definitions."
        )
        return 1
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Pipeline stopped: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
