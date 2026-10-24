"""Invented source records and mocked Census requests; no external data needed."""

import io
import traceback
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import requests

from walkability import extract, pipeline
from walkability.config import (
    ACS_YEAR,
    DETAILED_VARIABLES,
    PROFILE_VARIABLES,
    ZHVI_DATE,
)
from walkability.database import TABLE_COLUMNS
from walkability.prepare import (
    ACS_COLUMNS,
    normalize_zcta,
    prepare_acs,
    prepare_tables,
    prepare_zillow,
    validate_acs,
)


def zillow_source():
    """Seven study rows, one per NYC county plus DC and Chicago."""
    rows = [
        ("10451", "New York", "Bronx County", "NY"),
        ("11201", "New York", "Kings County", "NY"),
        ("10001", "New York", "New York County", "NY"),
        ("11101", "New York", "Queens County", "NY"),
        ("10301", "New York", "Richmond County", "NY"),
        ("20001", "Washington", "District of Columbia", "DC"),
        ("60601", "Chicago", "Cook County", "IL"),
    ]
    frame = pd.DataFrame(rows, columns=["RegionName", "City", "CountyName", "State"])
    frame[ZHVI_DATE.isoformat()] = 250_000.0
    return frame


def acs_extract(keys=("60601",)):
    values = {
        "ZIP": list(keys),
        "NAME": "Invented ZCTA",
        "Median_Income": 60_000.0,
        "Median_Rent": 1_000.0,
        "Median_Home_Value": 200_000.0,
        "Percent_Car": 60.0,
        "Percent_Public_Transit": 20.0,
        "Percent_Walk": 10.0,
        "Percent_Bike": 2.0,
        "Commute_Time_Min": 25.0,
        "Percent_Renter": 40.0,
        "Percent_Owner": 60.0,
        "Percent_Bachelors_Plus": 30.0,
        "Total_Population": 1_000.0,
    }
    return pd.DataFrame(values)[ACS_COLUMNS]


def api_tables():
    """One valid invented record in each Census response's actual column layout."""
    values = acs_extract().iloc[0].to_dict()
    values.update(Percent_Drove_Alone=50.0, Percent_Carpooled=10.0)
    profile = {
        variable: str(values[label]) for label, variable in PROFILE_VARIABLES.items()
    }
    profile.update(NAME="Invented ZCTA", **{"zip code tabulation area": "60601"})
    detailed = {
        "NAME": "Invented ZCTA",
        "zip code tabulation area": "60601",
        "B08301_001E": "200",
        "B08301_018E": "4",
    }
    return pd.DataFrame([profile]), pd.DataFrame([detailed])


class PreparationTests(unittest.TestCase):
    def test_numeric_fields_reject_boolean_values(self):
        variants = [
            pd.Series([True]),
            pd.Series([np.bool_(False)]),
            pd.Series([True], dtype="boolean"),
            pd.Series([1.0, True], dtype=object),
            pd.Series([np.bool_(True), pd.NA], dtype="boolean"),
        ]
        for column in ["Percent_Renter", "Median_Income", "Total_Population"]:
            for values in variants:
                with self.subTest(
                    column=column, dtype=str(values.dtype), values=values.tolist()
                ):
                    keys = ["60601", "60602"][: len(values)]
                    source = acs_extract(keys)
                    source[column] = values
                    with self.assertRaisesRegex(ValueError, "Boolean"):
                        validate_acs(source, set(keys))
        cached = pd.read_csv(
            io.StringIO(acs_extract().assign(Percent_Renter=True).to_csv(index=False)),
            dtype={"ZIP": "string"},
        )
        with self.assertRaisesRegex(ValueError, "Boolean"):
            validate_acs(cached, {"60601"})

    def test_keys_preserve_leading_zeros_and_reject_malformed_values(self):
        self.assertEqual(
            normalize_zcta(pd.Series([" 1234 ", "00501", 60601])).tolist(),
            ["01234", "00501", "60601"],
        )
        for value in [None, pd.NA, "", "123456", "12.0", 1234.5, "abc", True]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_zcta(pd.Series([value]))

    def test_city_filters_reject_nearby_but_out_of_scope_rows(self):
        source = zillow_source()
        distractors = pd.DataFrame(
            [
                ["11001", "New York", "Nassau County", "NY", 250_000.0],
                ["99901", "New York", "Bronx County", "NJ", 250_000.0],
                ["20002", "Other", "District of Columbia", "DC", 250_000.0],
                ["60602", "Other", "Cook County", "IL", 250_000.0],
                ["60603", "Chicago", "DuPage County", "IL", 250_000.0],
                ["60604", "Chicago", "Cook County", "IN", 250_000.0],
            ],
            columns=source.columns,
        )
        result = prepare_zillow(pd.concat([source, distractors], ignore_index=True))
        self.assertEqual(set(result["ZIP"]), set(source["RegionName"]))
        self.assertEqual(
            result.groupby("Study_Area").size().to_dict(),
            {
                "Chicago": 1,
                "New York City": 5,
                "Washington DC": 1,
            },
        )
        self.assertTrue(result["ZHVI_Date"].eq(ZHVI_DATE).all())

    def test_zillow_requires_unique_complete_geography_and_positive_finite_value(self):
        source = zillow_source()
        cases = [
            source.iloc[:-1],  # Missing Chicago.
            source.iloc[1:],  # Missing one NYC borough county.
            pd.concat([source, source.iloc[:1]], ignore_index=True),
            source.drop(columns=[ZHVI_DATE.isoformat()]),
        ]
        for value in [0.0, -1.0, np.inf, np.nan, True, "bad"]:
            invalid = source.copy()
            invalid[ZHVI_DATE.isoformat()] = pd.Series([value] * len(source))
            cases.append(invalid)
        for index, invalid in enumerate(cases):
            with self.subTest(case=index):
                with self.assertRaises(ValueError):
                    prepare_zillow(invalid)

    def test_numeric_strings_and_permitted_missing_estimates_are_retained(self):
        source = acs_extract(("60601", "60602"))
        for column in ACS_COLUMNS[2:]:
            source[column] = source[column].astype("string")
        nullable = [
            "Median_Income",
            "Median_Rent",
            "Median_Home_Value",
            "Commute_Time_Min",
            "Total_Population",
        ]
        source.loc[0, nullable] = pd.NA
        result = validate_acs(source, {"60601", "60602"})
        self.assertTrue(result.loc[0, nullable].isna().all())
        self.assertEqual(result.loc[1, "Median_Income"], 60_000.0)
        self.assertEqual(result.loc[1, "Percent_Renter"], 40.0)

    def test_cached_acs_rejects_bad_values_keys_and_coverage(self):
        source = acs_extract()
        for column, value in [
            ("Percent_Walk", -1.0),
            ("Percent_Walk", 101.0),
            ("Percent_Walk", np.nan),
            ("Median_Income", 0.0),
            ("Median_Rent", -1.0),
            ("Commute_Time_Min", -1.0),
            ("Total_Population", 1.5),
            ("Median_Home_Value", np.inf),
            ("Percent_Renter", "True"),
        ]:
            with self.subTest(column=column, value=value):
                invalid = source.copy()
                invalid[column] = pd.Series([value])
                with self.assertRaises(ValueError):
                    validate_acs(invalid, {"60601"})
        for invalid, keys in [
            (pd.concat([source, source], ignore_index=True), {"60601"}),
            (source, {"60601", "60602"}),
            (source.drop(columns=["Median_Income"]), {"60601"}),
        ]:
            with self.subTest(keys=keys, rows=len(invalid)):
                with self.assertRaises(ValueError):
                    validate_acs(invalid, keys)

    def test_api_preparation_uses_sentinels_and_correct_commute_formulas(self):
        profile, detailed = api_tables()
        profile["DP04_0089E"] = "-666666666"
        result = prepare_acs(profile, detailed, {"60601"})
        self.assertTrue(pd.isna(result.loc[0, "Median_Home_Value"]))
        self.assertEqual(result.loc[0, "Percent_Car"], 60.0)
        self.assertEqual(result.loc[0, "Percent_Bike"], 2.0)  # 100 * 4 / 200.

    def test_api_worker_counts_and_coverage_are_validated(self):
        profile, detailed = api_tables()
        for workers, bicycles in [
            (0, 0),
            (200, 201),
            (200.5, 4),
            (200, 4.5),
            (-666666666, 4),
            (200, -666666666),
        ]:
            with self.subTest(workers=workers, bicycles=bicycles):
                invalid = detailed.copy()
                invalid["B08301_001E"] = str(workers)
                invalid["B08301_018E"] = str(bicycles)
                with self.assertRaises(ValueError):
                    prepare_acs(profile, invalid, {"60601"})
        for invalid_profile, invalid_detailed in [
            (profile.iloc[:0], detailed),
            (profile, detailed.iloc[:0]),
            (pd.concat([profile, profile], ignore_index=True), detailed),
        ]:
            with self.subTest(rows=(len(invalid_profile), len(invalid_detailed))):
                with self.assertRaises(ValueError):
                    prepare_acs(invalid_profile, invalid_detailed, {"60601"})

    def test_prepared_tables_keep_keys_periods_and_missing_estimates(self):
        zillow = prepare_zillow(zillow_source())
        acs = acs_extract(tuple(zillow["ZIP"]))
        acs.loc[0, "Median_Home_Value"] = np.nan
        acs.loc[0, "Total_Population"] = np.nan
        tables = prepare_tables(zillow, acs)
        for name, frame in tables.items():
            self.assertEqual(list(frame.columns), TABLE_COLUMNS[name])
            self.assertEqual(set(frame["zcta"]), set(zillow["ZIP"]))
            self.assertFalse(frame["zcta"].duplicated().any())
        self.assertTrue(tables["fact_housing"]["observation_date"].eq(ZHVI_DATE).all())
        self.assertTrue(tables["fact_acs"]["acs_year"].eq(ACS_YEAR).all())
        self.assertEqual(str(tables["fact_acs"]["population"].dtype), "Int64")
        self.assertEqual(tables["fact_acs"]["median_home_value"].isna().sum(), 1)
        self.assertEqual(tables["fact_acs"]["population"].isna().sum(), 1)


class ExtractionTests(unittest.TestCase):
    def test_zillow_csv_preserves_zip_and_requires_pinned_month(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "zillow.csv"
            source = zillow_source()
            source.loc[0, "RegionName"] = "00501"
            source["unused"] = "ignore"
            source.to_csv(path, index=False)
            result = extract.read_zillow(path)
            self.assertEqual(result.loc[0, "RegionName"], "00501")
            self.assertNotIn("unused", result)
            source.drop(columns=[ZHVI_DATE.isoformat()]).to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "missing columns"):
                extract.read_zillow(path)
            with self.assertRaises(FileNotFoundError):
                extract.read_zillow(Path(directory) / "missing.csv")

    def test_fetch_acs_uses_both_pinned_endpoints_and_timeout(self):
        profile, detailed = api_tables()
        responses = []
        for frame in [profile, detailed]:
            response = Mock()
            response.headers = {"content-type": "application/json; charset=utf-8"}
            response.json.return_value = [list(frame.columns), *frame.values.tolist()]
            responses.append(response)
        with patch.object(extract.requests, "get", side_effect=responses) as get:
            actual_profile, actual_detailed = extract.fetch_acs("invented-key")
        pd.testing.assert_frame_equal(actual_profile, profile)
        pd.testing.assert_frame_equal(actual_detailed, detailed)
        self.assertEqual(
            [call.args[0] for call in get.call_args_list],
            [
                "https://api.census.gov/data/2022/acs/acs5/profile",
                "https://api.census.gov/data/2022/acs/acs5",
            ],
        )
        for call, variables in zip(
            get.call_args_list, [PROFILE_VARIABLES, DETAILED_VARIABLES]
        ):
            self.assertEqual(call.kwargs["timeout"], 60)
            self.assertEqual(
                call.kwargs["params"]["get"], ",".join(["NAME", *variables.values()])
            )
            self.assertEqual(call.kwargs["params"]["key"], "invented-key")

    def test_malformed_census_responses_are_rejected(self):
        for payload in [
            {"error": "bad"},
            [],
            [["NAME"]],
            [["NAME", "NAME"], ["A", "B"]],
            [[1], ["A"]],
            [["NAME"], []],
            [["NAME"], "not a row"],
        ]:
            with self.subTest(payload=payload):
                response = Mock(headers={"content-type": "application/json"})
                response.json.return_value = payload
                with patch.object(extract.requests, "get", return_value=response):
                    with self.assertRaisesRegex(ValueError, "response structure"):
                        extract.fetch_acs("invented-key")
        response = Mock(headers={"content-type": "text/html"})
        with patch.object(extract.requests, "get", return_value=response):
            with self.assertRaisesRegex(ValueError, "non-JSON"):
                extract.fetch_acs("invented-key")

    def test_census_failures_do_not_leak_raw_messages_or_chained_errors(self):
        private = "https://example.invalid/?key=invented-secret"
        for failure in [
            requests.Timeout(private),
            requests.HTTPError(private),
            ValueError(private),
        ]:
            with self.subTest(exception=type(failure).__name__):
                response = Mock(headers={"content-type": "application/json"})
                if isinstance(failure, requests.RequestException):
                    response.raise_for_status.side_effect = failure
                else:
                    response.json.side_effect = failure
                with patch.object(extract.requests, "get", return_value=response):
                    try:
                        extract.fetch_acs("invented-key")
                    except (RuntimeError, ValueError) as error:
                        rendered = "".join(traceback.format_exception(error))
                        self.assertNotIn(private, rendered)
                        self.assertTrue(error.__suppress_context__)
                    else:
                        self.fail("Expected Census failure")
        with patch.object(
            extract.requests, "get", side_effect=requests.ConnectionError(private)
        ):
            with self.assertRaises(RuntimeError) as caught:
                extract.fetch_acs("invented-key")
        self.assertNotIn(private, "".join(traceback.format_exception(caught.exception)))
        self.assertTrue(caught.exception.__suppress_context__)

    def test_cached_validation_is_offline_and_database_free(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "acs.csv"
            source = zillow_source()
            acs_extract(tuple(source["RegionName"])).to_csv(path, index=False)
            with (
                patch("sys.argv", ["load", "--validate-only", "--acs-file", str(path)]),
                patch.object(pipeline, "read_zillow", return_value=source),
                patch.object(
                    pipeline,
                    "database_settings",
                    side_effect=AssertionError("DB access"),
                ),
                patch.object(
                    pipeline, "load_tables", side_effect=AssertionError("DB write")
                ),
                patch.object(
                    pipeline, "fetch_acs", side_effect=AssertionError("API call")
                ),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(pipeline.main(), 0)
                path.write_text('a,b\n"unterminated', encoding="utf-8")
                self.assertEqual(pipeline.main(), 1)


if __name__ == "__main__":
    unittest.main()
