"""Διερεύνηση παραβιάσεων created_date <= closed_date σε πραγματικά δεδομένα NYC 311.

Δεν μεταβάλλει το αρχικό dataset ή την εφαρμογή. Διαβάζει το CSV διαδοχικά.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INPUT_CSV = ROOT.parent / "NYC_311_expiriments" / "nyc311_datasets" / "nyc311_1000000.csv"
OUTPUT_DIR = ROOT / "nyc311_time_consistency_experiment"
SAMPLE_SIZE = 25
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"


def parse_datetime(value: str):
    try:
        return datetime.strptime(value.strip(), DATE_FORMAT)
    except (ValueError, AttributeError):
        return None


def classify_gap(seconds: float) -> str:
    # seconds = created - closed, strictly positive only
    if seconds <= 60:
        return "(0, 1 λεπτό]"
    if seconds <= 3600:
        return "(1 λεπτό, 1 ώρα]"
    if seconds <= 86400:
        return "(1 ώρα, 1 ημέρα]"
    if seconds <= 7 * 86400:
        return "(1 ημέρα, 7 ημέρες]"
    if seconds <= 30 * 86400:
        return "(7 ημέρες, 30 ημέρες]"
    return "> 30 ημέρες"


def main():
    if not INPUT_CSV.is_file():
        raise FileNotFoundError(f"Δεν βρέθηκε το CSV: {INPUT_CSV}")

    total = 0
    missing = 0
    invalid = 0
    comparable = 0
    violations = 0
    bins = Counter()
    agencies = Counter()
    statuses = Counter()
    sample = []
    largest = None

    with INPUT_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"unique_key", "created_date", "closed_date"}
        absent = required - set(reader.fieldnames or [])
        if absent:
            raise ValueError(f"Λείπουν στήλες: {', '.join(sorted(absent))}")

        for row_number, row in enumerate(reader, start=1):
            total += 1
            created_raw = (row.get("created_date") or "").strip()
            closed_raw = (row.get("closed_date") or "").strip()
            if not created_raw or not closed_raw:
                missing += 1
                continue
            created = parse_datetime(created_raw)
            closed = parse_datetime(closed_raw)
            if created is None or closed is None:
                invalid += 1
                continue
            comparable += 1
            if created <= closed:
                continue

            violations += 1
            seconds = (created - closed).total_seconds()
            bins[classify_gap(seconds)] += 1
            agencies[(row.get("agency") or "").strip() or "(κενό)"] += 1
            statuses[(row.get("status") or "").strip() or "(κενό)"] += 1
            result = {
                "row_number": row_number,
                "unique_key": row.get("unique_key", ""),
                "created_date": created_raw,
                "closed_date": closed_raw,
                "created_minus_closed_hours": round(seconds / 3600, 3),
                "agency": row.get("agency", ""),
                "status": row.get("status", ""),
                "complaint_type": row.get("complaint_type", ""),
            }
            if len(sample) < SAMPLE_SIZE:
                sample.append(result)
            if largest is None or seconds > largest[0]:
                largest = (seconds, result)

    OUTPUT_DIR.mkdir(exist_ok=True, parents=True)
    sample_path = OUTPUT_DIR / "date_violations_sample.csv"
    with sample_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "row_number", "unique_key", "created_date", "closed_date",
            "created_minus_closed_hours", "agency", "status", "complaint_type",
        ])
        writer.writeheader()
        writer.writerows(sample)

    summary = {
        "input_file": INPUT_CSV.name,
        "rows": total,
        "missing_at_least_one_date": missing,
        "invalid_nonempty_dates": invalid,
        "comparable": comparable,
        "violations_created_after_closed": violations,
        "violation_percent_of_comparable": round(100 * violations / comparable, 3) if comparable else None,
        "gap_categories": dict(bins),
        "agencies_with_violations_top_10": agencies.most_common(10),
        "statuses_with_violations": statuses.most_common(),
        "largest_gap_example": largest[1] if largest else None,
        "methodology": "Οι χρόνοι ερμηνεύονται ως naive datetime σύμφωνα με %Y-%m-%dT%H:%M:%S.%f. Δεν έγινε μετατροπή ζώνης ώρας.",
    }
    summary_path = OUTPUT_DIR / "date_violations_analysis.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("ΔΙΕΡΕΥΝΗΣΗ ΧΡΟΝΙΚΗΣ ΣΥΝΕΠΕΙΑΣ NYC 311")
    print(f"Εγγραφές: {total:,}")
    print(f"Με τουλάχιστον μία κενή ημερομηνία: {missing:,}")
    print(f"Με μη αναγνωρίσιμη μη κενή ημερομηνία: {invalid:,}")
    print(f"Συγκρίσιμες: {comparable:,}")
    print(f"Παραβιάσεις (created_date > closed_date): {violations:,}")
    print("Κατανομή χρονικής διαφοράς:")
    for key in ["(0, 1 λεπτό]", "(1 λεπτό, 1 ώρα]", "(1 ώρα, 1 ημέρα]", "(1 ημέρα, 7 ημέρες]", "(7 ημέρες, 30 ημέρες]", "> 30 ημέρες"]:
        print(f"  {key}: {bins[key]:,}")
    print("Πρώτα 5 παραδείγματα:")
    for item in sample[:5]:
        print(f"  γραμμή {item['row_number']}, κλειδί {item['unique_key']}: {item['created_date']} > {item['closed_date']} ({item['created_minus_closed_hours']} ώρες)")
    print(f"Ανάλυση: {summary_path}")
    print(f"Δείγμα: {sample_path}")
    if total == 1_000_000 and violations != 9830:
        print("ΠΡΟΣΟΧΗ: Ο αριθμός παραβιάσεων διαφέρει από τις 9.830 της προηγούμενης αναφοράς. Χρειάζεται διερεύνηση πριν εξαχθεί συμπέρασμα.")


if __name__ == "__main__":
    main()
