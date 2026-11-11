#Συντονισμός των ελέγχων και ανεξάρτητη διαχείριση σφαλμάτων κατά την εκτέλεσή τους.
from __future__ import annotations

from pathlib import Path
from typing import Any
import hashlib
import json
import sys
import time

import numpy as np
import pandas as pd

from .checks import check_consistency, check_duplicate, check_missing, check_validity
from .io import read_csv
from .models import CheckResult, failed
from .reporting import create_report
from .rules import load_rules


def evaluate_dataframe(df: pd.DataFrame, rules: dict[str, Any]) -> list[CheckResult]:
    #Επιστροφή αποτελεσμάτων χωρίς τροποποίηση του DataFrame. Οι κανόνες πρέπει να έχουν προηγουμένως επικυρωθεί.
    results: list[CheckResult] = []
    tokens = rules.get("missing_tokens", [""])
    results.extend(check_missing(df, tokens))

    for group, checker in (
        ("duplicate_checks", check_duplicate),
        ("validity_checks", check_validity),
        ("consistency_checks", check_consistency),
    ):
        category = group.removesuffix("_checks")
        for rule in rules.get(group, []):
            try:
                results.append(checker(df, rule, tokens))
            except Exception as exc:
                #Η αποτυχία ενός ανεξάρτητου ελέγχου δεν πρέπει να αποκρύπτει τα αποτελέσματα των υπόλοιπων ελέγχων. Το σφάλμα πρέπει να καταγράφεται και να αναφέρεται.
                results.append(failed(rule["id"], category, f"{type(exc).__name__}: {exc}"))
    return results


def run_analysis(
    file_path: str | Path,
    rules_path: str | Path | None = None,
    output_base: str | Path = "reports",
    dataset_id: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    if dataset_id is not None:
        dataset_id = dataset_id.strip()

        if not dataset_id:
            raise ValueError("Το dataset_id δεν μπορεί να είναι κενό.")

    start = time.perf_counter()
    rules = load_rules(rules_path)
    df = read_csv(file_path)
    results = evaluate_dataframe(df, rules)
    elapsed = round(time.perf_counter() - start, 6)
    input_digest = hashlib.sha256(Path(file_path).read_bytes()).hexdigest()
    rules_digest = hashlib.sha256(
        json.dumps(rules, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


    metadata_extra = {
        "input_sha256": input_digest,
        "rules_sha256": rules_digest,
        "processing_time_seconds": elapsed,
        "python_version": sys.version.split()[0],
        "pandas_version": pd.__version__,
        "numpy_version": np.__version__,
    }

    if dataset_id is not None:
        metadata_extra["dataset_id"] = dataset_id

    return create_report(
        results,
        source_name=Path(file_path).name,
        row_count=len(df),
        column_count=len(df.columns),
        output_base=output_base,
        rules_name=Path(rules_path).name if rules_path else "default",
        metadata_extra=metadata_extra,
    )
