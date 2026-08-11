import logging
from dataclasses import dataclass, field

import pandas as pd

try:
    from src.config import LOG_DATE_FORMAT, LOG_FORMAT, LOG_LEVEL
except ImportError:
    from config import LOG_DATE_FORMAT, LOG_FORMAT, LOG_LEVEL

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
logger = logging.getLogger(__name__)


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


class GenerationValidator:
    MIN_GENERATION_MW = 0.0
    MAX_GENERATION_MW = 20_000.0

    def validate(self, df: pd.DataFrame) -> ValidationResult:
        validation = ValidationResult(passed=True, row_count=len(df))

        if df.empty:
            validation.add_error("DataFrame is empty")
            return validation

        if not isinstance(df.index, pd.DatetimeIndex):
            validation.add_error("Index must be DatetimeIndex")

        if "country_code" not in df.columns:
            validation.add_error("Missing required column: country_code")

        numeric_cols = df.select_dtypes(include="number").columns.tolist()
        if not numeric_cols:
            validation.add_error("No numeric generation columns found")
            return validation

        null_counts = df[numeric_cols].isnull().sum()
        for col, null_count in null_counts.items():
            if null_count > 0:
                pct = null_count / len(df) * 100
                if pct > 10:
                    validation.add_error(f"Column '{col}' has {null_count} nulls ({pct:.1f}%)")
                else:
                    validation.add_warning(f"Column '{col}' has {null_count} nulls ({pct:.1f}%)")

        for col in numeric_cols:
            col_data = df[col].dropna()
            if (col_data < self.MIN_GENERATION_MW).any():
                neg_count = int((col_data < self.MIN_GENERATION_MW).sum())
                validation.add_warning(f"Column '{col}' has {neg_count} negative values")
            if (col_data > self.MAX_GENERATION_MW).any():
                high_count = int((col_data > self.MAX_GENERATION_MW).sum())
                validation.add_warning(
                    f"Column '{col}' has {high_count} values above {self.MAX_GENERATION_MW} MW"
                )

        if df.index.duplicated().any():
            dup_count = int(df.index.duplicated().sum())
            validation.add_warning(f"{dup_count} duplicate timestamps found")

        logger.info(validation.summary())
        return validation
