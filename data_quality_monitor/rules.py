"""Ανάγνωση και επικύρωση κανόνων αξιολόγησης από μια απλή και σαφώς καθορισμένη δομή JSON."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any


class RulesError(ValueError):
    pass


DEFAULT_RULES: dict[str, Any] = {
    "missing_tokens": ["", "NULL", "N/A", "NaN"],
    "duplicate_checks": [{"id": "duplicates_full_row", "columns": None}],
    "validity_checks": [],
    "consistency_checks": [],
}


def _str_field(rule: dict[str, Any], key: str) -> str:
    value = rule.get(key)
    if not isinstance(value, str) or not value:
        raise RulesError(f"Ο κανόνας {rule.get('id', '<χωρίς id>')} χρειάζεται πεδίο '{key}' (κείμενο).")
    return value


def load_rules(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        rules = json.loads(json.dumps(DEFAULT_RULES))
    else:
        try:
            with Path(path).open("r", encoding="utf-8-sig") as stream:
                rules = json.load(stream)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RulesError(f"Αδυναμία ανάγνωσης κανόνων JSON: {exc}") from exc
    validate_rules(rules)
    return rules


def validate_rules(rules: Any) -> None:
    if not isinstance(rules, dict):
        raise RulesError("Οι κανόνες πρέπει να είναι αντικείμενο JSON.")
    tokens = rules.get("missing_tokens", [""])
    if not isinstance(tokens, list) or not all(isinstance(x, str) for x in tokens):
        raise RulesError("Το missing_tokens πρέπει να είναι λίστα κειμένων.")

    ids: set[str] = set()
    for category in ("duplicate_checks", "validity_checks", "consistency_checks"):
        items = rules.get(category, [])
        if not isinstance(items, list):
            raise RulesError(f"Το '{category}' πρέπει να είναι λίστα.")
        for rule in items:
            if not isinstance(rule, dict):
                raise RulesError(f"Κάθε στοιχείο του '{category}' πρέπει να είναι αντικείμενο.")
            rule_id = _str_field(rule, "id")
            if rule_id in ids or rule_id.startswith("missing:"):
                raise RulesError(f"Μη μοναδικό ή δεσμευμένο id κανόνα: {rule_id}")
            ids.add(rule_id)

            if category == "duplicate_checks":
                columns = rule.get("columns")
                if columns is not None and (
                    not isinstance(columns, list) or not columns or
                    not all(isinstance(x, str) and x for x in columns)
                ):
                    raise RulesError(f"{rule_id}: columns = null ή μη κενή λίστα στηλών.")

            elif category == "validity_checks":
                _str_field(rule, "column")
                kind = rule.get("kind")
                if kind not in (
                    "numeric_range",
                    "allowed_values",
                    "regex",
                    "date_format",
                    "text_length",
                ):
                    raise RulesError(f"{rule_id}: μη υποστηριζόμενο kind: {kind}")
                if kind == "numeric_range":
                    for name in ("min", "max"):
                        if name in rule:
                            x = rule[name]
                            if type(x) not in (float, int) or (
                                isinstance(x, float) and not math.isfinite(x)
                            ):
                                raise RulesError(
                                    f"{rule_id}: {name} πρέπει να είναι πεπερασμένος αριθμός."
                                )
                    if "integer" in rule and not isinstance(rule["integer"], bool):
                        raise RulesError(f"{rule_id}: integer πρέπει να είναι true/false.")
                    if "min" in rule and "max" in rule and rule["min"] > rule["max"]:
                        raise RulesError(f"{rule_id}: min δεν μπορεί να είναι μεγαλύτερο από max.")
                if kind == "allowed_values":
                    values = rule.get("values")
                    if not isinstance(values, list) or not values or not all(isinstance(x, str) for x in values):
                        raise RulesError(f"{rule_id}: values πρέπει να είναι μη κενή λίστα κειμένων.")
                if kind == "regex":
                    try:
                        re.compile(_str_field(rule, "pattern"))
                    except re.error as exc:
                        raise RulesError(f"{rule_id}: μη έγκυρο regex: {exc}") from exc
                if kind == "date_format":
                    _str_field(rule, "format")
                
                if kind == "text_length":
                    if "min_length" not in rule and "max_length" not in rule:
                        raise RulesError(
                            f"{rule_id}: απαιτείται min_length ή max_length."
                        )

                    for name in ("min_length", "max_length"):
                        if name in rule:
                            value = rule[name]

                            if type(value) is not int or value < 0:
                                raise RulesError(
                                    f"{rule_id}: {name} πρέπει να είναι "
                                    "μη αρνητικός ακέραιος."
                                )

                    if (
                        "min_length" in rule
                        and "max_length" in rule
                        and rule["min_length"] > rule["max_length"]
                    ):
                        raise RulesError(
                            f"{rule_id}: min_length δεν μπορεί να "
                            "είναι μεγαλύτερο από max_length."
                        )


            elif category == "consistency_checks":
                kind = rule.get("kind")
                if kind == "comparison":
                    _str_field(rule, "left")
                    _str_field(rule, "right")
                    if rule.get("operator") not in ("<", "<=", "==", "!=", ">=", ">"):
                        raise RulesError(f"{rule_id}: μη έγκυρος τελεστής.")
                    if rule.get("data_type", "number") not in ("number", "date", "string"):
                        raise RulesError(f"{rule_id}: data_type πρέπει να είναι number, date ή string.")
                    if rule.get("data_type") == "date":
                        _str_field(rule, "format")
                elif kind == "product_equals":
                    for name in ("left", "right", "result"):
                        _str_field(rule, name)
                    tol = rule.get("tolerance", 0.01)
                    if type(tol) not in (int, float) or tol < 0:
                        raise RulesError(f"{rule_id}: tolerance πρέπει να είναι μη αρνητικός αριθμός.")
                else:
                    raise RulesError(f"{rule_id}: μη υποστηριζόμενο kind: {kind}")
