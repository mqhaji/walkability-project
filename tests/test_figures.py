"""Figure checks use tiny invented geometries, not downloaded study data."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from walkability.figures import _figure, _save, save_diagnostics, save_maps


class FigureTests(unittest.TestCase):
    def setUp(self):
        self.features = pd.DataFrame(
            {
                "ZIP": ["60601", "10001", "20001"],
                "Study_Area": ["Chicago", "New York City", "Washington DC"],
                "Walkability_Score": [0.1, 0.3, 0.2],
            }
        )
        self.geometry = gpd.GeoDataFrame(
            {"ZCTA5CE20": self.features["ZIP"]},
            geometry=[box(i, 0, i + 0.5, 0.5) for i in range(3)],
            crs="EPSG:4326",
        )

    def test_maps_cover_sample_and_share_scale(self):
        scales = []
        # Inspect the actual plotting arguments without replacing GeoPandas rendering.
        from geopandas.plotting import GeoplotAccessor

        actual_call = GeoplotAccessor.__call__

        def record(accessor, *args, **kwargs):
            scales.append((kwargs["vmin"], kwargs["vmax"]))
            return actual_call(accessor, *args, **kwargs)

        with (
            TemporaryDirectory() as directory,
            patch("geopandas.read_file", return_value=self.geometry.copy()),
            patch.object(GeoplotAccessor, "__call__", record),
        ):
            self.assertEqual(
                save_maps(self.features, Path("unused.shp"), Path(directory)), 3
            )
            self.assertEqual(scales, [(0.1, 0.3)] * 3)
            images = list(Path(directory).glob("map_*.png"))
            self.assertEqual(len(images), 3)
            for image in images:
                self.assertTrue(image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))

    def test_missing_geometry_is_rejected(self):
        with patch("geopandas.read_file", return_value=self.geometry.iloc[:2].copy()):
            with self.assertRaisesRegex(ValueError, "exactly one geometry"):
                save_maps(self.features, Path("unused.shp"), Path("unused"))

    def test_missing_or_corrupt_file_has_safe_geometry_error(self):
        with TemporaryDirectory() as directory:
            for name in ["missing.shp", "corrupt.shp"]:
                path = Path(directory) / name
                if name == "corrupt.shp":
                    path.write_text("not a shapefile", encoding="utf-8")
                with self.subTest(name=name):
                    with self.assertRaisesRegex(
                        ValueError, "Could not read ZCTA geometry"
                    ) as caught:
                        save_maps(self.features, path, Path(directory))
                    self.assertNotIn(directory, str(caught.exception))
                    self.assertTrue(caught.exception.__suppress_context__)

    def test_empty_geometry_is_rejected(self):
        self.geometry.loc[0, "geometry"] = None
        with patch("geopandas.read_file", return_value=self.geometry):
            with self.assertRaisesRegex(ValueError, "nonempty geometry"):
                save_maps(self.features, Path("unused.shp"), Path("unused"))

    def test_failed_save_clears_figure(self):
        figure = _figure((2, 2))
        figure.subplots().plot([0, 1])
        with patch.object(figure, "savefig", side_effect=OSError("full disk")):
            with self.assertRaises(OSError):
                _save(figure, Path("unused.png"), "Test caption")
        self.assertEqual(len(figure.axes), 0)

    def diagnostic_fixture(self):
        rng = np.random.default_rng(42)
        columns = [
            "Log_ZHVI",
            "Income_to_Rent",
            "Home_Value_to_Income",
            "Walk_Share",
            "Transit_Share",
            "Bike_Share",
            "Car_Share",
            "Commute_Min",
            "Rent_Share",
            "Owner_Share",
            "College_Grad_Share",
            "Population_k",
        ]
        features = self.features.copy()
        for column in columns:
            features[column] = rng.normal(size=len(features))
        results = {
            "cluster_assignments": features[["Study_Area", "ZIP"]].assign(
                Cluster=[0, 1, 2]
            ),
            "cluster_quality": pd.DataFrame(
                {"k": [2, 3], "inertia": [4.0, 2.0], "silhouette": [0.2, 0.3]}
            ),
            "lasso_coefficients": pd.Series([0.1, -0.2], index=["Income", "Score"]),
        }
        return features, results

    def test_diagnostic_charts_render_without_mutating_inputs(self):
        features, results = self.diagnostic_fixture()
        original = features.copy(deep=True)
        with TemporaryDirectory() as directory:
            save_diagnostics(features, results, Path(directory))
            self.assertEqual(
                {p.name for p in Path(directory).glob("*.png")},
                {
                    "correlations.png",
                    "cluster_diagnostics.png",
                    "cluster_profiles.png",
                    "lasso_coefficients.png",
                },
            )
            for image in Path(directory).glob("*.png"):
                self.assertTrue(image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
        pd.testing.assert_frame_equal(features, original)

    def test_incomplete_clusters_fail_before_writing_charts(self):
        features, results = self.diagnostic_fixture()
        results["cluster_assignments"] = results["cluster_assignments"].iloc[:2]
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "every analytical observation"):
                save_diagnostics(features, results, Path(directory))
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
