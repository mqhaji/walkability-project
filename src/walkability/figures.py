"""Save study figures without opening a notebook or a display window."""

from pathlib import Path

import pandas as pd
import seaborn as sns
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure


class GeometryInputError(ValueError):
    """Missing, unreadable or incomplete geometry for the requested maps."""


def _figure(size: tuple[float, float]) -> Figure:
    figure = Figure(figsize=size)
    FigureCanvasAgg(figure)
    return figure


def _save(figure: Figure, destination: Path, caption: str) -> None:
    figure.text(0.5, 0.02, caption, ha="center", va="bottom", fontsize=9, wrap=True)
    figure.tight_layout(rect=(0, 0.13, 1, 1))
    try:
        figure.savefig(destination, dpi=160)
    finally:
        figure.clear()


def save_diagnostics(
    features: pd.DataFrame,
    results: dict[str, pd.DataFrame | pd.Series],
    output_dir: Path,
) -> None:
    """Save four charts from run_analysis results without refitting models.

    The caller supplies an existing output directory. Cluster assignments must
    match the feature keys exactly; missing rows must not disappear in a plot.
    """
    clustered = features.merge(
        results["cluster_assignments"], on=["Study_Area", "ZIP"], validate="one_to_one"
    )
    if len(clustered) != len(features) or len(clustered) != len(
        results["cluster_assignments"]
    ):
        raise ValueError(
            "Cluster assignments must cover every analytical observation exactly once."
        )
    columns = [
        "Log_ZHVI",
        "Walkability_Score",
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
    figure = _figure((12, 10))
    ax = figure.subplots()
    sns.heatmap(
        features[columns].corr(),
        annot=True,
        cmap="coolwarm",
        fmt=".2f",
        square=True,
        cbar_kws={"shrink": 0.7},
        ax=ax,
    )
    ax.set_title("Housing and mobility correlations")
    _save(
        figure,
        output_dir / "correlations.png",
        "Pairwise associations describe this sample; they do not establish causal effects.",
    )

    figure = _figure((11, 5))
    axes = figure.subplots(1, 2)
    quality = results["cluster_quality"]
    panels = [("inertia", "KMeans dispersion"), ("silhouette", "KMeans separation")]
    for ax, (column, title) in zip(axes, panels):
        ax.plot(quality["k"], quality[column], marker="o")
        ax.set(title=title, xlabel="Number of clusters", ylabel=column.capitalize())
    _save(
        figure,
        output_dir / "cluster_diagnostics.png",
        "Compare dispersion and separation across candidate cluster counts; clustering is exploratory.",
    )

    figure = _figure((10, 7))
    ax = figure.subplots()
    sns.scatterplot(
        data=clustered,
        x="Walkability_Score",
        y="Log_ZHVI",
        hue="Cluster",
        palette="Set2",
        s=60,
        edgecolor="k",
        ax=ax,
    )
    ax.set(
        title="Exploratory ZIP/ZCTA profiles",
        xlabel="Walkability score",
        ylabel="Log ZHVI",
    )
    _save(
        figure,
        output_dir / "cluster_profiles.png",
        "Colors identify four-feature KMeans profiles, not ranked neighborhood types or causal groups.",
    )

    figure = _figure((9, 7))
    ax = figure.subplots()
    results["lasso_coefficients"].sort_values().plot.barh(ax=ax)
    ax.axvline(0, color="black", linewidth=1)
    ax.set(
        title="Lasso coefficients after city-grouped penalty selection",
        xlabel="Coefficient on standardized predictor",
    )
    _save(
        figure,
        output_dir / "lasso_coefficients.png",
        "Full-sample coefficients describe the fitted model; held-out-city predictions measure transfer.",
    )


def save_maps(features: pd.DataFrame, geometry_path: Path, output_dir: Path) -> int:
    """Require one geometry per observation and use a shared color range."""
    import geopandas as gpd

    try:
        geometry = gpd.read_file(geometry_path)
    except (OSError, RuntimeError, ValueError):
        raise GeometryInputError(
            "Could not read ZCTA geometry. Check --geometry-file and keep the "
            "shapefile and its sidecar files together; see README.md."
        ) from None
    if "ZCTA5CE20" not in geometry:
        raise GeometryInputError("Geometry must contain the ZCTA5CE20 field.")
    geometry["ZIP"] = geometry["ZCTA5CE20"].astype("string").str.zfill(5)
    geometry = geometry.loc[geometry["ZIP"].isin(features["ZIP"]), ["ZIP", "geometry"]]
    if geometry["ZIP"].duplicated().any() or set(geometry["ZIP"]) != set(
        features["ZIP"]
    ):
        raise GeometryInputError(
            "Each analytical ZCTA must match exactly one geometry."
        )
    mapped = geometry.merge(features, on="ZIP", validate="one_to_one")
    if mapped.geometry.isna().any() or mapped.geometry.is_empty.any():
        raise GeometryInputError("Analytical ZCTAs must have nonempty geometry.")
    if not mapped.geometry.is_valid.all():
        raise GeometryInputError(
            "Analytical ZCTAs contain invalid geometry; check the source file."
        )
    low, high = features["Walkability_Score"].agg(["min", "max"])
    cities = [
        ("Chicago", "chicago"),
        ("New York City", "new_york_city"),
        ("Washington DC", "washington_dc"),
    ]
    for city, slug in cities:
        subset = mapped.loc[mapped["Study_Area"].eq(city)]
        if subset.empty:
            raise GeometryInputError("A study area has no mapped observations.")
        figure = _figure((8, 8))
        ax = figure.subplots()
        subset.plot(
            column="Walkability_Score",
            cmap="YlGnBu",
            linewidth=0.3,
            edgecolor="white",
            legend=True,
            vmin=low,
            vmax=high,
            ax=ax,
        )
        ax.set_title(f"Commute-mode walkability in {city}")
        ax.set_axis_off()
        _save(
            figure,
            output_dir / f"map_{slug}.png",
            "Retained ZCTAs use the same score scale across cities; boundaries do not define neighborhoods.",
        )
    return len(mapped)
