
"""Γραμμή εντολών για την παρακολούθηση ποιότητας δεδομένων."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from .monitoring import (
    build_check_history,
    find_report_paths,
    load_report,
    parse_report_timestamp,
    save_check_history,
    save_check_history_csv,
)


def monitor_main(argv: list[str]) -> int:
    #Δημιουργεί ιστορικό ποιότητας για έναν συγκεκριμένο έλεγχο.

    parser = argparse.ArgumentParser(
        prog="python -m data_quality_monitor monitor",
        description="Παρακολούθηση ιστορικών δεικτών ποιότητας δεδομένων."
    )

    parser.add_argument(
        "--reports",
        default="reports",
        help="Φάκελος αποθηκευμένων αναφορών"
    )

    parser.add_argument(
        "--check",
        required=True,
        help="Αναγνωριστικό ελέγχου, π.χ. missing:product_name"
    )

    parser.add_argument(
        "--output",
        default="monitoring_reports",
        help="Φάκελος εξόδου ιστορικού"
    )
    parser.add_argument(
        "--dataset-id",
        default=None,
        help="Αναγνωριστικό συνόλου δεδομένων προς παρακολούθηση"
    )
    args = parser.parse_args(argv)

    try:
        report_paths = find_report_paths(args.reports)

        if not report_paths:
            raise ValueError("Δεν βρέθηκαν αποθηκευμένες αναφορές.")

        

        if args.dataset_id is not None:
            dataset_id = args.dataset_id.strip()

            if not dataset_id:
                raise ValueError(
                    "Το --dataset-id δεν μπορεί να είναι κενό."
                )

            matching_paths = [
                path
                for path in report_paths
                if load_report(path)["metadata"].get("dataset_id")
                == dataset_id
            ]

            if not matching_paths:
                raise ValueError(
                    f"Δεν βρέθηκαν αναφορές για το dataset_id: {dataset_id}"
                )

            candidate_paths = matching_paths

        else:
            candidate_paths = report_paths



        reference_path = max(
            candidate_paths,
            key=parse_report_timestamp
        )



        history = build_check_history(
            args.reports,
            reference_path,
            args.check
        )

        if not any(item["status"] != "missing" for item in history):
            raise ValueError(
                f"Δεν βρέθηκε ο έλεγχος: {args.check}"
            )

        if not any(
            item["issue_rate_percent"] is not None
            for item in history
        ):
            raise ValueError(
                f"Δεν υπάρχουν διαθέσιμες μετρήσεις "
                f"για τον έλεγχο: {args.check}"
            )


        timestamp = datetime.now(timezone.utc).strftime(
            "%Y%m%d_%H%M%S_%fZ"
        )

        safe_check_id = "".join(
            character
            if character.isascii() and (
                character.isalnum() or character in "_-"
            )
            else "_"
            for character in args.check
        )

        output_dir = Path(args.output)

        json_path = save_check_history(
            history,
            output_dir / f"{safe_check_id}_{timestamp}.json"
        )

        csv_path = save_check_history_csv(
            history,
            output_dir / f"{safe_check_id}_{timestamp}.csv"
        )

    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Σφάλμα Monitoring: {exc}", file=sys.stderr)
        return 2

    print(f"Έλεγχος: {args.check}")
    print(f"Ιστορικές μετρήσεις: {len(history)}")
    print(f"Αναφορά αναφοράς: {reference_path}")
    print(f"JSON: {json_path.resolve()}")
    print(f"CSV: {csv_path.resolve()}")

    return 0
