"""Run the established statistical analysis without a notebook or source downloads."""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
import statsmodels.api as sm
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from sklearn.cluster import KMeans
from sklearn.linear_model import Lasso
from sklearn.metrics import (
    adjusted_rand_score,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
    silhouette_score,
)
from sklearn.model_selection import GridSearchCV, GroupKFold, LeaveOneGroupOut
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from walkability.config import DATA_DIR, PROJECT_ROOT
from walkability.database import read_analysis_data
from walkability.figures import GeometryInputError, save_diagnostics, save_maps
from walkability.prepare import STUDY_AREAS

PREDICTORS = [
    "Walkability_Score",
    "Log_Median_Income",
    "Commute_Min",
    "Rent_Share",
    "College_Grad_Share",
    "Log_Population",
]
CLUSTER_FEATURES = [
    "Walkability_Score",
    "Income_to_Rent",
    "Rent_Share",
    "College_Grad_Share",
]


class StudySampleError(ValueError):
    """The analytical sample cannot support this three-city workflow."""


def fit_ols(
    frame: pd.DataFrame, predictors: list[str], *, city_indicators: bool = False
):
    """Fit the notebook's full-rank OLS specification with HC3 errors."""
    design = frame[predictors].astype(float).copy()
    if city_indicators:
        indicators = pd.get_dummies(
            frame["Study_Area"], prefix="Study_Area", drop_first=True, dtype=float
        )
        design = pd.concat([design, indicators], axis=1)
    design = sm.add_constant(design, has_constant="add")
    if np.linalg.matrix_rank(design.to_numpy()) < design.shape[1]:
        raise ValueError("OLS design is rank deficient; check the input sample.")
    return sm.OLS(frame["Log_ZHVI"], design).fit(cov_type="HC3")


def lasso_search(groups: np.ndarray) -> GridSearchCV:
    """Keep scaling inside the city-grouped penalty-selection folds."""
    return GridSearchCV(
        Pipeline([("scale", StandardScaler()), ("lasso", Lasso(max_iter=100_000))]),
        {"lasso__alpha": np.logspace(-4, 0, 80)},
        scoring="neg_mean_squared_error",
        cv=GroupKFold(n_splits=np.unique(groups).size),
        n_jobs=-1,
    )


def run_analysis(features: pd.DataFrame) -> dict[str, pd.DataFrame | pd.Series]:
    """Fit the fixed study models and return named, exportable tables.

    Input uses database.read_analysis_data's feature contract. Rows are sorted
    by study area and ZIP before fitting. OLS tables use model/term indexes;
    assignments and predictions carry explicit study-area/ZIP keys. Other
    frames contain cluster diagnostics or held-out-city metrics. Series hold
    summary metrics, bootstrap scores and standardized Lasso coefficients.
    The caller owns file output; the input frame is not modified.
    """
    if (
        features["Study_Area"].isna().any()
        or set(features["Study_Area"]) != STUDY_AREAS
    ):
        raise StudySampleError(
            "Analysis requires all three study areas: Chicago, New York City and "
            "Washington DC, with no other or missing labels. Check sample coverage."
        )
    frame = features.sort_values(["Study_Area", "ZIP"]).reset_index(drop=True).copy()
    models = {
        "primary": fit_ols(frame, PREDICTORS, city_indicators=True),
        "sensitivity": fit_ols(
            frame, [*PREDICTORS, "Home_Value_to_Income"], city_indicators=True
        ),
    }
    for city, subset in frame.groupby("Study_Area", sort=True):
        models[city] = fit_ols(subset, PREDICTORS)
    coefficients = pd.concat(
        {
            name: pd.DataFrame(
                {
                    "coefficient": m.params,
                    "HC3_standard_error": m.bse,
                    "p_value": m.pvalues,
                }
            )
            for name, m in models.items()
        },
        names=["model", "term"],
    )
    model_summary = pd.DataFrame.from_dict(
        {
            name: {
                "observations": int(model.nobs),
                "R_squared": model.rsquared,
                "adjusted_R_squared": model.rsquared_adj,
                "condition_number": model.condition_number,
            }
            for name, model in models.items()
        },
        orient="index",
    ).rename_axis("model")

    scaler = StandardScaler()
    scaled = scaler.fit_transform(frame[CLUSTER_FEATURES])
    quality = []
    for k in range(2, 7):
        candidate = KMeans(n_clusters=k, random_state=42, n_init=50)
        labels = candidate.fit_predict(scaled)
        quality.append(
            {
                "k": k,
                "inertia": candidate.inertia_,
                "silhouette": silhouette_score(scaled, labels),
            }
        )
    model = KMeans(n_clusters=3, random_state=42, n_init=50)
    reference = model.fit_predict(scaled)
    rng = np.random.default_rng(42)
    stability = []
    for iteration in range(100):
        indices = rng.choice(len(frame), size=len(frame), replace=True)
        if len(np.unique(indices)) <= 3:
            continue
        labels = KMeans(
            n_clusters=3, random_state=1_000 + iteration, n_init=20
        ).fit_predict(scaled[indices])
        assignments = (
            pd.DataFrame({"Index": indices, "Label": labels})
            .groupby("Index")["Label"]
            .agg(lambda values: values.mode().iat[0])
        )
        stability.append(
            adjusted_rand_score(
                reference[assignments.index.to_numpy()], assignments.to_numpy()
            )
        )

    x = frame[PREDICTORS].astype(float)
    y = frame["Log_ZHVI"].to_numpy()
    groups = frame["Study_Area"].to_numpy()
    predictions = np.full(len(frame), np.nan)
    folds = []
    for train, test in LeaveOneGroupOut().split(x, y, groups):
        search = lasso_search(groups[train])
        search.fit(x.iloc[train], y[train], groups=groups[train])
        predicted = search.predict(x.iloc[test])
        predictions[test] = predicted
        folds.append(
            {
                "city": groups[test][0],
                "rows": len(test),
                "alpha": search.best_params_["lasso__alpha"],
                "MAE": mean_absolute_error(y[test], predicted),
                "RMSE": np.sqrt(mean_squared_error(y[test], predicted)),
                "R_squared": r2_score(y[test], predicted),
            }
        )
    if not np.isfinite(predictions).all():
        raise ValueError("Some observations lack a valid held-out-city prediction.")
    final = lasso_search(groups)
    final.fit(x, y, groups=groups)
    prediction_rows = frame[["Study_Area", "ZIP", "Log_ZHVI"]].copy()
    prediction_rows["Predicted_Log_ZHVI"] = predictions
    metrics = pd.Series(
        {
            "rows": len(frame),
            "flagged_candidates": int(frame["Is_Walkable_and_Affordable"].sum()),
            "primary_score_coefficient": models["primary"].params["Walkability_Score"],
            "primary_HC3_p": models["primary"].pvalues["Walkability_Score"],
            "primary_R_squared": models["primary"].rsquared,
            "bootstrap_median_ARI": float(np.median(stability)),
            "transfer_MAE": mean_absolute_error(y, predictions),
            "transfer_RMSE": np.sqrt(mean_squared_error(y, predictions)),
            "transfer_R_squared": r2_score(y, predictions),
            "final_lasso_alpha": final.best_params_["lasso__alpha"],
        },
        name="value",
    )
    return {
        "metrics": metrics,
        "ols_coefficients": coefficients,
        "ols_summary": model_summary,
        "cluster_quality": pd.DataFrame(quality),
        "cluster_stability": pd.Series(stability, name="ARI"),
        "cluster_assignments": frame[["Study_Area", "ZIP"]].assign(Cluster=reference),
        "cluster_centroids": pd.DataFrame(
            scaler.inverse_transform(model.cluster_centers_), columns=CLUSTER_FEATURES
        ),
        "lasso_folds": pd.DataFrame(folds),
        "lasso_coefficients": pd.Series(
            final.best_estimator_.named_steps["lasso"].coef_,
            index=PREDICTORS,
            name="coefficient",
        ),
        "predictions": prediction_rows,
    }


class OutputDirectoryNotEmpty(ValueError):
    """An export would mix new results with existing files."""


def prepare_output_directory(directory: Path) -> None:
    """Check the final destination without creating or replacing it."""
    if directory.exists() or directory.is_symlink():
        raise OutputDirectoryNotEmpty(
            "Output destination already exists; choose a new --output-dir."
        )
    directory.parent.mkdir(parents=True, exist_ok=True)


def export_analysis(features, rankings, audit, results, directory, geometry_file=None):
    """Write one run into its private staging folder; do not publish it here."""
    for name, frame in {
        **results,
        "city_rankings": rankings,
        "source_audit": audit,
    }.items():
        frame.to_csv(directory / f"{name}.csv", index=True)
    predictions = results["predictions"]
    fig = Figure(figsize=(7, 7))
    FigureCanvasAgg(fig)
    ax = fig.subplots()
    for city, subset in predictions.groupby("Study_Area", sort=True):
        ax.scatter(
            subset["Log_ZHVI"], subset["Predicted_Log_ZHVI"], label=city, alpha=0.75
        )
    limits = predictions[["Log_ZHVI", "Predicted_Log_ZHVI"]].to_numpy()
    ax.plot([limits.min(), limits.max()], [limits.min(), limits.max()], "k--")
    ax.set(
        xlabel="Observed log ZHVI",
        ylabel="Held-out-city predicted log ZHVI",
        title="Leave-one-city-out housing predictions",
    )
    ax.legend()
    fig.tight_layout()
    try:
        fig.savefig(directory / "geographic_transfer.png", dpi=160)
    finally:
        fig.clear()
    save_diagnostics(features, results, directory)
    if geometry_file is not None:
        save_maps(features, geometry_file, directory)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the fixed study models and save tables and a prediction chart."
    )
    parser.add_argument(
        "--output-dir", type=Path, default=PROJECT_ROOT / "outputs" / "analysis"
    )
    parser.add_argument(
        "--maps",
        action="store_true",
        help="Also save city maps; requires local ZCTA geometry.",
    )
    parser.add_argument(
        "--geometry-file",
        type=Path,
        default=DATA_DIR / "geo" / "tl_2024_us_zcta520.shp",
    )
    args = parser.parse_args()
    try:
        # Fail before fitting or exporting if this would mix separate runs.
        prepare_output_directory(args.output_dir)
        features, rankings, audit = read_analysis_data()
        results = run_analysis(features)
        # A sibling directory keeps the final rename on the same filesystem.
        with TemporaryDirectory(
            prefix=f".{args.output_dir.name}-incomplete-", dir=args.output_dir.parent
        ) as temporary:
            staging = Path(temporary) / "results"
            staging.mkdir()
            export_analysis(
                features,
                rankings,
                audit,
                results,
                staging,
                args.geometry_file if args.maps else None,
            )
            prepare_output_directory(args.output_dir)
            staging.rename(args.output_dir)
        print(results["metrics"].to_string())
        print(
            "Analysis complete. Result tables and figures saved in the output directory."
        )
        return 0
    except OSError:
        print(
            "Could not save the analysis. Check directory permissions and disk space; this run was not published."
        )
        return 1
    except OutputDirectoryNotEmpty:
        print("Output destination already exists; choose a new --output-dir.")
        return 1
    except (StudySampleError, GeometryInputError) as error:
        # These application errors contain only fixed, safe guidance.
        print(str(error))
        return 1
    except ValueError:
        print("Analysis failed. Check the study sample and geometry before retrying.")
        return 1
    except RuntimeError:
        print(
            "Analysis failed. Check PostgreSQL setup and the study sample before retrying."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
