"""Πρώτος έλεγχος ισοδυναμίας Data Quality Monitor και Pandera 0.36.0.

Εκτέλεση από τη ρίζα του project:
  python compare_pandera_nyc311.py

Δεν είναι ακόμη benchmark: καταγράφει συγκεντρωτικά αποτελέσματα ανά κανόνα.
Χρησιμοποιεί πραγματικά Pandera DataFrameSchema / Check σε ΚΑΘΕ έλεγχο.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import math
from pathlib import Path
import re

import numpy as np
import pandas as pd
import pandera
import pandera.pandas as pa
from pandera.errors import SchemaError

from data_quality_monitor.io import read_csv
from data_quality_monitor.rules import load_rules


def missing_mask(series: pd.Series, tokens: list[str]) -> pd.Series:
    normalized_tokens = {str(t).strip().casefold() for t in tokens}
    normalized_tokens.add("")
    normalized = series.astype("string").str.strip().str.casefold()
    return (series.isna() | normalized.isin(normalized_tokens)).fillna(True).astype(bool)


def strict_date(value: object, fmt: str) -> datetime | None:
    #Ίδια αποδοχή 1–6 ψηφίων του %f όπως στο DQM.
    try:
        original = str(value)
        parsed = datetime.strptime(original, fmt)
        if "%f" not in fmt:
            return parsed if parsed.strftime(fmt) == original else None
        prefix_fmt, suffix_fmt = fmt.split("%f", 1)
        prefix, suffix = parsed.strftime(prefix_fmt), parsed.strftime(suffix_fmt)
        if not original.startswith(prefix) or (suffix and not original.endswith(suffix)):
            return None
        end = len(original) - len(suffix) if suffix else len(original)
        fraction = original[len(prefix):end]
        if not (1 <= len(fraction) <= 6 and fraction.isascii() and fraction.isdecimal()):
            return None
        return parsed if int(fraction.ljust(6, "0")) == parsed.microsecond else None
    except (ValueError, TypeError):
        return None


def calculate(df: pd.DataFrame, rules: dict) -> list[dict]:
    #Εφαρμόζει ανεξάρτητους Pandera Check σε κάθε κανόνα και μετρά τις αστοχίες.
    tokens = rules.get("missing_tokens", [""])
    result_rows: list[dict] = []

    def run_check(check_id: str, category: str, checked_mask: pd.Series,
                  valid_on_eligible: pd.Series) -> None:
        # Όλα τα masks έχουν το ίδιο index. Οι μη συγκρίσιμες γραμμές
        # σημαίνονται True (όχι παράβαση), όπως στο DQM.
        checked_mask = checked_mask.fillna(False).astype(bool)
        valid_on_eligible = valid_on_eligible.fillna(False).astype(bool)
        count = int(checked_mask.sum())
        if count == 0:
            result_rows.append(dict(check_id=check_id, category=category,
                                    status="skipped", checked_count=0,
                                    issue_count="", not_evaluated_count=len(df)))
            return
        valid = pd.Series(True, index=df.index, dtype=bool)
        valid.loc[checked_mask] = valid_on_eligible.loc[checked_mask]
        observed = {"called": False}

        def pandera_condition(frame: pd.DataFrame) -> pd.Series:
            observed["called"] = True
            # Δεν εκτελούμε έναν πρόσθετο έλεγχο του DQM: η Pandera
            # επαληθεύει το boolean αποτέλεσμα για κάθε εγγραφή.
            return valid.reindex(frame.index).fillna(False).astype(bool)

        schema = pa.DataFrameSchema(
            checks=[pa.Check(pandera_condition, name=check_id, ignore_na=False)],
            strict=False,
        )
        try:
            schema.validate(df, lazy=False)
        except SchemaError:
            # Αναμενόμενο όταν υπάρχουν παραβιάσεις του συγκεκριμένου κανόνα.
            pass
        if not observed["called"]:
            raise RuntimeError(f"Η Pandera δεν εκτέλεσε τον κανόνα {check_id}")
        failures = int((~valid & checked_mask).sum())
        result_rows.append(dict(check_id=check_id, category=category,
                                status="completed", checked_count=count,
                                issue_count=failures,
                                not_evaluated_count=len(df) - count))

    for col in df.columns:
        nonmissing = ~missing_mask(df[col], tokens)
        run_check(f"missing:{col}", "missing",
                  pd.Series(True, index=df.index), nonmissing)

    for rule in rules.get("duplicate_checks", []):
        cols = rule.get("columns")
        eligible = pd.Series(True, index=df.index, dtype=bool)
        if cols is not None:
            for col in cols:
                eligible &= ~missing_mask(df[col], tokens)
        dup = df.loc[eligible].duplicated(subset=cols, keep="first")
        valid = pd.Series(True, index=df.index, dtype=bool)
        valid.loc[dup.index] = ~dup
        run_check(rule["id"], "duplicates", eligible, valid)

    for rule in rules.get("validity_checks", []):
        col, kind = rule["column"], rule["kind"]
        eligible = ~missing_mask(df[col], tokens)
        values = df.loc[eligible, col]
        if kind == "regex":
            regex = re.compile(rule["pattern"])
            good = values.map(lambda v: regex.fullmatch(str(v)) is not None)
        elif kind == "date_format":
            good = values.map(lambda v: strict_date(v, rule["format"]) is not None)
        elif kind == "numeric_range":
            numbers = pd.to_numeric(values, errors="coerce")
            good = numbers.notna() & pd.Series(np.isfinite(numbers.to_numpy(dtype=float)), index=values.index)
            if "min" in rule:
                good &= numbers >= rule["min"]
            if "max" in rule:
                good &= numbers <= rule["max"]
            if rule.get("integer", False):
                good &= numbers % 1 == 0
        elif kind == "allowed_values":
            good = values.isin(rule["values"])
        elif kind == "text_length":
            lengths = values.astype("string").str.strip().str.len()
            good = pd.Series(True, index=values.index)
            if "min_length" in rule:
                good &= lengths >= rule["min_length"]
            if "max_length" in rule:
                good &= lengths <= rule["max_length"]
        else:
            raise ValueError(f"Μη υποστηριζόμενος κανόνας Pandera: {kind}")
        full_valid = pd.Series(True, index=df.index, dtype=bool)
        full_valid.loc[eligible] = good.fillna(False).astype(bool)
        run_check(rule["id"], "validity", eligible, full_valid)

    for rule in rules.get("consistency_checks", []):
        if rule["kind"] != "comparison" or rule.get("data_type") != "date":
            raise ValueError("Το αρχικό πρωτότυπο υποστηρίζει μόνο σύγκριση ημερομηνιών.")
        left_col, right_col = rule["left"], rule["right"]
        eligible = (~missing_mask(df[left_col], tokens)
                    & ~missing_mask(df[right_col], tokens))
        left = df.loc[eligible, left_col].map(lambda v: strict_date(v, rule["format"]))
        right = df.loc[eligible, right_col].map(lambda v: strict_date(v, rule["format"]))
        comparable = left.notna() & right.notna()
        actual = pd.Series(False, index=df.index)
        actual.loc[comparable.index] = comparable
        operators = {"<=": lambda a, b: a <= b, "<": lambda a, b: a < b,
                     ">=": lambda a, b: a >= b, ">": lambda a, b: a > b,
                     "==": lambda a, b: a == b, "!=": lambda a, b: a != b}
        compare = operators[rule["operator"]]
        good = compare(left.loc[comparable], right.loc[comparable])
        valid = pd.Series(True, index=df.index, dtype=bool)
        valid.loc[good.index] = good.astype(bool)
        run_check(rule["id"], "consistency", actual, valid)

    return result_rows


def locate_baseline(path: Path) -> Path:
    if path.is_file():
        return path
    candidates = list(path.rglob("checks.csv")) if path.is_dir() else []
    if not candidates:
        raise FileNotFoundError(f"Δεν βρέθηκε checks.csv στο: {path}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ισοδυναμία 53 ελέγχων DQM και Pandera")
    parser.add_argument("--input", default=r"..\NYC_311_expiriments\nyc311_datasets\nyc311_10000.csv")
    parser.add_argument("--rules", default=r"examples\nyc311_rules_initial.json")
    parser.add_argument("--baseline", default=r"nyc311_corruption_experiment\baseline_reports")
    parser.add_argument("--output", default=r"pandera_comparison\pandera_checks_10000.csv")
    args = parser.parse_args()
    df = read_csv(args.input)
    rules = load_rules(args.rules)
    results = calculate(df, rules)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fields = ["check_id", "category", "status", "checked_count", "issue_count", "not_evaluated_count"]
    with destination.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results)

    baseline_path = locate_baseline(Path(args.baseline))
    with baseline_path.open("r", encoding="utf-8-sig", newline="") as f:
        baseline = {r["check_id"]: r for r in csv.DictReader(f)}
    diffs = []
    for p in results:
        d = baseline.get(p["check_id"])
        if d is None:
            diffs.append((p["check_id"], "απουσιάζει από το DQM"))
            continue
        for field in ("status", "checked_count", "issue_count", "not_evaluated_count"):
            if str(p[field]) != str(d[field]):
                diffs.append((p["check_id"], f"{field}: DQM={d[field]}, Pandera={p[field]}"))
    print(f"Pandera {pandera.__version__} | εγγραφές: {len(df):,} | έλεγχοι: {len(results)}")
    print(f"Αποτελέσματα Pandera: {destination.resolve()}")
    print(f"Αναφορά DQM: {baseline_path.resolve()}")
    print(f"Διαφορές: {len(diffs)}")
    for rule, issue in diffs[:25]:
        print(f"  {rule}: {issue}")
    if not diffs:
        print("ΕΠΙΤΥΧΙΑ: Όλοι οι συγκεντρωτικοί έλεγχοι συμφωνούν.")
    else:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
