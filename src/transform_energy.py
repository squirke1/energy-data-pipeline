import logging
from typing import ClassVar

import pandas as pd

try:
    from src.config import LOG_DATE_FORMAT, LOG_FORMAT, LOG_LEVEL
except ImportError:
    from config import LOG_DATE_FORMAT, LOG_FORMAT, LOG_LEVEL

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
logger = logging.getLogger(__name__)


class GenerationTransformer:
    RENEWABLE_SOURCES: ClassVar[set[str]] = {
        "Wind Onshore",
        "Wind Offshore",
        "Solar",
        "Hydro Run-of-river and poundage",
        "Hydro Run-of-river",
        "Hydro Water Reservoir",
        "Geothermal",
        "Biomass",
        "Marine",
        "Wind",
        "Hydro",
    }

    # gCO2eq per kWh by fuel type
    FOSSIL_CO2_INTENSITY: ClassVar[dict[str, int]] = {
        "Fossil Gas": 490,
        "Fossil Hard coal": 820,
        "Fossil Brown coal/Lignite": 1050,
        "Fossil Oil": 650,
        "Fossil Peat": 900,
        "Nuclear": 12,
    }

    def melt_generation_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """Reshape wide ENTSOE generation DataFrame (index=timestamp, cols=fuel) to long format."""
        numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        meta_cols = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]

        df_reset = df.reset_index()
        timestamp_col = df_reset.columns[0]

        long_df = df_reset.melt(
            id_vars=[timestamp_col] + meta_cols,
            value_vars=numeric_cols,
            var_name="fuel_type",
            value_name="generation_mw",
        )
        long_df = long_df.rename(columns={timestamp_col: "timestamp"})
        long_df = long_df.dropna(subset=["generation_mw"])
        long_df["generation_mw"] = long_df["generation_mw"].clip(lower=0)
        return long_df.reset_index(drop=True)

    def add_renewable_flag(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["is_renewable"] = df["fuel_type"].isin(self.RENEWABLE_SOURCES)
        return df

    def compute_generation_summary(self, df: pd.DataFrame) -> pd.DataFrame:
        group_cols = ["timestamp"]
        if "country_code" in df.columns:
            group_cols.append("country_code")

        total = df.groupby(group_cols)["generation_mw"].sum().rename("total_generation_mw")
        renewable = (
            df[df["is_renewable"]]
            .groupby(group_cols)["generation_mw"]
            .sum()
            .rename("renewable_mw")
        )

        summary = (
            total.to_frame()
            .join(renewable, how="left")
            .fillna({"renewable_mw": 0.0})
            .reset_index()
        )
        summary["renewable_pct"] = (
            summary["renewable_mw"]
            / summary["total_generation_mw"].where(summary["total_generation_mw"] > 0)
            * 100
        ).round(2)
        return summary

    def compute_carbon_intensity(self, long_df: pd.DataFrame) -> pd.Series:
        """Return carbon intensity (gCO2eq/kWh) per timestamp, indexed by group cols."""
        df = long_df.copy()
        df["co2_intensity"] = df["fuel_type"].map(self.FOSSIL_CO2_INTENSITY).fillna(0)
        df["co2_contribution"] = df["generation_mw"] * df["co2_intensity"]

        group_cols = ["timestamp"]
        if "country_code" in df.columns:
            group_cols.append("country_code")

        totals = df.groupby(group_cols).agg(
            total_mw=("generation_mw", "sum"),
            total_co2=("co2_contribution", "sum"),
        )
        totals["carbon_intensity_g_per_kwh"] = (
            totals["total_co2"] / totals["total_mw"].where(totals["total_mw"] > 0)
        ).round(1)
        return totals["carbon_intensity_g_per_kwh"]

    def transform_entsoe_generation(
        self, df: pd.DataFrame
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Transform raw wide ENTSOE DataFrame → (long_df, summary_df)."""
        logger.info(f"Transforming ENTSOE generation data ({len(df)} rows)")

        long_df = self.melt_generation_df(df)
        long_df = self.add_renewable_flag(long_df)
        long_df["processed_at"] = pd.Timestamp.now(tz="UTC")

        summary_df = self.compute_generation_summary(long_df)
        carbon_intensity = self.compute_carbon_intensity(long_df)

        merge_cols = ["timestamp"]
        if "country_code" in summary_df.columns:
            merge_cols.append("country_code")

        summary_df = summary_df.merge(carbon_intensity.reset_index(), on=merge_cols, how="left")
        summary_df["processed_at"] = pd.Timestamp.now(tz="UTC")

        logger.info(
            f"Transformed to {len(long_df)} long rows, {len(summary_df)} summary rows"
        )
        return long_df, summary_df
