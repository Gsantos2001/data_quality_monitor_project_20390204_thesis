#Χρήση: python -m data_quality_monitor --input ... --rules ... --output ...
from __future__ import annotations

import argparse
import sys

from .engine import run_analysis
from .io import DataInputError
from .rules import RulesError
from .monitor_cli import monitor_main

def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if argv and argv[0] == "monitor":
        return monitor_main(argv[1:])
    parser = argparse.ArgumentParser(description="Έλεγχος και αξιολόγηση ποιότητας δεδομένων CSV.")
    parser.add_argument("--input", required=True, help="Διαδρομή εισερχόμενου CSV")
    parser.add_argument("--rules", help="JSON με κανόνες ελέγχου (προαιρετικό)")
    parser.add_argument("--output", default="reports", help="Φάκελος εξόδου αναφορών")
    parser.add_argument(
        "--dataset-id",
        default=None,
        help="Αναγνωριστικό συνόλου δεδομένων (προαιρετικό)"
    )
    args = parser.parse_args(argv)

    try:
         folder, report = run_analysis(
            args.input,
            args.rules,
            args.output,
            dataset_id=args.dataset_id,
        )
    except (DataInputError, RulesError, OSError, ValueError) as exc:
        print(f"Σφάλμα: {exc}", file=sys.stderr)
        return 2

    counts = report["check_status_counts"]
    print(f"Ολοκληρώθηκε η ανάλυση: {report['metadata']['input_file']}")
    print(f"Εγγραφές: {report['metadata']['row_count']}; στήλες: {report['metadata']['column_count']}")
    print(f"Έλεγχοι: ολοκληρωμένοι={counts['completed']}, παραλείψεις={counts['skipped']}, σφάλματα={counts['error']}")
    print(f"Αναφορές: {folder.resolve()}")
    #Ο κωδικός εξόδου 1 υποδηλώνει τουλάχιστον μία τεχνική αποτυχία ελέγχου και όχι απλώς την ύπαρξη προβλημάτων ποιότητας δεδομένων.
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
