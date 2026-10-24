"""Small offline checks; run with python -m unittest discover -s tests."""

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline

from walkability import analysis


class AnalysisTests(unittest.TestCase):
    def test_study_area_check_happens_before_any_fit(self):
        for cities in [
            ["Chicago", "New York City"],
            ["Chicago", "New York City", "Washington DC", "Other"],
            ["Chicago", "New York City", "Washington DC", None],
            [],
        ]:
            with self.subTest(cities=cities):
                frame = pd.DataFrame({"Study_Area": cities})
                with patch.object(
                    analysis, "fit_ols", side_effect=AssertionError("fit started")
                ) as fit:
                    with self.assertRaisesRegex(ValueError, "all three study areas"):
                        analysis.run_analysis(frame)
                    fit.assert_not_called()

    def test_ols_rejects_duplicate_predictors(self):
        frame = pd.DataFrame(
            {"x": [1.0, 2.0, 3.0], "copy": [1.0, 2.0, 3.0], "Log_ZHVI": [2.0, 3.0, 4.0]}
        )
        with self.assertRaisesRegex(ValueError, "rank deficient"):
            analysis.fit_ols(frame, ["x", "copy"])

    def test_ols_uses_hc3_and_city_indicators(self):
        rng = np.random.default_rng(42)
        frame = pd.DataFrame(
            {
                "x": rng.normal(size=30),
                "Study_Area": np.repeat(
                    ["Chicago", "New York City", "Washington DC"], 10
                ),
                "Log_ZHVI": rng.normal(size=30),
            }
        )
        model = analysis.fit_ols(frame, ["x"], city_indicators=True)
        self.assertEqual(model.cov_type, "HC3")
        self.assertEqual(
            model.model.exog_names,
            [
                "const",
                "x",
                "Study_Area_New York City",
                "Study_Area_Washington DC",
            ],
        )

    def test_lasso_keeps_scaling_inside_grouped_search(self):
        search = analysis.lasso_search(np.array(["A", "A", "B", "B"]))
        self.assertIsInstance(search.estimator, Pipeline)
        self.assertIsInstance(search.cv, GroupKFold)
        self.assertEqual(search.cv.n_splits, 2)
        self.assertEqual(search.estimator.named_steps["lasso"].max_iter, 100_000)
        np.testing.assert_array_equal(
            search.param_grid["lasso__alpha"], np.logspace(-4, 0, 80)
        )

    def test_database_failure_is_sanitized(self):
        output = io.StringIO()
        with (
            TemporaryDirectory() as directory,
            patch(
                "sys.argv",
                ["walkability-analyze", "--output-dir", str(Path(directory) / "run")],
            ),
            patch.object(
                analysis,
                "read_analysis_data",
                side_effect=RuntimeError("private connection details"),
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(analysis.main(), 1)
        self.assertNotIn("private connection details", output.getvalue())
        self.assertIn("PostgreSQL", output.getvalue())

    def test_existing_outputs_are_preserved_before_database_access(self):
        with TemporaryDirectory() as directory:
            marker = Path(directory) / "previous.csv"
            marker.write_text("previous results", encoding="utf-8")
            with (
                patch("sys.argv", ["walkability-analyze", "--output-dir", directory]),
                patch.object(analysis, "read_analysis_data") as reader,
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(analysis.main(), 1)
                reader.assert_not_called()
            self.assertEqual(marker.read_text(encoding="utf-8"), "previous results")

    def test_failed_export_removes_only_its_temporary_files(self):
        def fail_export(features, rankings, audit, results, directory, geometry_file):
            (directory / "partial.csv").write_text("partial", encoding="utf-8")
            raise OSError("simulated full disk")

        with TemporaryDirectory() as root:
            destination = Path(root) / "run"
            marker = Path(root) / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            with (
                patch(
                    "sys.argv",
                    ["walkability-analyze", "--output-dir", str(destination)],
                ),
                patch.object(
                    analysis, "read_analysis_data", return_value=(None, None, None)
                ),
                patch.object(analysis, "run_analysis", return_value={}),
                patch.object(analysis, "export_analysis", side_effect=fail_export),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(analysis.main(), 1)
            self.assertEqual(list(Path(root).iterdir()), [marker])

    def test_success_publishes_only_completed_results(self):
        def export(features, rankings, audit, results, directory, geometry_file):
            self.assertFalse(destination.exists())
            (directory / "complete.csv").write_text("complete", encoding="utf-8")

        with TemporaryDirectory() as root:
            destination = Path(root) / "run"
            with (
                patch(
                    "sys.argv",
                    ["walkability-analyze", "--output-dir", str(destination)],
                ),
                patch.object(
                    analysis, "read_analysis_data", return_value=(None, None, None)
                ),
                patch.object(
                    analysis, "run_analysis", return_value={"metrics": pd.Series([1.0])}
                ),
                patch.object(analysis, "export_analysis", side_effect=export),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(analysis.main(), 0)
            self.assertEqual(list(Path(root).iterdir()), [destination])
            self.assertEqual((destination / "complete.csv").read_text(), "complete")

    def test_empty_existing_destination_is_not_replaced(self):
        with TemporaryDirectory() as root:
            with self.assertRaises(analysis.OutputDirectoryNotEmpty):
                analysis.prepare_output_directory(Path(root))

    def test_missing_city_cli_error_is_clear_and_stops_before_fitting(self):
        frame = pd.DataFrame({"Study_Area": ["Chicago", "New York City"]})
        output = io.StringIO()
        with TemporaryDirectory() as root:
            destination = Path(root) / "run"
            with (
                patch("sys.argv", ["analyze", "--output-dir", str(destination)]),
                patch.object(
                    analysis, "read_analysis_data", return_value=(frame, None, None)
                ),
                patch.object(
                    analysis, "fit_ols", side_effect=AssertionError("fit started")
                ),
                redirect_stdout(output),
            ):
                self.assertEqual(analysis.main(), 1)
            self.assertEqual(list(Path(root).iterdir()), [])
        self.assertIn("all three study areas", output.getvalue())
        self.assertNotIn("PostgreSQL", output.getvalue())

    def export_results(self):
        return {
            "metrics": pd.Series([3.0], index=["rows"], name="value"),
            "predictions": pd.DataFrame(
                {
                    "Study_Area": ["Chicago", "New York City", "Washington DC"],
                    "Log_ZHVI": [12.0, 13.0, 14.0],
                    "Predicted_Log_ZHVI": [12.1, 13.1, 14.1],
                }
            ),
        }

    def test_geometry_cli_failures_are_safe_and_not_published(self):
        for kind in ["missing", "corrupt"]:
            with self.subTest(kind=kind), TemporaryDirectory() as root:
                geometry = Path(root) / f"{kind}.shp"
                if kind == "corrupt":
                    geometry.write_text("not geometry", encoding="utf-8")
                destination = Path(root) / "run"
                output = io.StringIO()
                with (
                    patch(
                        "sys.argv",
                        [
                            "analyze",
                            "--maps",
                            "--geometry-file",
                            str(geometry),
                            "--output-dir",
                            str(destination),
                        ],
                    ),
                    patch.object(
                        analysis,
                        "read_analysis_data",
                        return_value=(pd.DataFrame(), pd.DataFrame(), pd.DataFrame()),
                    ),
                    patch.object(
                        analysis, "run_analysis", return_value=self.export_results()
                    ),
                    patch.object(analysis, "save_diagnostics"),
                    redirect_stdout(output),
                ):
                    self.assertEqual(analysis.main(), 1)
                self.assertIn("Could not read ZCTA geometry", output.getvalue())
                self.assertNotIn("PostgreSQL", output.getvalue())
                self.assertNotIn(root, output.getvalue())
                self.assertFalse(destination.exists())
                self.assertEqual(
                    list(Path(root).iterdir()), [geometry] if kind == "corrupt" else []
                )

    def test_plot_save_failure_remains_an_output_error(self):
        output = io.StringIO()
        with TemporaryDirectory() as root:
            destination = Path(root) / "run"
            with (
                patch(
                    "sys.argv", ["analyze", "--maps", "--output-dir", str(destination)]
                ),
                patch.object(
                    analysis,
                    "read_analysis_data",
                    return_value=(pd.DataFrame(), pd.DataFrame(), pd.DataFrame()),
                ),
                patch.object(
                    analysis, "run_analysis", return_value=self.export_results()
                ),
                patch.object(
                    analysis.Figure,
                    "savefig",
                    side_effect=OSError("private failed path"),
                ),
                redirect_stdout(output),
            ):
                self.assertEqual(analysis.main(), 1)
            self.assertEqual(list(Path(root).iterdir()), [])
        self.assertIn("Could not save the analysis", output.getvalue())
        self.assertNotIn("private failed path", output.getvalue())
        self.assertNotIn("geometry", output.getvalue())

    def test_no_map_run_never_reads_geometry(self):
        with TemporaryDirectory() as root:
            destination = Path(root) / "run"
            with (
                patch(
                    "sys.argv",
                    [
                        "analyze",
                        "--geometry-file",
                        "absent.shp",
                        "--output-dir",
                        str(destination),
                    ],
                ),
                patch.object(
                    analysis,
                    "read_analysis_data",
                    return_value=(pd.DataFrame(), pd.DataFrame(), pd.DataFrame()),
                ),
                patch.object(
                    analysis, "run_analysis", return_value=self.export_results()
                ),
                patch.object(analysis, "save_diagnostics"),
                patch.object(
                    analysis, "save_maps", side_effect=AssertionError("geometry read")
                ) as maps,
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(analysis.main(), 0)
                maps.assert_not_called()
            self.assertTrue((destination / "geographic_transfer.png").is_file())


if __name__ == "__main__":
    unittest.main()
