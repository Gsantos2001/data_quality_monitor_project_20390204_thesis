"""Ανεξάρτητη εκτέλεση της υβριδικής υλοποίησης Pandera χωρίς DQM baseline.

Χρήση: python pandera_benchmark_worker.py --input CSV --rules JSON --output CSV
Η συνάρτηση calculate προέρχεται από το ήδη επαληθευμένο compare_pandera_nyc311.py.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from compare_pandera_nyc311 import calculate
from data_quality_monitor.io import read_csv
from data_quality_monitor.rules import load_rules

FIELDS = ["check_id", "category", "status", "checked_count", "issue_count", "not_evaluated_count"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Pandera hybrid benchmark worker")
    parser.add_argument("--input", required=True)
    parser.add_argument("--rules", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    df = read_csv(args.input)
    rules = load_rules(args.rules)
    results = calculate(df, rules)
    expected = len(df.columns) + len(rules.get("duplicate_checks", [])) + len(rules.get("validity_checks", [])) + len(rules.get("consistency_checks", []))
    if len(results) != expected or any(r["status"] != "completed" for r in results):
        raise RuntimeError(f"Μη αναμενόμενα αποτελέσματα Pandera: {len(results)}/{expected} checks")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(results)
    print(f"Pandera hybrid: {len(df):,} εγγραφές, {len(results)} έλεγχοι, {out}")


if __name__ == "__main__":
    main()
