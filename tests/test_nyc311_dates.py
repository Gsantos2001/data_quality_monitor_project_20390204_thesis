from datetime import datetime

from data_quality_monitor.checks import _strict_date


def test_nyc311_date_with_milliseconds():
    # Έλεγχος έγκυρης ημερομηνίας με τρία ψηφία χιλιοστών.
    value = "2020-09-25T15:43:34.000"
    date_format = "%Y-%m-%dT%H:%M:%S.%f"

    result = _strict_date(value, date_format)

    assert result == datetime(2020, 9, 25, 15, 43, 34)


def test_nyc311_date_with_nonzero_milliseconds():
    # Έλεγχος ημερομηνίας με μη μηδενικά χιλιοστά.
    value = "2020-09-25T15:43:34.123"

    result = _strict_date(value, "%Y-%m-%dT%H:%M:%S.%f")

    assert result == datetime(2020, 9, 25, 15, 43, 34, 123000)


def test_nyc311_invalid_date():
    # Έλεγχος απόρριψης ημερομηνίας με μη έγκυρο μήνα.
    value = "2020-13-25T15:43:34.000"

    result = _strict_date(value, "%Y-%m-%dT%H:%M:%S.%f")

    assert result is None


def test_nyc311_date_without_milliseconds():
    # Έλεγχος απόρριψης ημερομηνίας χωρίς τα απαιτούμενα χιλιοστά.
    value = "2020-09-25T15:43:34"

    result = _strict_date(value, "%Y-%m-%dT%H:%M:%S.%f")

    assert result is None