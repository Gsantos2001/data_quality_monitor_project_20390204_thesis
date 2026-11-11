import json
import csv
import pytest
from data_quality_monitor.monitoring import (
    build_check_history,
    compare_reports,
    load_report,
    save_check_history,
    save_check_history_csv,
)
from data_quality_monitor.__main__ import main

def test_compare_reports_detects_trends():
    old_report = {
        "metadata": {
            "input_file": "products.csv",
            "rules_sha256": "same_rules"
        },
        "checks": [
            {
                "check_id": "missing:name",
                "status": "completed",
                "issue_rate_percent": 25.0
            },
            {
                "check_id": "duplicate_id",
                "status": "completed",
                "issue_rate_percent": 10.0
            },
            {
                "check_id": "valid_price",
                "status": "completed",
                "issue_rate_percent": 5.0
            }
        ]
    }

    new_report = {
        "metadata": {
            "input_file": "products.csv",
            "rules_sha256": "same_rules"
        },
        "checks": [
            {
                "check_id": "missing:name",
                "status": "completed",
                "issue_rate_percent": 10.0
            },
            {
                "check_id": "duplicate_id",
                "status": "completed",
                "issue_rate_percent": 20.0
            },
            {
                "check_id": "valid_price",
                "status": "completed",
                "issue_rate_percent": 5.0
            }
        ]
    }

    results = compare_reports(old_report, new_report)

    trends = {
        result["check_id"]: result["trend"]
        for result in results
    }

    assert len(results) == 3
    assert trends["missing:name"] == "improved"
    assert trends["duplicate_id"] == "worsened"
    assert trends["valid_price"] == "unchanged"


def test_compare_reports_rejects_different_rules():
    old_report = {
        "metadata": {
            "input_file": "products.csv",
            "rules_sha256": "rules_version_1"
        },
        "checks": []
    }

    new_report = {
        "metadata": {
            "input_file": "products.csv",
            "rules_sha256": "rules_version_2"
        },
        "checks": []
    }

    with pytest.raises(ValueError, match="διαφορετικούς κανόνες"):
        compare_reports(old_report, new_report)



def test_compare_reports_ignores_incomplete_checks():
    old_report = {
        "metadata": {
            "input_file": "products.csv",
            "rules_sha256": "same_rules"
        },
        "checks": [
            {
                "check_id": "missing:name",
                "status": "completed",
                "issue_rate_percent": 20.0
            },
            {
                "check_id": "valid:price",
                "status": "completed",
                "issue_rate_percent": 10.0
            },
            {
                "check_id": "valid:date",
                "status": "error",
                "issue_rate_percent": None
            }
        ]
    }

    new_report = {
        "metadata": {
            "input_file": "products.csv",
            "rules_sha256": "same_rules"
        },
        "checks": [
            {
                "check_id": "missing:name",
                "status": "completed",
                "issue_rate_percent": 10.0
            },
            {
                "check_id": "valid:price",
                "status": "skipped",
                "issue_rate_percent": None
            },
            {
                "check_id": "valid:date",
                "status": "completed",
                "issue_rate_percent": 5.0
            }
        ]
    }

    results = compare_reports(old_report, new_report)

    assert len(results) == 1
    assert results[0]["check_id"] == "missing:name"
    assert results[0]["trend"] == "improved"
    assert results[0]["change_percentage_points"] == -10.0



def test_build_check_history(tmp_path):
    rates_and_rules = [
        (25.0, "same_rules"),
        (16.67, "same_rules"),
        (25.0, "same_rules"),
        (99.0, "different_rules"),
    ]

    for index, (rate, rules_hash) in enumerate(rates_and_rules, start=1):
        run_dir = tmp_path / f"run_20260101_00000{index}_000000Z"
        run_dir.mkdir()

        report = {
            "metadata": {
                "input_file": "products.csv",
                "rules_sha256": rules_hash,
                "generated_at_utc": f"2026-01-01T00:00:0{index}+00:00",
            },
            "checks": [
                {
                    "check_id": "missing:name",
                    "status": "completed",
                    "issue_rate_percent": rate,
                }
            ],
        }

        report_path = run_dir / "report.json"
        report_path.write_text(
            json.dumps(report),
            encoding="utf-8",
        )

        if index == 3:
            reference_path = report_path

    history = build_check_history(
        tmp_path,
        reference_path,
        "missing:name",
    )

    assert len(history) == 3

    assert [item["issue_rate_percent"] for item in history] == [
        25.0, 16.67, 25.0
    ]

    assert [item["trend"] for item in history] == [
        None, "improved", "worsened"
    ]

    assert [item["change_percentage_points"] for item in history] == [
        None, -8.33, 8.33
    ]



def test_save_check_history(tmp_path):
    history = [
        {
            "generated_at_utc": "2026-01-01T10:00:00+00:00",
            "report_path": "reports/run_1/report.json",
            "status": "completed",
            "issue_rate_percent": 25.0,
            "change_percentage_points": None,
            "trend": None
        }
    ]

    output_path = tmp_path / "monitoring_reports" / "history.json"

    saved_path = save_check_history(history, output_path)

    # Ελέγχουμε ότι δημιουργήθηκε το αρχείο.
    assert saved_path == output_path
    assert output_path.is_file()

    # Διαβάζουμε ξανά το JSON και ελέγχουμε το περιεχόμενο.
    saved_history = json.loads(
        output_path.read_text(encoding="utf-8")
    )

    assert saved_history == history

    # Ελέγχουμε ότι δεν αντικαθίσταται υπάρχον αρχείο.
    with pytest.raises(FileExistsError):
        save_check_history(history, output_path)

    # Βεβαιωνόμαστε ότι το περιεχόμενο δεν άλλαξε.
    assert json.loads(
        output_path.read_text(encoding="utf-8")
    ) == history



def test_save_check_history_csv(tmp_path):
    history = [
        {
            "generated_at_utc": "2026-01-01T10:00:00+00:00",
            "report_path": "reports/run_1/report.json",
            "status": "completed",
            "issue_rate_percent": 25.0,
            "change_percentage_points": None,
            "trend": None,
        },
        {
            "generated_at_utc": "2026-01-02T10:00:00+00:00",
            "report_path": "reports/run_2/report.json",
            "status": "completed",
            "issue_rate_percent": 16.67,
            "change_percentage_points": -8.33,
            "trend": "improved",
        },
    ]

    output_path = tmp_path / "monitoring_reports" / "history.csv"

    saved_path = save_check_history_csv(history, output_path)

    assert saved_path == output_path
    assert output_path.is_file()

    with output_path.open(
        "r", encoding="utf-8-sig", newline=""
    ) as file:
        reader = csv.DictReader(file, delimiter=";")
        rows = list(reader)

        assert reader.fieldnames == [
            "generated_at_utc",
            "report_path",
            "status",
            "issue_rate_percent",
            "change_percentage_points",
            "trend",
        ]

    assert len(rows) == 2

    assert rows[0]["issue_rate_percent"] == "25.0"
    assert rows[0]["change_percentage_points"] == ""
    assert rows[0]["trend"] == ""

    assert rows[1]["issue_rate_percent"] == "16.67"
    assert rows[1]["change_percentage_points"] == "-8.33"
    assert rows[1]["trend"] == "improved"

    original_content = output_path.read_bytes()

    with pytest.raises(FileExistsError):
        save_check_history_csv(history, output_path)

    assert output_path.read_bytes() == original_content




def test_monitor_cli_creates_history_files(tmp_path):
    reports_dir = tmp_path / "reports"
    output_dir = tmp_path / "monitoring_reports"

    rates = [25.0, 10.0]

    for index, rate in enumerate(rates, start=1):
        run_dir = reports_dir / f"run_2026010{index}_120000_000000Z"
        run_dir.mkdir(parents=True)

        report = {
            "metadata": {
                "input_file": "products.csv",
                "rules_sha256": "same_rules",
                "generated_at_utc": (
                    f"2026-01-0{index}T12:00:00+00:00"
                ),
            },
            "checks": [
                {
                    "check_id": "missing:name",
                    "status": "completed",
                    "issue_rate_percent": rate,
                }
            ],
        }

        (run_dir / "report.json").write_text(
            json.dumps(report),
            encoding="utf-8",
        )

    exit_code = main([
        "monitor",
        "--reports", str(reports_dir),
        "--check", "missing:name",
        "--output", str(output_dir),
    ])

    assert exit_code == 0

    json_files = list(output_dir.glob("*.json"))
    csv_files = list(output_dir.glob("*.csv"))

    assert len(json_files) == 1
    assert len(csv_files) == 1

    history = json.loads(
        json_files[0].read_text(encoding="utf-8")
    )

    assert len(history) == 2
    assert history[0]["issue_rate_percent"] == 25.0
    assert history[1]["issue_rate_percent"] == 10.0
    assert history[1]["change_percentage_points"] == -15.0
    assert history[1]["trend"] == "improved"




def test_monitor_cli_rejects_unknown_check(tmp_path, capsys):
    reports_dir = tmp_path / "reports"
    run_dir = reports_dir / "run_20260101_120000_000000Z"
    run_dir.mkdir(parents=True)

    report = {
        "metadata": {
            "input_file": "products.csv",
            "rules_sha256": "same_rules",
            "generated_at_utc": "2026-01-01T12:00:00+00:00",
        },
        "checks": [
            {
                "check_id": "missing:name",
                "status": "completed",
                "issue_rate_percent": 10.0,
            }
        ],
    }

    (run_dir / "report.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )

    output_dir = tmp_path / "monitoring_reports"

    exit_code = main([
        "monitor",
        "--reports", str(reports_dir),
        "--check", "missing:unknown",
        "--output", str(output_dir),
    ])

    captured = capsys.readouterr()

    assert exit_code == 2
    assert "Δεν βρέθηκε ο έλεγχος" in captured.err
    assert not output_dir.exists()


def test_compare_reports_rejects_different_dataset_ids():
    old_report = {
        "metadata": {
            "input_file": "data.csv",
            "dataset_id": "store_products",
            "rules_sha256": "same_rules",
        },
        "checks": [
            {
                "check_id": "missing:name",
                "status": "completed",
                "issue_rate_percent": 25.0,
            }
        ],
    }

    new_report = {
        "metadata": {
            "input_file": "data.csv",
            "dataset_id": "customers",
            "rules_sha256": "same_rules",
        },
        "checks": [
            {
                "check_id": "missing:name",
                "status": "completed",
                "issue_rate_percent": 10.0,
            }
        ],
    }

    with pytest.raises(
        ValueError,
        match="διαφορετικά σύνολα δεδομένων"
    ):
        compare_reports(old_report, new_report)




def test_compare_reports_accepts_same_dataset_different_filenames():
    old_report = {
        "metadata": {
            "input_file": "products_january.csv",
            "dataset_id": "store_products",
            "rules_sha256": "same_rules",
        },
        "checks": [
            {
                "check_id": "missing:product_name",
                "status": "completed",
                "issue_rate_percent": 25.0,
            }
        ],
    }

    new_report = {
        "metadata": {
            "input_file": "products_february.csv",
            "dataset_id": "store_products",
            "rules_sha256": "same_rules",
        },
        "checks": [
            {
                "check_id": "missing:product_name",
                "status": "completed",
                "issue_rate_percent": 10.0,
            }
        ],
    }

    results = compare_reports(old_report, new_report)

    assert len(results) == 1
    assert results[0]["check_id"] == "missing:product_name"
    assert results[0]["old_rate"] == 25.0
    assert results[0]["new_rate"] == 10.0
    assert results[0]["change_percentage_points"] == -15.0
    assert results[0]["trend"] == "improved"




def test_monitor_cli_filters_by_dataset_id(tmp_path):
    reports_dir = tmp_path / "reports"
    output_dir = tmp_path / "monitoring_reports"

    datasets = [
        ("store_products", "products_january.csv", 25.0),
        ("store_products", "products_february.csv", 10.0),
        ("customers", "customers.csv", 80.0),
    ]

    for index, (dataset_id, filename, rate) in enumerate(
        datasets, start=1
    ):
        run_dir = (
            reports_dir
            / f"run_2026010{index}_120000_000000Z"
        )
        run_dir.mkdir(parents=True)

        report = {
            "metadata": {
                "input_file": filename,
                "dataset_id": dataset_id,
                "rules_sha256": "same_rules",
                "generated_at_utc": (
                    f"2026-01-0{index}T12:00:00+00:00"
                ),
            },
            "checks": [
                {
                    "check_id": "missing:name",
                    "status": "completed",
                    "issue_rate_percent": rate,
                }
            ],
        }

        (run_dir / "report.json").write_text(
            json.dumps(report),
            encoding="utf-8",
        )

    exit_code = main([
        "monitor",
        "--reports", str(reports_dir),
        "--dataset-id", "store_products",
        "--check", "missing:name",
        "--output", str(output_dir),
    ])

    assert exit_code == 0

    json_files = list(output_dir.glob("*.json"))
    csv_files = list(output_dir.glob("*.csv"))

    assert len(json_files) == 1
    assert len(csv_files) == 1

    history = json.loads(
        json_files[0].read_text(encoding="utf-8")
    )

    assert len(history) == 2

    assert [
        item["issue_rate_percent"] for item in history
    ] == [25.0, 10.0]

    assert history[1]["change_percentage_points"] == -15.0
    assert history[1]["trend"] == "improved"




def test_monitor_cli_rejects_unknown_dataset_id(tmp_path, capsys):
    reports_dir = tmp_path / "reports"
    output_dir = tmp_path / "monitoring_reports"

    run_dir = reports_dir / "run_20260101_120000_000000Z"
    run_dir.mkdir(parents=True)

    report = {
        "metadata": {
            "input_file": "products.csv",
            "dataset_id": "store_products",
            "rules_sha256": "same_rules",
            "generated_at_utc": "2026-01-01T12:00:00+00:00",
        },
        "checks": [
            {
                "check_id": "missing:name",
                "status": "completed",
                "issue_rate_percent": 25.0,
            }
        ],
    }

    (run_dir / "report.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )

    exit_code = main([
        "monitor",
        "--reports", str(reports_dir),
        "--dataset-id", "customers",
        "--check", "missing:name",
        "--output", str(output_dir),
    ])

    captured = capsys.readouterr()

    assert exit_code == 2
    assert "Δεν βρέθηκαν αναφορές για το dataset_id: customers" in captured.err
    assert not output_dir.exists()




def test_monitor_cli_rejects_corrupted_json(tmp_path, capsys):
    reports_dir = tmp_path / "reports"
    output_dir = tmp_path / "monitoring_reports"

    run_dir = reports_dir / "run_20260101_120000_000000Z"
    run_dir.mkdir(parents=True)

    report_path = run_dir / "report.json"

    # Δημιουργούμε σκόπιμα ένα μη έγκυρο αρχείο JSON.
    report_path.write_text(
        '{"metadata":',
        encoding="utf-8",
    )

    exit_code = main([
        "monitor",
        "--reports", str(reports_dir),
        "--check", "missing:name",
        "--output", str(output_dir),
    ])

    captured = capsys.readouterr()

    assert exit_code == 2
    assert "Σφάλμα Monitoring" in captured.err
    assert not output_dir.exists()
    assert str(report_path) in captured.err



def test_history_sorts_by_report_timestamp(tmp_path):
    reports = [
        ("run_999_old", "2026-01-01T09:00:00+00:00", 25.0),
        ("run_001_new", "2026-01-02T09:00:00+00:00", 10.0),
    ]

    for folder_name, timestamp, rate in reports:
        run_dir = tmp_path / folder_name
        run_dir.mkdir()

        report = {
            "metadata": {
                "input_file": "products.csv",
                "dataset_id": "store_products",
                "rules_sha256": "same_rules",
                "generated_at_utc": timestamp,
            },
            "checks": [
                {
                    "check_id": "missing:name",
                    "status": "completed",
                    "issue_rate_percent": rate,
                }
            ],
        }

        (run_dir / "report.json").write_text(
            json.dumps(report),
            encoding="utf-8",
        )

    reference_path = tmp_path / "run_001_new" / "report.json"

    history = build_check_history(
        tmp_path,
        reference_path,
        "missing:name",
    )

    assert len(history) == 2

    assert [
        item["issue_rate_percent"] for item in history
    ] == [25.0, 10.0]

    assert history[0]["trend"] is None
    assert history[1]["trend"] == "improved"
    assert history[1]["change_percentage_points"] == -15.0



def test_monitor_cli_selects_latest_report_by_timestamp(
    tmp_path, capsys
):
    reports_dir = tmp_path / "reports"
    output_dir = tmp_path / "monitoring_reports"

    reports = [
        ("run_999_old", "2026-01-01T09:00:00+00:00", 25.0),
        ("run_001_new", "2026-01-02T09:00:00+00:00", 10.0),
    ]

    for folder_name, timestamp, rate in reports:
        run_dir = reports_dir / folder_name
        run_dir.mkdir(parents=True)

        report = {
            "metadata": {
                "input_file": "products.csv",
                "dataset_id": "store_products",
                "rules_sha256": "same_rules",
                "generated_at_utc": timestamp,
            },
            "checks": [
                {
                    "check_id": "missing:name",
                    "status": "completed",
                    "issue_rate_percent": rate,
                }
            ],
        }

        (run_dir / "report.json").write_text(
            json.dumps(report),
            encoding="utf-8",
        )

    exit_code = main([
        "monitor",
        "--reports", str(reports_dir),
        "--dataset-id", "store_products",
        "--check", "missing:name",
        "--output", str(output_dir),
    ])

    captured = capsys.readouterr()

    assert exit_code == 0

    #Το CLI πρέπει να επιλέξει τη νεότερη αναφορά.
    newest_report = (
        reports_dir / "run_001_new" / "report.json"
    )

    assert str(newest_report) in captured.out

    #Ελέγχουμε και το παραγόμενο ιστορικό.
    json_files = list(output_dir.glob("*.json"))
    csv_files = list(output_dir.glob("*.csv"))

    assert len(json_files) == 1
    assert len(csv_files) == 1

    history = json.loads(
        json_files[0].read_text(encoding="utf-8")
    )

    assert len(history) == 2

    assert [
        item["issue_rate_percent"] for item in history
    ] == [25.0, 10.0]

    assert history[1]["change_percentage_points"] == -15.0
    assert history[1]["trend"] == "improved"



def test_monitor_cli_rejects_invalid_timestamp(tmp_path, capsys):
    reports_dir = tmp_path / "reports"
    output_dir = tmp_path / "monitoring_reports"

    run_dir = reports_dir / "run_20260101_120000_000000Z"
    run_dir.mkdir(parents=True)

    report_path = run_dir / "report.json"

    report = {
        "metadata": {
            "input_file": "products.csv",
            "dataset_id": "store_products",
            "rules_sha256": "same_rules",
            "generated_at_utc": "2026-01-01T99:00:00+00:00",
        },
        "checks": [
            {
                "check_id": "missing:name",
                "status": "completed",
                "issue_rate_percent": 25.0,
            }
        ],
    }

    report_path.write_text(
        json.dumps(report),
        encoding="utf-8",
    )

    exit_code = main([
        "monitor",
        "--reports", str(reports_dir),
        "--dataset-id", "store_products",
        "--check", "missing:name",
        "--output", str(output_dir),
    ])

    captured = capsys.readouterr()

    assert exit_code == 2
    assert "Μη έγκυρη ημερομηνία" in captured.err
    assert str(report_path) in captured.err
    assert not output_dir.exists()




def test_load_report_rejects_invalid_structure(tmp_path):
    invalid_reports = [
        (
            {"checks": []},
            "Μη έγκυρα ή ελλιπή μεταδεδομένα"
        ),
        (
            {"metadata": [], "checks": []},
            "Μη έγκυρα ή ελλιπή μεταδεδομένα"
        ),
        (
            {"metadata": {}},
            "Μη έγκυρη λίστα ελέγχων"
        ),
        (
            {"metadata": {}, "checks": "invalid"},
            "Μη έγκυρη λίστα ελέγχων"
        ),
    ]

    report_path = tmp_path / "report.json"

    for report, expected_error in invalid_reports:
        report_path.write_text(
            json.dumps(report),
            encoding="utf-8",
        )

        with pytest.raises(
            ValueError,
            match=expected_error
        ) as error:
            load_report(report_path)

        assert str(report_path) in str(error.value)



def test_load_report_rejects_missing_metadata_fields(tmp_path):
    report_path = tmp_path / "report.json"

    valid_metadata = {
        "input_file": "products.csv",
        "rules_sha256": "same_rules",
        "generated_at_utc": "2026-01-01T12:00:00+00:00",
    }

    for field in valid_metadata:
        for invalid_value in (None, ""):
            metadata = valid_metadata.copy()
            metadata[field] = invalid_value

            report = {
                "metadata": metadata,
                "checks": [],
            }

            report_path.write_text(
                json.dumps(report),
                encoding="utf-8",
            )

            with pytest.raises(
                ValueError,
                match=f"metadata.{field}",
            ) as error:
                load_report(report_path)

            assert str(report_path) in str(error.value)



def test_monitor_cli_rejects_no_available_measurements(
    tmp_path, capsys
):
    reports_dir = tmp_path / "reports"
    output_dir = tmp_path / "monitoring_reports"

    run_dir = reports_dir / "run_20260101_120000_000000Z"
    run_dir.mkdir(parents=True)

    report = {
        "metadata": {
            "input_file": "products.csv",
            "dataset_id": "store_products",
            "rules_sha256": "same_rules",
            "generated_at_utc": "2026-01-01T12:00:00+00:00",
        },
        "checks": [
            {
                "check_id": "valid:price",
                "status": "skipped",
                "issue_rate_percent": None,
            }
        ],
    }

    (run_dir / "report.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )

    exit_code = main([
        "monitor",
        "--reports", str(reports_dir),
        "--dataset-id", "store_products",
        "--check", "valid:price",
        "--output", str(output_dir),
    ])

    captured = capsys.readouterr()

    assert exit_code == 2
    assert "Δεν υπάρχουν διαθέσιμες μετρήσεις" in captured.err
    assert not output_dir.exists()



def test_monitor_cli_accepts_zero_issue_rate(tmp_path):
    reports_dir = tmp_path / "reports"
    output_dir = tmp_path / "monitoring_reports"

    run_dir = reports_dir / "run_20260101_120000_000000Z"
    run_dir.mkdir(parents=True)

    report = {
        "metadata": {
            "input_file": "products.csv",
            "dataset_id": "store_products",
            "rules_sha256": "same_rules",
            "generated_at_utc": "2026-01-01T12:00:00+00:00",
        },
        "checks": [
            {
                "check_id": "missing:name",
                "status": "completed",
                "issue_rate_percent": 0.0,
            }
        ],
    }

    (run_dir / "report.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )

    exit_code = main([
        "monitor",
        "--reports", str(reports_dir),
        "--dataset-id", "store_products",
        "--check", "missing:name",
        "--output", str(output_dir),
    ])

    assert exit_code == 0

    json_files = list(output_dir.glob("*.json"))
    csv_files = list(output_dir.glob("*.csv"))

    assert len(json_files) == 1
    assert len(csv_files) == 1

    history = json.loads(
        json_files[0].read_text(encoding="utf-8")
    )

    assert len(history) == 1
    assert history[0]["issue_rate_percent"] == 0.0
    assert history[0]["status"] == "completed"
    assert history[0]["trend"] is None
