"""Δημιουργία αναπαραγώγιμων αλλοιώσεων NYC 311 και αρχείου ground truth.

Το αρχικό CSV δεν τροποποιείται. Χρησιμοποιείται μόνο η τυπική βιβλιοθήκη.
"""
from __future__ import annotations

import csv
import json
import random
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
INPUT_CSV = PROJECT_DIR.parent / "NYC_311_expiriments" / "nyc311_datasets" / "nyc311_10000.csv"
OUTPUT_DIR = PROJECT_DIR / "nyc311_corruption_experiment"
OUTPUT_CSV = OUTPUT_DIR / "nyc311_10000_corrupted.csv"
GROUND_TRUTH_CSV = OUTPUT_DIR / "ground_truth.csv"
MANIFEST_JSON = OUTPUT_DIR / "experiment_manifest.json"
SEED = 20390204
ERRORS_PER_TYPE = 20
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"

TYPES = [
    ("missing_agency", "agency", "missing:agency"),
    ("duplicate_unique_key", "unique_key", "duplicate_unique_key"),
    ("invalid_unique_key", "unique_key", "unique_key_numeric"),
    ("invalid_closed_date", "closed_date", "closed_date_format"),
    ("invalid_latitude", "latitude", "latitude_range"),
    ("invalid_zip", "incident_zip", "incident_zip_format"),
    ("reversed_dates", "created_date", "created_before_closed"),
]


def parse_date(value: str):
    try:
        return datetime.strptime(value, DATE_FORMAT)
    except (ValueError, TypeError):
        return None


def eligible(row: dict[str, str], kind: str) -> bool:
    value = row.get(dict((k, c) for k, c, _ in TYPES)[kind], "").strip()
    if kind == "missing_agency":
        return bool(value)
    if kind == "duplicate_unique_key":
        return bool(re.fullmatch(r"[0-9]+", value))
    if kind == "invalid_unique_key":
        return bool(re.fullmatch(r"[0-9]+", value))
    if kind == "invalid_closed_date":
        return parse_date(value) is not None
    if kind == "invalid_latitude":
        try:
            return bool(value) and -90 <= float(value) <= 90
        except ValueError:
            return False
    if kind == "invalid_zip":
        return bool(re.fullmatch(r"[0-9]{5}", value))
    if kind == "reversed_dates":
        created, closed = parse_date(row.get("created_date", "")), parse_date(row.get("closed_date", ""))
        return created is not None and closed is not None and created <= closed
    return False


def main() -> None:
    if not INPUT_CSV.is_file():
        raise FileNotFoundError(f"Δεν βρέθηκε το αρχικό CSV: {INPUT_CSV}")

    # Ανάγνωση μόνον του παγωμένου δείγματος 10.000 εγγραφών.
    with INPUT_CSV.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames
        if not columns:
            raise ValueError("Το CSV δεν περιέχει ονόματα στηλών.")
        original_rows = list(reader)

    required = {col for _, col, _ in TYPES} | {"created_date", "closed_date", "unique_key"}
    absent = sorted(required - set(columns))
    if absent:
        raise ValueError(f"Λείπουν απαιτούμενες στήλες: {', '.join(absent)}")

    if len(original_rows) < len(TYPES) * ERRORS_PER_TYPE + 1:
        raise ValueError("Το dataset δεν έχει αρκετές εγγραφές για διακριτές αλλοιώσεις.")

    # Ελέγχουμε τη μοναδικότητα των αρχικών κλειδιών πριν εισαγάγουμε διπλότυπα.
    original_keys = [row["unique_key"] for row in original_rows]
    if any(not re.fullmatch(r"[0-9]+", key.strip()) for key in original_keys):
        raise ValueError("Υπάρχουν ήδη κενά ή μη αριθμητικά unique_key. Ελέγξτε το αρχικό dataset.")
    if len(set(original_keys)) != len(original_keys):
        raise ValueError("Υπάρχουν ήδη διπλότυπα unique_key. Ελέγξτε το αρχικό dataset.")

    rng = random.Random(SEED)
    modified = [dict(row) for row in original_rows]
    used_targets: set[int] = set()
    selected: dict[str, list[int]] = {}

    for kind, _, _ in TYPES:
        candidates = [i for i, row in enumerate(original_rows)
                      if i not in used_targets and (kind != "duplicate_unique_key" or i > 0) and eligible(row, kind)]
        if len(candidates) < ERRORS_PER_TYPE:
            raise ValueError(f"Δεν υπάρχουν {ERRORS_PER_TYPE} κατάλληλες εγγραφές για {kind}.")
        picked = sorted(rng.sample(candidates, ERRORS_PER_TYPE))
        selected[kind] = picked
        used_targets.update(picked)

    # Για κάθε διπλότυπο αντιγράφουμε το κλειδί από προηγούμενη εγγραφή που
    # δεν έχει επιλεγεί προς αλλοίωση, ώστε να υπάρχει ακριβώς μία νέα παράβαση.
    duplicate_sources: dict[int, int] = {}
    for target in selected["duplicate_unique_key"]:
        sources = [i for i in range(target) if i not in used_targets]
        if not sources:
            raise ValueError("Δεν υπάρχει διαθέσιμη προηγούμενη εγγραφή για διπλότυπο.")
        duplicate_sources[target] = sources[0]

    truth: list[dict[str, object]] = []
    for kind, column, check_id in TYPES:
        for i in selected[kind]:
            old = original_rows[i][column]
            if kind == "missing_agency":
                new = ""
            elif kind == "duplicate_unique_key":
                new = original_rows[duplicate_sources[i]]["unique_key"]
            elif kind == "invalid_unique_key":
                new = f"INVALID_KEY_{i+1}"
            elif kind == "invalid_closed_date":
                new = "not-a-date"
            elif kind == "invalid_latitude":
                new = "999"
            elif kind == "invalid_zip":
                new = "ABCDE"
            elif kind == "reversed_dates":
                closed = parse_date(original_rows[i]["closed_date"])
                assert closed is not None
                # Διατηρούμε τη σωστή μορφή ημερομηνίας, αλλά αντιστρέφουμε τη σειρά.
                new = (closed + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
            else:
                raise AssertionError(kind)
            if old == new:
                raise ValueError(f"Η αλλοίωση δεν άλλαξε την εγγραφή {i+1} ({kind}).")
            modified[i][column] = new
            truth.append({
                "error_type": kind,
                "expected_check_id": check_id,
                "row_number": i + 1,
                "column": column,
                "original_value": old,
                "corrupted_value": new,
                "source_row_number": duplicate_sources[i] + 1 if kind == "duplicate_unique_key" else "",
            })

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(modified)

    fields = ["error_type", "expected_check_id", "row_number", "column",
              "original_value", "corrupted_value", "source_row_number"]
    with GROUND_TRUTH_CSV.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(sorted(truth, key=lambda item: int(item["row_number"])))

    manifest = {
        "source": str(INPUT_CSV),
        "output": str(OUTPUT_CSV),
        "seed": SEED,
        "original_rows": len(original_rows),
        "columns": len(columns),
        "errors_per_type": ERRORS_PER_TYPE,
        "total_injected_changes": len(truth),
        "error_type_counts": dict(Counter(item["error_type"] for item in truth)),
        "note": "Το ground truth δηλώνει τις γνωστές αλλαγές, όχι όλα τα προϋπάρχοντα προβλήματα. "
                "Οι έλεγχοι της εφαρμογής ενδέχεται να έχουν επιπλέον ευρήματα βάσης.",
    }
    with MANIFEST_JSON.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)

    print(f"Αρχικό dataset: {len(original_rows):,} εγγραφές, {len(columns)} στήλες")
    for kind, count in manifest["error_type_counts"].items():
        print(f"{kind}: {count} αλλοιώσεις")
    print(f"Σύνολο: {len(truth)} αλλαγές σε {len(used_targets)} διαφορετικές εγγραφές")
    print(f"Αλλοιωμένο CSV: {OUTPUT_CSV}")
    print(f"Ground truth: {GROUND_TRUTH_CSV}")
    print(f"Μεταδεδομένα: {MANIFEST_JSON}")


if __name__ == "__main__":
    main()
