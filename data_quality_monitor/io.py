"""Φόρτωση αρχείων CSV χωρίς τροποποίηση των αρχικών αρχείων στον δίσκο."""
from __future__ import annotations

from pathlib import Path
import pandas as pd


class DataInputError(ValueError):
    pass


def read_csv(file_path: str | Path) -> pd.DataFrame:
    path = Path(file_path)
    if not path.is_file():
        raise DataInputError(f"Το αρχείο δεν βρέθηκε: {path}")
    if path.suffix.lower() != ".csv":
        raise DataInputError("Η αρχική έκδοση υποστηρίζει μόνο αρχεία .csv")
    try:
        #Διατήρηση των αρχικών κειμενικών τιμών χωρίς αυτόματες μετατροπές. Τα αναγνωριστικά δεν μετατρέπονται αυτόματα σε αριθμούς και τιμές όπως 'NA' δεν αντιμετωπίζονται ως null.
        return pd.read_csv(path, dtype="string", keep_default_na=False, encoding="utf-8-sig")
    except (OSError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise DataInputError(f"Αδυναμία ανάγνωσης του CSV: {exc}") from exc
