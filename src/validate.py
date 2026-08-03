import logging
from dataclasses import dataclass, field

import pandas as pd

from config import LOG_DATE_FORMAT, LOG_FORMAT, LOG_LEVEL

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
logger = logging.getLogger(__name__)

MIN_GENERATION_MW = 0.0
MAX_GENERATION_MW = 20_000.0


@dataclass
class ValidationResult:
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    row_count: int = 0

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.passed = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def summary(self) -> str:
        status = "PASSED" if self.passed else "FAILED"
        return (
            f"Validation {status}: {self.row_count} rows, "
            f"{len(self.errors)} errors, {len(self.warnings)} warnings"
        )


def validate_generation_df(df: pd.DataFrame) -> ValidationResult:
    result = ValidationResult(passed=True, row_count=len(df))

    if df.empty:
        result.add_error("DataFrame is empty")
        return result

    if not isinstance(df.index, pd.DatetimeIndex):
        result.add_error("Index must be DatetimeIndex")

    if "country_code" not in df.columns:
        result.add_error("Missing required column: country_code")

    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    if not numeric_cols:
        result.add_error("No numeric generation columns found")
        return result

    null_counts = df[numeric_cols].isnull().sum()
    for col, count in null_counts.items():
        if count > 0:
            pct = count / len(df) * 100
            if pct > 10:
                result.add_error(f"Column '{col}' has {count} nulls ({pct:.1f}%)")
            else:
                result.add_warning(f"Column '{col}' has {count} nulls ({pct:.1f}%)")

    for col in numeric_cols:
        col_data = df[col].dropna()
        if (col_data < MIN_GENERATION_MW).any():
            neg_count = int((col_data < MIN_GENERATION_MW).sum())
            result.add_warning(f"Column '{col}' has {neg_count} negative values")
        if (col_data > MAX_GENERATION_MW).any():
            high_count = int((col_data > MAX_GENERATION_MW).sum())
            result.add_warning(
                f"Column '{col}' has {high_count} values above {MAX_GENERATION_MW} MW"
            )

    if df.index.duplicated().any():
        dup_count = int(df.index.duplicated().sum())
        result.add_warning(f"{dup_count} duplicate timestamps found")

    logger.info(result.summary())
    return result


def validate_eirgrid_response(data: dict) -> ValidationResult:
    result = ValidationResult(passed=True)

    if not isinstance(data, dict):
        result.add_error("Response is not a dict")
        return result

    if "Rows" not in data:
        result.add_error("Response missing 'Rows' key")
        return result

    rows = data.get("Rows", [])
    result.row_count = len(rows)

    if not rows:
        result.add_error("No rows in response")
        return result

    for i, row in enumerate(rows):
        if "FieldName" not in row:
            result.add_error(f"Row {i} missing 'FieldName'")
        if "Value" not in row:
            result.add_error(f"Row {i} missing 'Value'")
        else:
            try:
                val = float(row["Value"])
                if val < 0:
                    result.add_warning(
                        f"Row {i} ({row.get('FieldName', '?')}) has negative value"
                    )
            except (ValueError, TypeError):
                result.add_error(
                    f"Row {i} ({row.get('FieldName', '?')}) "
                    f"non-numeric Value: {row['Value']}"
                )

    if data.get("Status") == "Error":
        result.add_error(f"API error: {data.get('ErrorMessage', 'Unknown')}")

    logger.info(result.summary())
    return result
