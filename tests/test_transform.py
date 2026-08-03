import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from transform_energy import (
    add_renewable_flag,
    compute_carbon_intensity,
    compute_generation_summary,
    melt_generation_df,
    transform_eirgrid_generation,
    transform_entsoe_generation,
)


@pytest.fixture
def sample_wide_df():
    timestamps = pd.date_range("2024-01-01", periods=4, freq="15min", tz="Europe/Dublin")
    return pd.DataFrame(
        {
            "Fossil Gas": [800.0, 820.0, 810.0, 790.0],
            "Wind Onshore": [500.0, 520.0, 480.0, 510.0],
            "Hydro Run-of-river": [50.0, 55.0, 48.0, 52.0],
            "country_code": ["IE"] * 4,
        },
        index=timestamps,
    )


@pytest.fixture
def sample_long_df():
    timestamps = pd.to_datetime(["2024-01-01"] * 3)
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "country_code": ["IE"] * 3,
            "fuel_type": ["Fossil Gas", "Wind Onshore", "Solar"],
            "generation_mw": [800.0, 500.0, 100.0],
            "is_renewable": [False, True, True],
        }
    )


class TestMeltGenerationDf:
    def test_output_columns(self, sample_wide_df):
        result = melt_generation_df(sample_wide_df)
        assert "timestamp" in result.columns
        assert "fuel_type" in result.columns
        assert "generation_mw" in result.columns

    def test_row_count(self, sample_wide_df):
        result = melt_generation_df(sample_wide_df)
        # 4 timestamps × 3 numeric fuel columns = 12 rows
        assert len(result) == 12

    def test_negative_values_clipped(self, sample_wide_df):
        sample_wide_df = sample_wide_df.copy()
        sample_wide_df.iloc[0, 0] = -100.0
        result = melt_generation_df(sample_wide_df)
        assert (result["generation_mw"] >= 0).all()

    def test_nulls_dropped(self, sample_wide_df):
        sample_wide_df = sample_wide_df.copy()
        sample_wide_df.iloc[0, 0] = None
        result = melt_generation_df(sample_wide_df)
        assert result["generation_mw"].isna().sum() == 0

    def test_meta_columns_preserved(self, sample_wide_df):
        result = melt_generation_df(sample_wide_df)
        assert "country_code" in result.columns


class TestAddRenewableFlag:
    def test_wind_flagged_renewable(self, sample_long_df):
        result = add_renewable_flag(sample_long_df)
        assert result.loc[result["fuel_type"] == "Wind Onshore", "is_renewable"].all()

    def test_solar_flagged_renewable(self, sample_long_df):
        result = add_renewable_flag(sample_long_df)
        assert result.loc[result["fuel_type"] == "Solar", "is_renewable"].all()

    def test_fossil_gas_not_renewable(self, sample_long_df):
        result = add_renewable_flag(sample_long_df)
        assert not result.loc[result["fuel_type"] == "Fossil Gas", "is_renewable"].any()

    def test_column_is_bool(self, sample_long_df):
        result = add_renewable_flag(sample_long_df)
        assert result["is_renewable"].dtype == bool


class TestComputeGenerationSummary:
    def test_total_generation(self, sample_long_df):
        result = compute_generation_summary(sample_long_df)
        assert result["total_generation_mw"].iloc[0] == pytest.approx(1400.0)

    def test_renewable_mw(self, sample_long_df):
        result = compute_generation_summary(sample_long_df)
        assert result["renewable_mw"].iloc[0] == pytest.approx(600.0)

    def test_renewable_pct(self, sample_long_df):
        result = compute_generation_summary(sample_long_df)
        expected = round(600 / 1400 * 100, 2)
        assert result["renewable_pct"].iloc[0] == pytest.approx(expected)

    def test_grouped_by_timestamp(self, sample_long_df):
        # Add second timestamp
        second = sample_long_df.copy()
        second["timestamp"] = pd.to_datetime(["2024-01-02"] * 3)
        combined = pd.concat([sample_long_df, second], ignore_index=True)
        result = compute_generation_summary(combined)
        assert len(result) == 2

    def test_zero_total_yields_null_pct(self):
        df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(["2024-01-01"]),
                "country_code": ["IE"],
                "fuel_type": ["Fossil Gas"],
                "generation_mw": [0.0],
                "is_renewable": [False],
            }
        )
        result = compute_generation_summary(df)
        assert pd.isna(result["renewable_pct"].iloc[0])


class TestComputeCarbonIntensity:
    def test_returns_series(self, sample_long_df):
        result = compute_carbon_intensity(sample_long_df)
        assert isinstance(result, pd.Series)

    def test_fossil_gas_contributes(self, sample_long_df):
        result = compute_carbon_intensity(sample_long_df)
        # 800 MW gas × 490 gCO2/kWh / 1400 total MW
        expected = round(800 * 490 / 1400, 1)
        assert result.iloc[0] == pytest.approx(expected)


class TestTransformEntsoeGeneration:
    def test_returns_two_dataframes(self, sample_wide_df):
        long_df, summary_df = transform_entsoe_generation(sample_wide_df)
        assert isinstance(long_df, pd.DataFrame)
        assert isinstance(summary_df, pd.DataFrame)

    def test_long_df_required_columns(self, sample_wide_df):
        long_df, _ = transform_entsoe_generation(sample_wide_df)
        for col in ("timestamp", "fuel_type", "generation_mw", "is_renewable", "processed_at"):
            assert col in long_df.columns

    def test_summary_has_renewable_pct(self, sample_wide_df):
        _, summary_df = transform_entsoe_generation(sample_wide_df)
        assert "renewable_pct" in summary_df.columns

    def test_summary_has_carbon_intensity(self, sample_wide_df):
        _, summary_df = transform_entsoe_generation(sample_wide_df)
        assert "carbon_intensity_g_per_kwh" in summary_df.columns

    def test_summary_row_count_matches_timestamps(self, sample_wide_df):
        _, summary_df = transform_entsoe_generation(sample_wide_df)
        assert len(summary_df) == 4


class TestTransformEirgridGeneration:
    @pytest.fixture
    def eirgrid_data(self):
        return {
            "Rows": [
                {"FieldName": "Wind", "Value": "1000"},
                {"FieldName": "Gas", "Value": "2000"},
                {"FieldName": "Solar", "Value": "100"},
            ],
            "Status": "OK",
        }

    def test_returns_two_dataframes(self, eirgrid_data):
        long_df, summary_df = transform_eirgrid_generation(eirgrid_data)
        assert isinstance(long_df, pd.DataFrame)
        assert isinstance(summary_df, pd.DataFrame)

    def test_long_df_row_count(self, eirgrid_data):
        long_df, _ = transform_eirgrid_generation(eirgrid_data)
        assert len(long_df) == 3

    def test_summary_has_renewable_pct(self, eirgrid_data):
        _, summary_df = transform_eirgrid_generation(eirgrid_data)
        assert "renewable_pct" in summary_df.columns

    def test_empty_rows_raises(self):
        with pytest.raises(ValueError, match="No rows"):
            transform_eirgrid_generation({"Rows": []})

    def test_invalid_value_rows_skipped(self):
        data = {
            "Rows": [
                {"FieldName": "Wind", "Value": "1000"},
                {"FieldName": "Bad", "Value": "not_a_number"},
            ]
        }
        long_df, _ = transform_eirgrid_generation(data)
        assert len(long_df) == 1
