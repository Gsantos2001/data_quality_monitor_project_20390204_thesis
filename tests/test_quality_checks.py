#Ελεγχόμενες δοκιμές με προκαθορισμένα σφάλματα για την πειραματική αξιολόγηση της διπλωματικής εργασίας.
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from data_quality_monitor.__main__ import main
from data_quality_monitor.checks import check_consistency, check_duplicate, check_missing, check_validity
from data_quality_monitor.engine import evaluate_dataframe, run_analysis
from data_quality_monitor.io import DataInputError, read_csv
from data_quality_monitor.rules import RulesError, load_rules, validate_rules

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "examples" / "sample_data.csv"
RULES = ROOT / "examples" / "rules.json"


def sample_results():
    df = read_csv(SAMPLE)
    results = evaluate_dataframe(df, load_rules(RULES))
    return df, {r.check_id: r for r in results}


def test_seeded_errors_exact_counts():
    df, results = sample_results()
    assert len(df) == 12
    expected = {
        "missing:product_name": (3, [2, 9, 10]),
        "duplicates_full_row": (1, [7]),
        "duplicate_product_id": (2, [7, 8]),
        "quantity_nonnegative": (1, [3]),
        "unit_price_nonnegative": (2, [4, 11]),
        "allowed_category": (1, [5]),
        "start_date_format": (1, [6]),
        "end_date_format": (0, []),
        "date_order": (1, [12]),
        "total_calculation": (1, [12]),
    }
    for key, (count, positions) in expected.items():
        assert results[key].status == "completed", key
        assert results[key].issue_count == count, key
        assert [f.row_number for f in results[key].findings] == positions, key
    assert results["missing:product_name"].issue_rate_percent == 25.0
    assert results["date_order"].checked_count == 11
    assert results["date_order"].not_evaluated_count == 1
    assert results["total_calculation"].checked_count == 11


def test_missing_values_detect_blank_whitespace_and_configured_token():
    df = pd.DataFrame({"value": ["", "   ", "null", " NA ", "valid", "NA-v"]})
    result = check_missing(df, ["", "NULL", "NA"])[0]
    assert result.issue_count == 4
    assert [f.row_number for f in result.findings] == [1, 2, 3, 4]
    assert result.issue_rate_percent == 66.67


def test_missing_identifiers_are_not_treated_as_duplicate_ids():
    df = pd.DataFrame({"id": ["", "", "A", "A", "B"], "name": ["a", "b", "x", "y", "z"]})
    result = check_duplicate(df, {"id": "unique_id", "columns": ["id"]}, [""])
    assert result.issue_count == 1
    assert result.checked_count == 3
    assert result.not_evaluated_count == 2
    assert [f.row_number for f in result.findings] == [4]


def test_default_rules_run_only_missing_and_full_duplicates():
    df = pd.DataFrame({"a": ["1", "1"]})
    results = evaluate_dataframe(df, load_rules(None))
    assert len(results) == 2
    assert results[1].check_id == "duplicates_full_row"
    assert results[1].issue_count == 1


def test_numeric_invalid_not_counted_as_missing():
    df = pd.DataFrame({"amount": ["not a number", "-1", "0", "3.5", ""]})
    rule = {"id": "amount_check", "column": "amount", "kind": "numeric_range", "min": 0, "integer": True}
    result = check_validity(df, rule, [""])
    assert result.issue_count == 3
    assert result.checked_count == 4
    assert result.not_evaluated_count == 1
    assert [f.row_number for f in result.findings] == [1, 2, 4]


def test_regex_uses_full_match():
    df = pd.DataFrame({"code": ["P001", "P1", "xxP001", "P002", ""]})
    rule = {"id": "code_format", "column": "code", "kind": "regex", "pattern": "P[0-9]{3}"}
    result = check_validity(df, rule, [""])
    assert [f.row_number for f in result.findings] == [2, 3]
    assert result.checked_count == 4


def test_date_validation_is_strict_and_calendar_aware():
    df = pd.DataFrame({"date": ["2026-02-28", "2026-02-30", "2026-2-8", "", "2024-02-29"]})
    result = check_validity(df, {"id": "date", "column": "date", "kind": "date_format", "format": "%Y-%m-%d"}, [""])
    assert [f.row_number for f in result.findings] == [2, 3]
    assert result.checked_count == 4


def test_consistency_excludes_unparseable_and_missing_instead_of_false_positive():
    df = pd.DataFrame({"start": ["2026-01-02", "BAD", "", "2026-01-04"],
                       "end": ["2026-01-01", "2026-01-01", "2026-01-02", "2026-01-05"]})
    rule = {"id": "date_order", "kind": "comparison", "left": "start", "right": "end",
            "operator": "<=", "data_type": "date", "format": "%Y-%m-%d"}
    result = check_consistency(df, rule, [""])
    assert result.issue_count == 1
    assert result.checked_count == 2
    assert result.not_evaluated_count == 2
    assert result.findings[0].row_number == 1


def test_product_equals_uses_absolute_tolerance():
    df = pd.DataFrame({"qty": ["2", "3", "1"], "price": ["2.5", "4", "x"],
                       "sum": ["5.009", "20", "1"]})
    rule = {"id": "sum", "kind": "product_equals", "left": "qty", "right": "price",
            "result": "sum", "tolerance": 0.01}
    result = check_consistency(df, rule, [""])
    assert result.issue_count == 1
    assert result.checked_count == 2
    assert result.not_evaluated_count == 1
    assert [f.row_number for f in result.findings] == [2]


def test_missing_rule_columns_are_skipped_not_success():
    df = pd.DataFrame({"a": ["1", "2"]})
    rules = {"missing_tokens": [""], "duplicate_checks": [{"id": "dup", "columns": ["absent"]}],
             "validity_checks": [{"id": "value", "column": "absent", "kind": "numeric_range", "min": 0}],
             "consistency_checks": [{"id": "cmp", "kind": "comparison", "left": "a", "right": "absent",
                                     "operator": "<=", "data_type": "number"}]}
    for result in evaluate_dataframe(df, rules)[1:]:
        assert result.status == "skipped"
        assert result.issue_count is None
        assert result.issue_rate_percent is None


def test_empty_dataset_has_no_zero_divisions(tmp_path):
    file_path = tmp_path / "empty.csv"
    file_path.write_text("id,price\n", encoding="utf-8")
    folder, report = run_analysis(file_path, RULES, tmp_path / "out")
    assert report["metadata"]["row_count"] == 0
    assert report["check_status_counts"]["skipped"] == len(report["checks"])
    assert all(c["issue_rate_percent"] is None for c in report["checks"])
    assert (folder / "report.json").is_file()


def test_unreadable_files_do_not_generate_reports(tmp_path):
    with pytest.raises(DataInputError):
        run_analysis(tmp_path / "missing.csv", RULES, tmp_path / "out")
    assert not (tmp_path / "out").exists()
    empty = tmp_path / "no_header.csv"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(DataInputError):
        read_csv(empty)


def test_invalid_and_duplicate_rule_ids_are_rejected():
    with pytest.raises(RulesError):
        validate_rules({"duplicate_checks": [{"id": "x", "columns": None}],
                        "validity_checks": [{"id": "x", "kind": "numeric_range", "column": "a"}]})
    with pytest.raises(RulesError):
        validate_rules({"validity_checks": [{"id": "x", "kind": "regex", "column": "a", "pattern": "["}]})
    with pytest.raises(RulesError):
        validate_rules({"validity_checks": [{"id": "x", "kind": "numeric_range", "column": "a", "min": 5, "max": 3}]})


def test_original_csv_bytes_unchanged_and_new_report_directories(tmp_path):
    input_file = tmp_path / "input.csv"
    source_bytes = SAMPLE.read_bytes()
    input_file.write_bytes(source_bytes)
    first_folder, first_report = run_analysis(input_file, RULES, tmp_path / "reports")
    second_folder, second_report = run_analysis(input_file, RULES, tmp_path / "reports")
    assert input_file.read_bytes() == source_bytes
    assert first_folder != second_folder
    assert first_report["checks"] == second_report["checks"]
    for folder in (first_folder, second_folder):
        assert {p.name for p in folder.iterdir()} == {
            "report.json", "checks.csv", "findings.csv", "summary.txt"
        }
        assert json.loads((folder / "report.json").read_text(encoding="utf-8"))["metadata"]["row_count"] == 12


def test_evaluating_dataframe_does_not_mutate_values():
    frame = read_csv(SAMPLE)
    old = frame.copy(deep=True)
    evaluate_dataframe(frame, load_rules(RULES))
    pd.testing.assert_frame_equal(frame, old)


def test_cli_returns_zero_for_detected_data_issues_and_two_for_missing_file(tmp_path, capsys):
    code = main(["--input", str(SAMPLE), "--rules", str(RULES), "--output", str(tmp_path)])
    assert code == 0
    assert "Ολοκληρώθηκε" in capsys.readouterr().out
    code = main(["--input", str(tmp_path / "none.csv"), "--output", str(tmp_path)])
    assert code == 2
    assert "Σφάλμα" in capsys.readouterr().err


def test_text_length_with_greek_text_and_missing_values():
    import pandas as pd
    from data_quality_monitor.checks import check_validity

    df = pd.DataFrame({
        "description": [
            "Πρόβλημα",
            "Δεν λειτουργεί η σύνδεση",
            "",
            "   Πρόβλημα   ",
            "Α" * 101,
            "NULL",
        ]
    })

    rule = {
        "id": "description_length",
        "column": "description",
        "kind": "text_length",
        "min_length": 15,
        "max_length": 100,
    }

    result = check_validity(df, rule, ["", "NULL"])

    assert result.status == "completed"
    assert result.checked_count == 4
    assert result.issue_count == 3
    assert result.not_evaluated_count == 2
    assert result.issue_rate_percent == 75.0

    finding_rows = [
        finding.row_number
        for finding in result.findings
    ]

    assert finding_rows == [1, 4, 5]




def test_text_length_rule_validation():
    import pytest
    from data_quality_monitor.rules import (
        RulesError,
        validate_rules,
    )

    valid_rule = {
        "id": "description_length",
        "column": "description",
        "kind": "text_length",
        "min_length": 10,
        "max_length": 100,
    }

    # Έγκυρος κανόνας με δύο όρια.
    validate_rules({
        "validity_checks": [valid_rule]
    })

    # Έγκυροι κανόνες με μόνο ένα όριο.
    for limit in ("min_length", "max_length"):
        rule = {
            "id": "description_length",
            "column": "description",
            "kind": "text_length",
            limit: 10,
        }
        validate_rules({"validity_checks": [rule]})

    # Μη έγκυρες τιμές ορίων.
    invalid_cases = [
        {"min_length": -1},
        {"min_length": True},
        {"min_length": "10"},
        {"min_length": 5.5},
        {"min_length": 101, "max_length": 100},
    ]

    for changes in invalid_cases:
        rule = {**valid_rule, **changes}

        with pytest.raises(RulesError):
            validate_rules({
                "validity_checks": [rule]
            })

    # Κανόνας χωρίς κανένα όριο.
    rule_without_limits = {
        "id": "description_length",
        "column": "description",
        "kind": "text_length",
    }

    with pytest.raises(RulesError):
        validate_rules({
            "validity_checks": [rule_without_limits]
        })


def test_numeric_range_rejects_invalid_limits():
    #Τα αριθμητικά όρια πρέπει να είναι πραγματικοί και πεπερασμένοι αριθμοί και όχι τιμές null, NaN ή άπειρο.
    invalid_limits = [None, True, "10", float("nan"), float("inf"), float("-inf")]
    for name in ("min", "max"):
        for value in invalid_limits:
            rule = {
                "id": "numeric_limits", "column": "amount",
                "kind": "numeric_range", name: value,
            }
            with pytest.raises(RulesError):
                validate_rules({"validity_checks": [rule]})

    with pytest.raises(RulesError):
        validate_rules({"validity_checks": [{
            "id": "numeric_limits", "column": "amount",
            "kind": "numeric_range", "min": 10, "max": 5,
        }]})

    validate_rules({"validity_checks": [{
        "id": "numeric_limits", "column": "amount",
        "kind": "numeric_range", "min": 0, "max": 10,
    }]})


def test_date_format_requires_format_string():
    #Οι έλεγχοι ημερομηνιών απαιτούν τον ρητό καθορισμό μιας μη κενής συμβολοσειράς μορφοποίησης.
    rule = {"id": "valid_date", "column": "created_at", "kind": "date_format"}
    for invalid_format in (None, "", 123):
        invalid = dict(rule)
        if invalid_format is not None:
            invalid["format"] = invalid_format
        with pytest.raises(RulesError):
            validate_rules({"validity_checks": [invalid]})

    validate_rules({"validity_checks": [{**rule, "format": "%Y-%m-%d"}]})
