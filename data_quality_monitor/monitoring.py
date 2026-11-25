"""Διαχείριση ιστορικών αναφορών και σύγκριση αποτελεσμάτων ποιότητας δεδομένων."""
import json
from pathlib import Path
from typing import Any
import csv
from datetime import datetime


def load_report(report_path: str | Path) -> dict[str, Any]:
    #Διαβάζει μια αποθηκευμένη αναφορά ποιότητας δεδομένων.
    path = Path(report_path)

    try:
        with path.open("r", encoding="utf-8") as file:
            report = json.load(file)

    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(
            f"Μη έγκυρο JSON στην αναφορά '{path}': {exc}"
        ) from exc


    if not isinstance(report, dict):
        raise ValueError("Η αναφορά πρέπει να είναι αντικείμενο JSON.")


    if not isinstance(report.get("metadata"), dict):
        raise ValueError(
            f"Μη έγκυρα ή ελλιπή μεταδεδομένα στην αναφορά: {path}"
        )

    if not isinstance(report.get("checks"), list):
        raise ValueError(
            f"Μη έγκυρη λίστα ελέγχων στην αναφορά: {path}"
        )

    required_fields = (
        "input_file",
        "rules_sha256",
        "generated_at_utc",
    )

    for field in required_fields:
        value = report["metadata"].get(field)

        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"Μη έγκυρο ή ελλιπές πεδίο metadata.{field} "
                f"στην αναφορά: {path}"
            )

    return report



def parse_report_timestamp(report_path: str | Path) -> datetime:
    #Διαβάζει και ελέγχει τη χρονική σήμανση μιας αναφοράς.

    path = Path(report_path)
    report = load_report(path)

    raw_timestamp = report["metadata"].get("generated_at_utc")

    try:
        timestamp = datetime.fromisoformat(raw_timestamp)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Μη έγκυρη ημερομηνία στην αναφορά: {path}"
        ) from exc

    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(
            f"Η ημερομηνία δεν περιέχει ζώνη ώρας: {path}"
        )

    return timestamp



def compare_reports(
    old_report: dict[str, Any],
    new_report: dict[str, Any]
) -> list[dict[str, Any]]:
    #Συγκρίνει δείκτες ποιότητας από δύο εκτελέσεις.

    
    old_metadata = old_report["metadata"]
    new_metadata = new_report["metadata"]

    old_dataset_id = old_metadata.get("dataset_id")
    new_dataset_id = new_metadata.get("dataset_id")

    if (old_dataset_id is None) != (new_dataset_id is None):
        raise ValueError(
            "Οι αναφορές έχουν διαφορετική ταυτότητα συνόλου δεδομένων."
        )

    if old_dataset_id is not None:
        if old_dataset_id != new_dataset_id:
            raise ValueError(
                "Οι αναφορές αφορούν διαφορετικά σύνολα δεδομένων."
            )
    elif old_metadata["input_file"] != new_metadata["input_file"]:
        raise ValueError(
            "Οι αναφορές αφορούν διαφορετικά αρχεία εισόδου."
        )

    if old_metadata["rules_sha256"] != new_metadata["rules_sha256"]:
        raise ValueError(
            "Οι αναφορές χρησιμοποιούν διαφορετικούς κανόνες."
        )


    old_checks = {
        check["check_id"]: check
        for check in old_report["checks"]
    }

    comparisons = []

    for new_check in new_report["checks"]:
        check_id = new_check["check_id"]
        old_check = old_checks.get(check_id)

        if old_check is None:
            continue

        if old_check["status"] != "completed" or new_check["status"] != "completed":
            continue

        old_rate = old_check["issue_rate_percent"]
        new_rate = new_check["issue_rate_percent"]

        if old_rate is None or new_rate is None:
            continue

        change = round(new_rate - old_rate, 2)

        if change < 0:
            trend = "improved"
        elif change > 0:
            trend = "worsened"
        else:
            trend = "unchanged"

        comparisons.append({
            "check_id": check_id,
            "old_rate": old_rate,
            "new_rate": new_rate,
            "change_percentage_points": change,
            "trend": trend
        })

    return comparisons



def find_report_paths(reports_dir: str | Path) -> list[Path]:
    #Εντοπίζει τις αποθηκευμένες αναφορές ανάλυσης.

    root = Path(reports_dir)

    if not root.is_dir():
        raise ValueError(
            f"Ο φάκελος αναφορών δεν υπάρχει ή δεν είναι φάκελος: {root}"
        )

    report_paths = sorted(root.glob("run_*/report.json"))

    return report_paths



def find_comparable_report_paths(
    reports_dir: str | Path,
    reference_report_path: str | Path
) -> list[Path]:
    #Εντοπίζει ιστορικές αναφορές του ίδιου dataset και κανόνων.

    reference_report = load_report(reference_report_path)
    reference_metadata = reference_report["metadata"]
    reference_dataset_id = reference_metadata.get("dataset_id")

    comparable_paths = []

    for report_path in find_report_paths(reports_dir):
        report = load_report(report_path)
        metadata = report["metadata"]

        same_rules = (
            metadata.get("rules_sha256")
            == reference_metadata.get("rules_sha256")
        )

        if reference_dataset_id is not None:
            # Νέες αναφορές: σύγκριση με σταθερό dataset_id.
            same_dataset = (
                metadata.get("dataset_id") == reference_dataset_id
            )
        else:
            # Παλαιές αναφορές: διατηρούμε την προηγούμενη λογική.
            same_dataset = (
                metadata.get("dataset_id") is None
                and metadata.get("input_file")
                == reference_metadata.get("input_file")
            )

        if same_dataset and same_rules:
            comparable_paths.append(report_path)
        


   
    return sorted(comparable_paths, key=parse_report_timestamp)



def build_check_history(
    reports_dir: str | Path,
    reference_report_path: str | Path,
    check_id: str
) -> list[dict[str, Any]]:
    #Δημιουργεί χρονολογικό ιστορικό ενός δείκτη ποιότητας.

    paths = find_comparable_report_paths(
        reports_dir,
        reference_report_path
    )

    history = []
    previous_rate = None

    for report_path in paths:
        report = load_report(report_path)

        check = next(
            (
                item
                for item in report["checks"]
                if item["check_id"] == check_id
            ),
            None
        )

        status = check["status"] if check is not None else "missing"

        rate = None
        if status == "completed":
            rate = check.get("issue_rate_percent")

        change = None
        trend = None

        if rate is not None and previous_rate is not None:
            change = round(rate - previous_rate, 2)

            if change < 0:
                trend = "improved"
            elif change > 0:
                trend = "worsened"
            else:
                trend = "unchanged"

        history.append({
            "generated_at_utc": report["metadata"]["generated_at_utc"],
            "report_path": str(report_path),
            "status": status,
            "issue_rate_percent": rate,
            "change_percentage_points": change,
            "trend": trend
        })

        previous_rate = rate

    return history



def save_check_history(
    history: list[dict[str, Any]],
    output_path: str | Path
) -> Path:
    #Αποθηκεύει το ιστορικό ποιότητας σε αρχείο JSON.

    path = Path(output_path)

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("x", encoding="utf-8") as file:
        json.dump(
            history,
            file,
            ensure_ascii=False,
            indent=2
        )

    return path




def save_check_history_csv(
    history: list[dict[str, Any]],
    output_path: str | Path
) -> Path:
    #Αποθηκεύει το ιστορικό ποιότητας σε αρχείο CSV.

    path = Path(output_path)

    path.parent.mkdir(parents=True, exist_ok=True)

    columns = [
        "generated_at_utc",
        "report_path",
        "status",
        "issue_rate_percent",
        "change_percentage_points",
        "trend",
    ]

    with path.open(
        "x",
        encoding="utf-8-sig",
        newline=""
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=columns,
            delimiter=";",
            extrasaction="ignore"
        )

        writer.writeheader()
        writer.writerows(history)

    return path
