"""Επαλήθευση ελεγχόμενων αλλοιώσεων NYC 311 ανά εγγραφή και έλεγχο.

Το script διαβάζει υπάρχουσες αναφορές. Δεν τροποποιεί τα datasets.
"""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXP = ROOT / "nyc311_corruption_experiment"
TRUTH = EXP / "ground_truth.csv"
BASE = EXP / "baseline_reports"
CORRUPTED = EXP / "corrupted_reports"
OUTPUT = EXP / "verification_results.csv"


def newest_report_file(root: Path, filename: str) -> Path:
    matches = list(root.rglob(filename)) if root.is_dir() else []
    if not matches:
        raise FileNotFoundError(f"Δεν βρέθηκε {filename} στον φάκελο {root}")
    return max(matches, key=lambda p: p.stat().st_mtime_ns)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def row_id(row: dict[str, str], key: str) -> int:
    return int(row[key])


def main() -> None:
    if not TRUTH.is_file():
        raise FileNotFoundError(f"Δεν βρέθηκε ground truth: {TRUTH}")

    baseline_findings_path = newest_report_file(BASE, "findings.csv")
    corrupted_findings_path = newest_report_file(CORRUPTED, "findings.csv")
    baseline_checks_path = baseline_findings_path.parent / "checks.csv"
    corrupted_checks_path = corrupted_findings_path.parent / "checks.csv"

    truth = read_csv(TRUTH)
    before_findings = read_csv(baseline_findings_path)
    after_findings = read_csv(corrupted_findings_path)
    before_checks = {r["check_id"]: r for r in read_csv(baseline_checks_path)}
    after_checks = {r["check_id"]: r for r in read_csv(corrupted_checks_path)}

    before_pairs = {(r["check_id"], row_id(r, "row_number")) for r in before_findings}
    after_pairs = {(r["check_id"], row_id(r, "row_number")) for r in after_findings}
    intended = {(r["expected_check_id"], row_id(r, "row_number")) for r in truth}
    if len(intended) != len(truth):
        raise ValueError("Το ground truth περιλαμβάνει διπλές εγγραφές (check_id, row_number).")

    grouped: dict[str, list[dict[str, str]]] = {}
    for row in truth:
        grouped.setdefault(row["expected_check_id"], []).append(row)

    output_rows = []
    all_ok = True
    print("ΕΠΑΛΗΘΕΥΣΗ ΕΛΕΓΧΟΜΕΝΩΝ ΑΛΛΟΙΩΣΕΩΝ NYC 311")
    print(f"Ground truth: {len(truth)} αλλαγές")
    print(f"Baseline: {baseline_findings_path.parent}")
    print(f"Corrupted: {corrupted_findings_path.parent}")
    print()
    print(f"{'Έλεγχος':<26} {'Γνωστά':>7} {'Ανιχν.':>7} {'Νέα':>7} {'Δέλτα':>7} {'OK':>5}")

    for check_id, rows in grouped.items():
        expected = {(check_id, row_id(row, "row_number")) for row in rows}
        detected = expected & after_pairs
        already = expected & before_pairs
        new_pairs = {p for p in after_pairs - before_pairs if p[0] == check_id}
        disappeared = {p for p in before_pairs - after_pairs if p[0] == check_id}

        if check_id not in before_checks or check_id not in after_checks:
            raise ValueError(f"Λείπουν συγκεντρωτικά αποτελέσματα για {check_id}")
        b = before_checks[check_id]
        a = after_checks[check_id]
        if b["status"] != "completed" or a["status"] != "completed":
            raise ValueError(f"Ο έλεγχος {check_id} δεν ολοκληρώθηκε και στις δύο αναφορές")
        difference = int(a["issue_count"]) - int(b["issue_count"])
        ok = (detected == expected and not already and new_pairs == expected
              and not disappeared and difference == len(expected))
        all_ok &= ok
        print(f"{check_id:<26} {len(expected):>7} {len(detected):>7} {len(new_pairs):>7} {difference:>7} {('ΝΑΙ' if ok else 'ΟΧΙ'):>5}")

        for row in rows:
            pair = (check_id, row_id(row, "row_number"))
            output_rows.append({
                "error_type": row["error_type"],
                "expected_check_id": check_id,
                "row_number": row["row_number"],
                "detected_after": int(pair in after_pairs),
                "present_before": int(pair in before_pairs),
                "is_new_finding": int(pair in (after_pairs - before_pairs)),
            })

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output_rows[0]))
        writer.writeheader()
        writer.writerows(output_rows)

    detected_total = sum(int(row["detected_after"]) for row in output_rows)
    print(f"\nΑνιχνεύθηκαν στις σωστές εγγραφές: {detected_total}/{len(truth)}")
    print(f"Αρχείο επαλήθευσης: {OUTPUT}")
    print("ΤΕΛΙΚΟ ΑΠΟΤΕΛΕΣΜΑ:", "ΕΠΙΤΥΧΙΑ" if all_ok else "ΧΡΕΙΑΖΕΤΑΙ ΔΙΕΡΕΥΝΗΣΗ")
    if not all_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
