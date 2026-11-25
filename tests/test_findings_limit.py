#Δοκιμές διατήρησης συγκεντρωτικών αποτελεσμάτων με περιορισμένα ευρήματα.
import pandas as pd
import pytest
from data_quality_monitor.engine import evaluate_dataframe
from data_quality_monitor.models import completed


def test_limit_missing_and_validity():
    df = pd.DataFrame({"a": ["", "", "", "5", "oops"], "b": ["x", "x", "x", "x", "x"]})
    rules = {"missing_tokens": [""], "validity_checks": [{
        "id": "numeric", "column": "a", "kind": "numeric_range", "min": 0, "max": 4
    }]}
    full = evaluate_dataframe(df, rules)
    limited = evaluate_dataframe(df, rules, max_findings=1)
    assert [(r.check_id, r.issue_count, r.checked_count, r.status) for r in full] == [
        (r.check_id, r.issue_count, r.checked_count, r.status) for r in limited]
    assert len(limited[0].findings) == 1
    assert limited[0].issue_count == 3
    assert limited[0].findings_truncated is True
    assert limited[-1].issue_count == 2
    assert len(limited[-1].findings) == 1


def test_zero_limit_preserves_counts():
    df = pd.DataFrame({"id": ["a", "a", "a"], "left": [5, 5, 5], "right": [4, 4, 4]})
    rules = {"duplicate_checks": [{"id": "dups", "columns": ["id"]}],
             "consistency_checks": [{"id": "compare", "kind": "comparison", "left": "left", "right": "right", "operator": "<="}]}
    limited = evaluate_dataframe(df, rules, max_findings=0)
    by_id = {r.check_id: r for r in limited}
    assert by_id["dups"].issue_count == 2
    assert by_id["compare"].issue_count == 3
    assert all(not r.findings for r in limited)
    assert by_id["dups"].findings_truncated is True


def test_default_keeps_all_findings():
    results = evaluate_dataframe(pd.DataFrame({"a": ["", ""]}), {})
    assert results[0].issue_count == len(results[0].findings) == 2
    assert results[0].findings_truncated is False


def test_invalid_limit():
    with pytest.raises(ValueError):
        evaluate_dataframe(pd.DataFrame({"a": ["a"]}), {}, max_findings=-1)


def test_count_cannot_be_smaller_than_stored_findings():
    with pytest.raises(ValueError):
        completed("x", "missing", 1, [object()], issue_count=0)
