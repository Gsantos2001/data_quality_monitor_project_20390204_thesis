
import argparse
import csv
import json
from pathlib import Path


CHECK_ID = "borough_allowed_values"
EXPECTED_COUNT = 20


# Ανάγνωση των αναμενόμενων παραβιάσεων.
def load_ground_truth(path):
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)

        return {
            (row["check_id"], int(row["row_number"]))
            for row in reader
            if row["check_id"] == CHECK_ID
        }


# Ανάκτηση του αποτελέσματος του επιλεγμένου ελέγχου.
def load_check(path):
    with path.open("r", encoding="utf-8-sig") as file:
        report = json.load(file)

    matches = [
        check
        for check in report["checks"]
        if check["check_id"] == CHECK_ID
    ]

    if len(matches) != 1:
        raise ValueError(
            "Δεν βρέθηκε μοναδικό αποτέλεσμα του ζητούμενου ελέγχου."
        )

    check = matches[0]

    if check["status"] != "completed":
        raise ValueError("Ο επιλεγμένος έλεγχος δεν ολοκληρώθηκε.")

    if check.get("findings_truncated", False):
        raise ValueError("Τα αναλυτικά ευρήματα έχουν περιοριστεί.")

    if len(check["findings"]) != check["issue_count"]:
        raise ValueError("Η καταγραφή των ευρημάτων δεν είναι πλήρης.")

    return report["metadata"], check


# Ανάκτηση των θέσεων των προβληματικών εγγραφών.
def extract_findings(check):
    return {
        (CHECK_ID, int(finding["row_number"]))
        for finding in check["findings"]
    }


def main():
    parser = argparse.ArgumentParser(
        description="Επαλήθευση ελεγχόμενων αλλοιώσεων κατηγορικών τιμών."
    )

    parser.add_argument("--original-report", required=True, type=Path)
    parser.add_argument("--corrupted-report", required=True, type=Path)
    parser.add_argument("--ground-truth", required=True, type=Path)

    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "nyc311_allowed_values_experiment/verification_results.json"
        ),
    )

    args = parser.parse_args()

    expected = load_ground_truth(args.ground_truth)

    if len(expected) != EXPECTED_COUNT:
        raise ValueError("Μη αναμενόμενο πλήθος ελεγχόμενων αλλοιώσεων.")

    original_metadata, original_check = load_check(
        args.original_report
    )

    corrupted_metadata, corrupted_check = load_check(
        args.corrupted_report
    )

    # Επιβεβαίωση κοινών κανόνων και συνόλου δεδομένων.
    for field in [
        "rules_sha256",
        "dataset_id",
        "row_count",
        "column_count",
    ]:
        if original_metadata[field] != corrupted_metadata[field]:
            raise ValueError(
                f"Ασυμφωνία μεταδεδομένων στο πεδίο {field}."
            )

    original_findings = extract_findings(original_check)
    corrupted_findings = extract_findings(corrupted_check)

    # Απομόνωση των νέων και των απολεσθέντων ευρημάτων.
    new_findings = corrupted_findings - original_findings
    removed_findings = original_findings - corrupted_findings

    detected = expected & new_findings
    missed = expected - new_findings
    unexpected = new_findings - expected

    detection_rate = round(
        100 * len(detected) / len(expected),
        2,
    )

    issue_increase = (
        corrupted_check["issue_count"]
        - original_check["issue_count"]
    )

    success = (
        new_findings == expected
        and not removed_findings
        and issue_increase == EXPECTED_COUNT
        and original_check["checked_count"]
        == corrupted_check["checked_count"]
        and original_check["not_evaluated_count"]
        == corrupted_check["not_evaluated_count"]
    )

    # Συγκέντρωση και αποθήκευση αποτελεσμάτων επαλήθευσης.
    results = {
        "check_id": CHECK_ID,
        "expected_corruptions": len(expected),
        "original_issue_count": original_check["issue_count"],
        "corrupted_issue_count": corrupted_check["issue_count"],
        "issue_count_increase": issue_increase,
        "detected_corruptions": len(detected),
        "missed_corruptions": len(missed),
        "unexpected_new_findings": len(unexpected),
        "removed_original_findings": len(removed_findings),
        "detection_rate_percent": detection_rate,
        "detected_rows": sorted(row for _, row in detected),
        "missed_rows": sorted(row for _, row in missed),
        "unexpected_rows": sorted(row for _, row in unexpected),
        "removed_rows": sorted(row for _, row in removed_findings),
        "verification_success": success,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)

    with args.output.open("x", encoding="utf-8") as file:
        json.dump(
            results,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print(f"Αναμενόμενες αλλοιώσεις: {len(expected)}")
    print(f"Αρχικές παραβιάσεις: {original_check['issue_count']}")
    print(f"Παραβιάσεις μετά την αλλοίωση: {corrupted_check['issue_count']}")
    print(f"Πρόσθετες παραβιάσεις: {issue_increase}")
    print(f"Σωστά εντοπισμένες αλλοιώσεις: {len(detected)}")
    print(f"Μη εντοπισμένες αλλοιώσεις: {len(missed)}")
    print(f"Μη αναμενόμενα νέα ευρήματα: {len(unexpected)}")
    print(f"Απολεσθέντα αρχικά ευρήματα: {len(removed_findings)}")
    print(f"Ποσοστό εντοπισμού αλλοιώσεων: {detection_rate:.2f}%")
    print(f"Αρχείο αποτελεσμάτων: {args.output}")

    if success:
        print("Η επαλήθευση ολοκληρώθηκε επιτυχώς.")
        return 0

    print("Η επαλήθευση εντόπισε ασυμφωνίες.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
