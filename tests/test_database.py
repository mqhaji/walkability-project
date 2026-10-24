"""Opt-in PostgreSQL tests. Never use the project's default connection settings.

TEST_DATABASE_DSN must identify a server where the test role can create databases.
Each test creates and drops only its own randomly named database.
"""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

import numpy as np
import pandas as pd
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from walkability import database
from walkability.config import ACS_YEAR, ZHVI_DATE


def source_tables():
    """Four invented Chicago records with ties and known global medians."""
    keys = ["60601", "60602", "60603", "60604"]
    geography = pd.DataFrame([
        [key, "Chicago", "Chicago", "Cook County", "IL"] for key in keys
    ], columns=database.TABLE_COLUMNS["dim_geography"])
    housing = pd.DataFrame({
        "zcta": keys, "observation_date": ZHVI_DATE, "zhvi": [400., 300., 200., 100.],
    })
    acs = pd.DataFrame({
        "zcta": keys, "acs_year": ACS_YEAR,
        "median_income": 60_000., "median_rent": 1_000., "median_home_value": 200_000.,
        "percent_car": [90., 90., 70., 50.], "percent_public_transit": 0.,
        "percent_walk": [10., 10., 30., 50.], "percent_bike": 0.,
        "commute_minutes": 20., "percent_renter": 40., "percent_owner": 60.,
        "percent_bachelors_plus": 30., "population": 1_000,
    })[database.TABLE_COLUMNS["fact_acs"]]
    return {"dim_geography": geography, "fact_housing": housing, "fact_acs": acs}


@unittest.skipUnless(os.environ.get("TEST_DATABASE_DSN"), "Set TEST_DATABASE_DSN to run PostgreSQL tests")
class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.name = "walkability_test_" + uuid4().hex
        self.admin = psycopg.connect(os.environ["TEST_DATABASE_DSN"], autocommit=True)
        self.addCleanup(self.admin.close)
        self.admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.name)))
        self.addCleanup(self.drop_database)
        self.settings = conninfo_to_dict(os.environ["TEST_DATABASE_DSN"])
        self.settings["dbname"] = self.name
        self.tables = source_tables()
        database.load_tables(self.tables, self.settings)

    def drop_database(self):
        self.admin.execute(
            sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(self.name))
        )

    def snapshot(self):
        with psycopg.connect(**self.settings) as connection:
            return {
                table: connection.execute(
                    sql.SQL("SELECT * FROM public.{} ORDER BY 1, 2").format(sql.Identifier(table))
                ).fetchall()
                for table in database.TABLE_KEYS
            }

    def test_features_flags_and_ranking_ties(self):
        features, rankings, audit = database.read_analysis_data(self.settings)
        np.testing.assert_allclose(features["Walkability_Score"], [.05, .05, .15, .25])
        np.testing.assert_allclose(features["Log_ZHVI"], np.log([400., 300., 200., 100.]))
        np.testing.assert_allclose(features["Income_to_Rent"], 5.)
        self.assertEqual(features["Is_Walkable_and_Affordable"].tolist(), [False, False, True, True])
        self.assertEqual(rankings["walkability_rank"].tolist(), [3, 3, 2, 1])
        np.testing.assert_allclose(rankings["walkability_percent_rank"], [0, 0, 2/3, 1])
        self.assertEqual(rankings["walkability_top_order"].tolist(), [3, 4, 2, 1])
        self.assertTrue(audit["included_in_analysis"].all())

    def test_null_estimate_is_excluded_but_record_retained(self):
        with psycopg.connect(**self.settings) as connection:
            connection.execute("UPDATE public.fact_acs SET median_home_value=NULL WHERE zcta='60601'")
        features, _, audit = database.read_analysis_data(self.settings)
        self.assertEqual(len(features), 3)
        row = audit.set_index("zcta").loc["60601"]
        self.assertTrue(row["acs_present"])
        self.assertEqual(row["missing_required_fields"], "median_home_value")
        self.assertEqual(row["status"], "missing_required_estimate")

    def test_missing_fact_is_rejected_by_reader(self):
        with psycopg.connect(**self.settings) as connection:
            connection.execute("DELETE FROM public.fact_acs WHERE zcta='60601'")
        with self.assertRaisesRegex(ValueError, "source facts are missing"):
            database.read_analysis_data(self.settings)

    def test_repeat_load_and_view_install_preserve_values(self):
        before = self.snapshot()
        database.load_tables(self.tables, self.settings)
        database.apply_views(self.settings)
        self.assertEqual(before, self.snapshot())

    def test_history_does_not_multiply_rows_and_singleton_rank_is_zero(self):
        with psycopg.connect(**self.settings) as connection:
            connection.execute(
                "INSERT INTO public.fact_housing (zcta, observation_date, zhvi) "
                "SELECT zcta, DATE '2024-03-31', 9999 FROM public.fact_housing"
            )
        self.assertEqual(len(database.read_analysis_data(self.settings)[0]), 4)
        with psycopg.connect(**self.settings) as connection:
            connection.execute("UPDATE public.fact_acs SET median_home_value=NULL WHERE zcta <> '60601'")
        features, rankings, _ = database.read_analysis_data(self.settings)
        self.assertEqual(len(features), 1)
        self.assertEqual(rankings["walkability_percent_rank"].iloc[0], 0.)
        self.assertFalse(features["Is_Walkable_and_Affordable"].iloc[0])

    def test_view_failure_rolls_back_source_updates(self):
        before = self.snapshot()
        self.tables["fact_housing"].loc[0, "zhvi"] = 999.
        with TemporaryDirectory() as directory:
            invalid = Path(directory) / "invalid.sql"
            invalid.write_text("SELECT nonexistent_test_function();", encoding="utf-8")
            with patch.object(database, "VIEWS_PATH", invalid):
                with self.assertRaises(psycopg.Error):
                    database.load_tables(self.tables, self.settings)
        self.assertEqual(before, self.snapshot())

    def test_source_constraint_failure_rolls_back(self):
        before = self.snapshot()
        self.tables["fact_housing"].loc[0, "zhvi"] = 999.
        self.tables["fact_acs"].loc[0, "percent_walk"] = 101.
        with self.assertRaises(psycopg.errors.CheckViolation):
            database.load_tables(self.tables, self.settings)
        self.assertEqual(before, self.snapshot())

    def test_median_equality_is_not_flagged(self):
        # With three observations, the middle score and price are exact medians.
        with psycopg.connect(**self.settings) as connection:
            connection.execute("UPDATE public.fact_acs SET percent_walk=20 WHERE zcta='60602'")
            connection.execute("UPDATE public.fact_acs SET median_home_value=NULL WHERE zcta='60604'")
        features, _, _ = database.read_analysis_data(self.settings)
        self.assertFalse(features["Is_Walkable_and_Affordable"].iloc[1])


if __name__ == "__main__":
    unittest.main()