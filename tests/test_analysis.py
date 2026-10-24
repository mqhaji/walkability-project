"""Small offline checks; run with python -m unittest discover -s tests."""

import io
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
        with patch("sys.argv", ["walkability-analyze"]), \
                patch.object(analysis, "read_analysis_data", side_effect=RuntimeError("private connection details")), \
                redirect_stdout(output):
            self.assertEqual(analysis.main(), 1)
        self.assertNotIn("private connection details", output.getvalue())
        self.assertIn("PostgreSQL", output.getvalue())


if __name__ == "__main__":
    unittest.main()