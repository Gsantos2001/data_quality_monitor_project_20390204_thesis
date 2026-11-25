
import argparse
import hashlib
from pathlib import Path

import pandas as pd


SEED = 20390204
CORRUPTION_COUNT = 20
CHECK_ID = "borough_allowed_values"

ALLOWED_VALUES = [
    "BRONX",
    "BROOKLYN",
    "MANHATTAN",
    "QUEENS",
    "STATEN ISLAND",
]


def main():
    parser = argparse.ArgumentParser(
        description="Δημιουργία ελεγχόμενων αλλοιώσεων κατηγορικών τιμών."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("nyc311_allowed_values_experiment"),
    )
    args = parser.parse_args()

    # Υπολογισμός του αρχικού ψηφιακού αποτυπώματος.
    original_hash = hashlib.sha256(
        args.input.read_bytes()
    ).hexdigest()

    # Ανάγνωση χωρίς αυτόματη μετατροπή ελλιπών τιμών.
    df = pd.read_csv(
        args.input,
        dtype="string",
        keep_default_na=False,
        encoding="utf-8-sig",
    )

    if "borough" not in df.columns:
        raise ValueError("Δεν υπάρχει η απαιτούμενη στήλη borough.")

    corrupted = df.copy(deep=True)

    # Επιλογή εγγραφών που περιέχουν αρχικά επιτρεπόμενες τιμές.
    eligible = df.loc[df["borough"].isin(ALLOWED_VALUES)]

    if len(eligible) < CORRUPTION_COUNT:
        raise ValueError("Δεν υπάρχουν αρκετές κατάλληλες εγγραφές.")

    # Αναπαραγώγιμη επιλογή 20 διαφορετικών εγγραφών.
    selected = eligible.sample(
        n=CORRUPTION_COUNT,
        random_state=SEED,
        replace=False,
    ).sort_index()

    ground_truth = []

    # Εισαγωγή μη επιτρεπόμενων κατηγορικών τιμών.
    for number, index in enumerate(selected.index, start=1):
        original_value = str(df.at[index, "borough"])
        corrupted_value = f"INVALID_BOROUGH_{number:02d}"

        corrupted.at[index, "borough"] = corrupted_value

        ground_truth.append({
            "check_id": CHECK_ID,
            "row_number": int(index) + 1,
            "column": "borough",
            "original_value": original_value,
            "corrupted_value": corrupted_value,
        })

    # Επαλήθευση ότι άλλαξαν ακριβώς 20 εγγραφές
    # και ότι οι υπόλοιπες στήλες παρέμειναν ίδιες.
    changed_count = int(
        (df["borough"] != corrupted["borough"]).sum()
    )

    assert changed_count == CORRUPTION_COUNT
    assert df.shape == corrupted.shape
    assert df.drop(columns=["borough"]).equals(
        corrupted.drop(columns=["borough"])
    )

    # Δημιουργία ξεχωριστών αρχείων αποτελεσμάτων.
    args.output.mkdir(parents=True, exist_ok=True)

    corrupted_path = (
        args.output / "nyc311_10000_allowed_values_corrupted.csv"
    )
    ground_truth_path = args.output / "ground_truth.csv"

    corrupted.to_csv(
        corrupted_path,
        index=False,
        encoding="utf-8-sig",
        mode="x",
    )

    pd.DataFrame(ground_truth).to_csv(
        ground_truth_path,
        index=False,
        encoding="utf-8-sig",
        mode="x",
    )

    # Επιβεβαίωση της ακεραιότητας του αρχικού αρχείου.
    final_hash = hashlib.sha256(
        args.input.read_bytes()
    ).hexdigest()

    assert original_hash == final_hash

    print(f"Εγγραφές: {len(df)}")
    print(f"Στήλες: {len(df.columns)}")
    print(f"Κατάλληλες εγγραφές: {len(eligible)}")
    print(f"Τιμή αρχικοποίησης: {SEED}")
    print(f"Ελεγχόμενες αλλοιώσεις: {changed_count}")
    print("Το αρχικό αρχείο διατηρήθηκε χωρίς τροποποιήσεις.")
    print(f"Αλλοιωμένο αρχείο: {corrupted_path}")
    print(f"Αναμενόμενα ευρήματα: {ground_truth_path}")


if __name__ == "__main__":
    main()
