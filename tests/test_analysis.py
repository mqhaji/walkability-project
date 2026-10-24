"""Small offline checks; run with python -m unittest discover -s tests."""

import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline

from walkability import analysis


class AnalysisTests(unittest.TestCase):
    def test_ols_rejects_duplicate_predictors(self):
        frame = pd.DataFrame({"x": [1., 2., 3.], "copy": [1., 2., 3.], "Log_ZHVI": [2., 3., 4.]})
        with self.assertRaisesRegex(ValueError, "rank deficient"):
            analysis.fit_ols(frame, ["x", "copy"])

    def test_ols_uses_hc3_and_city_indicators(self):
        rng = np.random.default_rng(42)
        frame = pd.DataFrame({
            "x": rng.normal(size=30),
            "Study_Area": np.repeat(["Chicago", "New York City", "Washington DC"], 10),
            "Log_ZHVI": rng.normal(size=30),
        })
        model = analysis.fit_ols(frame, ["x"], city_indicators=True)
        self.assertEqual(model.cov_type, "HC3")
        self.assertEqual(model.model.exog_names, [
            "const", "x", "Study_Area_New York City", "Study_Area_Washington DC",
        ])

    def test_lasso_keeps_scaling_inside_grouped_search(self):
        search = analysis.lasso_search(np.array(["A", "A", "B", "B"]))
        self.assertIsInstance(search.estimator, Pipeline)
        self.assertIsInstance(search.cv, GroupKFold)
        self.assertEqual(search.cv.n_splits, 2)
        self.assertEqual(search.estimator.named_steps["lasso"].max_iter, 100_000)
        np.testing.assert_array_equal(search.param_grid["lasso__alpha"], np.logspace(-4, 0, 80))

    def test_database_failure_is_sanitized(self):
        output = io.StringIO()
        with TemporaryDirectory() as directory, \
                patch("sys.argv", ["walkability-analyze", "--output-dir", str(Path(directory) / "run")]), \
                patch.object(analysis, "read_analysis_data", side_effect=RuntimeError("private connection details")), \
                redirect_stdout(output):
            self.assertEqual(analysis.main(), 1)
        self.assertNotIn("private connection details", output.getvalue())
        self.assertIn("PostgreSQL", output.getvalue())

    def test_existing_outputs_are_preserved_before_database_access(self):
        with TemporaryDirectory() as directory:
            marker = Path(directory) / "previous.csv"
            marker.write_text("previous results", encoding="utf-8")
            with patch("sys.argv", ["walkability-analyze", "--output-dir", directory]), \
                    patch.object(analysis, "read_analysis_data") as reader, \
                    redirect_stdout(io.StringIO()):
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
            with patch("sys.argv", ["walkability-analyze", "--output-dir", str(destination)]), \
                    patch.object(analysis, "read_analysis_data", return_value=(None, None, None)), \
                    patch.object(analysis, "run_analysis", return_value={}), \
                    patch.object(analysis, "export_analysis", side_effect=fail_export), \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(analysis.main(), 1)
            self.assertEqual(list(Path(root).iterdir()), [marker])

    def test_success_publishes_only_completed_results(self):
        def export(features, rankings, audit, results, directory, geometry_file):
            self.assertFalse(destination.exists())
            (directory / "complete.csv").write_text("complete", encoding="utf-8")

        with TemporaryDirectory() as root:
            destination = Path(root) / "run"
            with patch("sys.argv", ["walkability-analyze", "--output-dir", str(destination)]), \
                    patch.object(analysis, "read_analysis_data", return_value=(None, None, None)), \
                    patch.object(analysis, "run_analysis", return_value={"metrics": pd.Series([1.])}), \
                    patch.object(analysis, "export_analysis", side_effect=export), \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(analysis.main(), 0)
            self.assertEqual(list(Path(root).iterdir()), [destination])
            self.assertEqual((destination / "complete.csv").read_text(), "complete")

    def test_empty_existing_destination_is_not_replaced(self):
        with TemporaryDirectory() as root:
            with self.assertRaises(analysis.OutputDirectoryNotEmpty):
                analysis.prepare_output_directory(Path(root))


if __name__ == "__main__":
    unittest.main()