"""Έλεγχοι ποιότητας δεδομένων που δεν τροποποιούν τα αρχικά DataFrames ή αρχεία."""
from __future__ import annotations

from datetime import datetime
import operator
import re
from typing import Any

import numpy as np
import pandas as pd

from .models import CheckResult, Finding, completed, failed, skipped


_COMPARATORS = {
    "<": operator.lt, "<=": operator.le, "==": operator.eq,
    "!=": operator.ne, ">=": operator.ge, ">": operator.gt,
}


def missing_mask(values: pd.Series, tokens: list[str]) -> pd.Series:
    #Επιστρέφει True για κενές τιμές, τιμές που περιέχουν μόνο κενά διαστήματα ή τιμές που έχουν οριστεί από τον χρήστη ως ελλιπείς.
    normalised_tokens = {token.strip().casefold() for token in tokens}
    normalised_tokens.add("")
    normalised = values.astype("string").str.strip().str.casefold()
    return (values.isna() | normalised.isin(normalised_tokens)).fillna(True).astype(bool)


def _rows(mask: pd.Series) -> list[int]:
    return [int(i) + 1 for i in np.flatnonzero(mask.to_numpy(dtype=bool))]


def _findings(check_id: str, category: str, rows, column: str, message: str,
              max_findings: int | None = None) -> list[Finding]:
    if max_findings is None:
        return [Finding(check_id, category, int(row_number), column, message) for row_number in rows]
    return [Finding(check_id, category, int(row_number), column, message)
            for row_number in rows[:max_findings]]


def _bad_rows(mask: pd.Series, max_findings: int | None):
    # Ο αριθμός υπολογίζεται χωρίς τη δημιουργία αντικειμένων για όλες τις αστοχίες.
    indices = np.flatnonzero(mask.to_numpy(dtype=bool))
    stored = indices if max_findings is None else indices[:max_findings]
    return int(len(indices)), stored + 1



def check_missing(df: pd.DataFrame, tokens: list[str], max_findings: int | None = None) -> list[CheckResult]:
    results: list[CheckResult] = []
    for column in df.columns:
        check_id = f"missing:{column}"
        if df.empty:
            results.append(skipped(check_id, "missing", "Δεν υπάρχουν εγγραφές για έλεγχο."))
            continue
        mask = missing_mask(df[column], tokens)
        issue_count, rows = _bad_rows(mask, max_findings)
        issues = _findings(check_id, "missing", rows, column, "Ελλιπής τιμή")
        results.append(completed(check_id, "missing", len(df), issues, details={"column": column}, issue_count=issue_count))
    return results


def check_duplicate(df: pd.DataFrame, rule: dict[str, Any], tokens: list[str], max_findings: int | None = None) -> CheckResult:
    check_id = rule["id"]
    if df.empty:
        return skipped(check_id, "duplicates", "Δεν υπάρχουν εγγραφές για έλεγχο.")
    cols = rule.get("columns")
    missing_columns = [col for col in (cols or []) if col not in df.columns]
    if missing_columns:
        return skipped(check_id, "duplicates", f"Απουσιάζουν στήλες: {', '.join(missing_columns)}")
    if cols is None:
        eligible_mask = pd.Series(True, index=df.index)
        display_cols = list(df.columns)
    else:
        #Τα ελλιπή αναγνωριστικά δεν θεωρούνται διπλότυπα. Καταγράφονται ξεχωριστά από τους ελέγχους ελλιπών τιμών.
        eligible_mask = pd.Series(True, index=df.index)
        for col in cols:
            eligible_mask &= ~missing_mask(df[col], tokens)
        display_cols = cols
    eligible = df.loc[eligible_mask]

    if eligible.empty:
        return skipped(check_id, "duplicates", "Δεν υπάρχουν συγκρίσιμες εγγραφές.")
    duplicated = eligible.duplicated(subset=cols, keep="first")
    issue_count = int(duplicated.sum())
    bad_index = eligible.index[duplicated]

    if max_findings is not None:
        bad_index = bad_index[:max_findings]
        
    rows = [int(i) + 1 for i in bad_index]
    issues = _findings(check_id, "duplicates", rows, ", ".join(display_cols), "Πρόσθετη διπλότυπη εγγραφή")
    return completed(
        check_id, "duplicates", len(eligible), issues,
        not_evaluated_count=len(df) - len(eligible),
        details={"columns": display_cols, "counting": "keep_first; subsequent occurrences"},
        issue_count=issue_count,
    )



def _strict_date(value: str, fmt: str) -> datetime | None:
    try:
        result = datetime.strptime(value, fmt)

        if "%f" in fmt:
            prefix_fmt, suffix_fmt = fmt.split("%f", 1)

            prefix = result.strftime(prefix_fmt)
            suffix = result.strftime(suffix_fmt)

            if not value.startswith(prefix):
                return None

            if suffix and not value.endswith(suffix):
                return None

            end = len(value) - len(suffix) if suffix else len(value)
            fraction = value[len(prefix):end]

            if not (
                1 <= len(fraction) <= 6
                and fraction.isascii()
                and fraction.isdecimal()
            ):
                return None

            microseconds = int(fraction.ljust(6, "0"))

            return result if microseconds == result.microsecond else None

        return result if result.strftime(fmt) == value else None

    except (ValueError, TypeError):
        return None


def check_validity(df: pd.DataFrame, rule: dict[str, Any], tokens: list[str], max_findings: int | None = None) -> CheckResult:
    check_id = rule["id"]
    column = rule["column"]
    if column not in df.columns:
        return skipped(check_id, "validity", f"Απουσιάζει στήλη: {column}")
    if df.empty:
        return skipped(check_id, "validity", "Δεν υπάρχουν εγγραφές για έλεγχο.")
    eligible_mask = ~missing_mask(df[column], tokens)
    eligible = df.loc[eligible_mask, column]
    if eligible.empty:
        return skipped(check_id, "validity", "Όλες οι τιμές είναι ελλιπείς.")
    kind = rule["kind"]
    if kind == "numeric_range":
        numbers = pd.to_numeric(eligible, errors="coerce")
        bad = numbers.isna() | ~np.isfinite(numbers.to_numpy(dtype=float))
        if "min" in rule:
            bad |= numbers < rule["min"]
        if "max" in rule:
            bad |= numbers > rule["max"]
        if rule.get("integer", False):
            bad |= numbers.notna() & (numbers % 1 != 0)
    elif kind == "allowed_values":
        bad = ~eligible.isin(rule["values"])
    elif kind == "regex":
        compiled = re.compile(rule["pattern"])
        bad = ~eligible.map(lambda value: compiled.fullmatch(str(value)) is not None).astype(bool)
    elif kind == "date_format":
        fmt = rule["format"]
        bad = ~eligible.map(lambda value: _strict_date(str(value), fmt) is not None).astype(bool)

    elif kind == "text_length":
        lengths = eligible.astype("string").str.strip().str.len()

        bad = pd.Series(False, index=eligible.index)

        if "min_length" in rule:
            bad |= lengths < rule["min_length"]

        if "max_length" in rule:
            bad |= lengths > rule["max_length"]

    else:  #pragma: no cover; Η επικύρωση του JSON αποτρέπει την εμφάνιση αυτής της περίπτωσης.
        return failed(check_id, "validity", f"Μη υποστηριζόμενος κανόνας: {kind}")
    bad = bad.fillna(True)
    issue_count = int(bad.sum())
    bad_index = eligible.index[bad]
    if max_findings is not None:
        bad_index = bad_index[:max_findings]
    rows = [int(i) + 1 for i in bad_index]
    issues = _findings(check_id, "validity", rows, column, f"Παραβίαση κανόνα: {kind}")
    return completed(
        check_id, "validity", len(eligible), issues,
        not_evaluated_count=len(df) - len(eligible),
        details={"column": column, "kind": kind},
        issue_count=issue_count,
    )


def check_consistency(df: pd.DataFrame, rule: dict[str, Any], tokens: list[str], max_findings: int | None = None) -> CheckResult:
    check_id = rule["id"]
    category = "consistency"
    columns = [rule["left"], rule["right"]]
    if rule["kind"] == "product_equals":
        columns.append(rule["result"])
    absent = [col for col in columns if col not in df.columns]
    if absent:
        return skipped(check_id, category, f"Απουσιάζουν στήλες: {', '.join(absent)}")
    if df.empty:
        return skipped(check_id, category, "Δεν υπάρχουν εγγραφές για έλεγχο.")
    eligible_mask = pd.Series(True, index=df.index)
    for col in columns:
        eligible_mask &= ~missing_mask(df[col], tokens)
    eligible = df.loc[eligible_mask, columns]
    if eligible.empty:
        return skipped(check_id, category, "Δεν υπάρχουν πλήρεις εγγραφές για σύγκριση.")

    kind = rule["kind"]
    if kind == "comparison":
        dtype = rule.get("data_type", "number")
        if dtype == "number":
            left = pd.to_numeric(eligible.iloc[:, 0], errors="coerce")
            right = pd.to_numeric(eligible.iloc[:, 1], errors="coerce")
            comparable = left.notna() & right.notna() & np.isfinite(left.to_numpy(dtype=float)) & np.isfinite(right.to_numpy(dtype=float))
        elif dtype == "date":
            fmt = rule["format"]
            left = eligible.iloc[:, 0].map(lambda value: _strict_date(str(value), fmt))
            right = eligible.iloc[:, 1].map(lambda value: _strict_date(str(value), fmt))
            comparable = left.notna() & right.notna()
        else:
            left = eligible.iloc[:, 0]
            right = eligible.iloc[:, 1]
            comparable = pd.Series(True, index=eligible.index)
        #Οι τιμές που δεν μπορούν να μετατραπούν δεν ταξινομούνται ως ασυνέπειες. Οι λανθασμένοι τύποι και οι μη έγκυρες μορφές εντοπίζονται ξεχωριστά από τους ελέγχους εγκυρότητας.
        compared = eligible.loc[comparable]
        if compared.empty:
            return skipped(check_id, category, "Καμία τιμή δεν μπορεί να συγκριθεί.")
        holds = _COMPARATORS[rule["operator"]](left.loc[comparable], right.loc[comparable])
        bad_indices = compared.index[~holds.fillna(False)]
    elif kind == "product_equals":
        left = pd.to_numeric(eligible.iloc[:, 0], errors="coerce")
        right = pd.to_numeric(eligible.iloc[:, 1], errors="coerce")
        target = pd.to_numeric(eligible.iloc[:, 2], errors="coerce")
        comparable = (left.notna() & right.notna() & target.notna()
                      & np.isfinite(left.to_numpy(dtype=float))
                      & np.isfinite(right.to_numpy(dtype=float))
                      & np.isfinite(target.to_numpy(dtype=float)))
        compared = eligible.loc[comparable]
        if compared.empty:
            return skipped(check_id, category, "Καμία τιμή δεν μπορεί να συγκριθεί.")
        holds_array = np.isclose(
            (left.loc[comparable] * right.loc[comparable]).to_numpy(dtype=float),
            target.loc[comparable].to_numpy(dtype=float),
            atol=rule.get("tolerance", 0.01), rtol=0,
        )
        bad_indices = compared.index[~holds_array]
    else:  # pragma: no cover
        return failed(check_id, category, f"Μη υποστηριζόμενος κανόνας: {kind}")

    issue_count = len(bad_indices)
    if max_findings is not None:
        bad_indices = bad_indices[:max_findings]
    rows = [int(i) + 1 for i in bad_indices]
    issues = _findings(check_id, category, rows, ", ".join(columns), f"Παραβίαση κανόνα: {kind}")
    return completed(
        check_id, category, int(comparable.sum()), issues,
        not_evaluated_count=len(df) - int(comparable.sum()),
        details={"columns": columns, "kind": kind,
                 "excluded_missing_or_unparseable": len(df) - int(comparable.sum())},
        issue_count=issue_count,
    )
