"""Τελικό συγκριτικό end-to-end benchmark DQM / Pandera-hybrid.

Εκτέλεση από τη ρίζα του project: python benchmark_dqm_vs_pandera.py
Απαιτεί psutil, compare_pandera_nyc311.py και pandera_benchmark_worker.py.
Δεν τροποποιεί τον κώδικα DQM ούτε προηγούμενες αναφορές.

Σημείωση μεθοδολογίας: οι ροές παράγουν διαφορετικά artifacts.
Το benchmark συγκρίνει τις συγκεκριμένες πλήρεις ροές, όχι την εγγενή
ταχύτητα του Pandera validator έναντι του DQM.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

import psutil

ROOT = Path(__file__).resolve().parent
DATASET_DIR = ROOT.parent / "NYC_311_expiriments" / "nyc311_datasets"
RULES = ROOT / "examples" / "nyc311_rules_initial.json"
PANDERA_WORKER = ROOT / "pandera_benchmark_worker.py"
PANDERA_SOURCE = ROOT / "compare_pandera_nyc311.py"
SIZES = [1_000, 10_000, 100_000, 1_000_000]
REPETITIONS = 3
DQM_MAX_FINDINGS = 100
SAMPLING_INTERVAL_SECONDS = 0.01
RESULTS_ROOT = ROOT / "pandera_comparison" / "final_benchmark"
FIELDS = ["tool", "rows", "repetition", "elapsed_seconds", "peak_observed_rss_mib", "max_single_process_rss_mib", "max_process_count", "exit_code", "log_folder"]
CHECK_FIELDS = ("status", "checked_count", "issue_count", "not_evaluated_count")


def execute(tool: str, rows: int, repetition: int, command: list[str], run_dir: Path) -> dict:
    run_dir.mkdir(parents=True, exist_ok=False)
    peak_total = 0.0
    peak_single = 0.0
    max_count = 0
    started = time.perf_counter()
    with (run_dir / "stdout.txt").open("w", encoding="utf-8") as stdout, \
         (run_dir / "stderr.txt").open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr)
        parent = psutil.Process(process.pid)
        while process.poll() is None:
            try:
                members = [parent, *parent.children(recursive=True)]
                rss_total = 0
                member_count = 0
                for member in members:
                    try:
                        rss = member.memory_info().rss
                        rss_total += rss
                        peak_single = max(peak_single, rss / (1024 ** 2))
                        member_count += 1
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        continue
                peak_total = max(peak_total, rss_total / (1024 ** 2))
                max_count = max(max_count, member_count)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
            time.sleep(SAMPLING_INTERVAL_SECONDS)
        exit_code = process.wait()
    elapsed = time.perf_counter() - started
    entry = {
        "tool": tool, "rows": rows, "repetition": repetition,
        "elapsed_seconds": round(elapsed, 6),
        "peak_observed_rss_mib": round(peak_total, 3),
        "max_single_process_rss_mib": round(peak_single, 3),
        "max_process_count": max_count,
        "exit_code": exit_code,
        "log_folder": str(run_dir.relative_to(ROOT)),
    }
    print(f"  {tool}: {'success' if exit_code == 0 else 'FAILED'} | {elapsed:.3f} s | {peak_total:.2f} MiB", flush=True)
    if peak_total < 25:
        print("    ΠΡΟΕΙΔΟΠΟΙΗΣΗ: ύποπτα χαμηλή RSS — ελέγξτε την παρακολούθηση διεργασιών.", flush=True)
    if exit_code:
        raise RuntimeError(f"{tool} απέτυχε. Δες: {run_dir / 'stderr.txt'}")
    return entry


def read_checks(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        data = list(csv.DictReader(stream))
    mapping = {row["check_id"]: row for row in data}
    if len(mapping) != len(data):
        raise RuntimeError(f"Διπλά check IDs στο {path}")
    return mapping


def verify_pair(dqm_dir: Path, pandera_file: Path, expected_rows: int) -> tuple[int, str]:
    paths = list((dqm_dir / "reports").rglob("checks.csv"))
    if len(paths) != 1:
        raise RuntimeError(f"Αναμέναμε 1 DQM checks.csv, βρέθηκαν {len(paths)} στο {dqm_dir}")
    a, b = read_checks(paths[0]), read_checks(pandera_file)
    differences = []
    if len(a) != 53 or len(b) != 53:
        differences.append(f"Πλήθος ελέγχων: DQM={len(a)}, Pandera={len(b)}")
    for check_id in sorted(set(a) | set(b)):
        if check_id not in a or check_id not in b:
            differences.append(f"Απουσιάζει κανόνας {check_id}")
            continue
        for field in CHECK_FIELDS:
            if str(a[check_id][field]) != str(b[check_id][field]):
                differences.append(f"{check_id}: {field}, DQM={a[check_id][field]}, Pandera={b[check_id][field]}")
    return len(differences), "\n".join(differences)


def append_measurement(csv_path: Path, row: dict) -> None:
    exists = csv_path.exists()
    with csv_path.open("a", encoding="utf-8-sig" if not exists else "utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def main() -> None:
    for needed in [RULES, PANDERA_WORKER, PANDERA_SOURCE]:
        if not needed.is_file():
            raise FileNotFoundError(f"Λείπει: {needed}")
    for size in SIZES:
        filename = DATASET_DIR / f"nyc311_{size}.csv"
        if not filename.is_file():
            raise FileNotFoundError(f"Λείπει το dataset: {filename}")

    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%fZ")
    root = RESULTS_ROOT / stamp
    root.mkdir(parents=True, exist_ok=False)
    measurement_file = root / "measurements.csv"
    pair_file = root / "equivalence.csv"
    with pair_file.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["rows", "repetition", "differences", "status"])

    methodology = {
        "timestamp_utc": stamp,
        "python_executable": sys.executable,
        "sizes": SIZES,
        "repetitions": REPETITIONS,
        "dqm_max_findings_per_check": DQM_MAX_FINDINGS,
        "rss_sampling_interval_seconds": SAMPLING_INTERVAL_SECONDS,
        "rss_method": "Sample sum RSS of launched process + recursively discovered children, peak sampled sum",
        "pandera_implementation": "Hybrid pandas precomputed masks + 53 Pandera DataFrameSchema/Check validations via calculate()",
        "pandera_baseline_check_during_timing": False,
        "note": "End-to-end comparison of two different pipelines and report outputs; not a comparison of isolated validator overhead. No prior DQM CSV read during timed Pandera run.",
        "files": {"worker": str(PANDERA_WORKER), "pandera_logic": str(PANDERA_SOURCE), "rules": str(RULES)},
    }
    (root / "methodology.json").write_text(json.dumps(methodology, ensure_ascii=False, indent=2), encoding="utf-8")

    for size in SIZES:
        dataset = DATASET_DIR / f"nyc311_{size}.csv"
        for repetition in range(1, REPETITIONS + 1):
            print(f"\nΕγγραφές: {size:,} | επανάληψη {repetition}/{REPETITIONS}", flush=True)
            pair_root = root / f"nyc311_{size}" / f"repeat_{repetition}"
            dqm_dir = pair_root / "dqm"
            pandera_dir = pair_root / "pandera_hybrid"
            dqm_cmd = [sys.executable, "-m", "data_quality_monitor", "--input", str(dataset),
                       "--rules", str(RULES), "--output", str(dqm_dir / "reports"),
                       "--dataset-id", "nyc311", "--max-findings", str(DQM_MAX_FINDINGS)]
            pandera_csv = pandera_dir / "checks.csv"
            pandera_cmd = [sys.executable, str(PANDERA_WORKER), "--input", str(dataset),
                           "--rules", str(RULES), "--output", str(pandera_csv)]
            jobs = [("DQM", dqm_cmd, dqm_dir), ("Pandera_hybrid", pandera_cmd, pandera_dir)]
            if repetition % 2 == 0:
                jobs.reverse()
            for tool, cmd, run_dir in jobs:
                result = execute(tool, size, repetition, cmd, run_dir)
                append_measurement(measurement_file, result)
            mismatch_count, details = verify_pair(dqm_dir, pandera_csv, size)
            with pair_file.open("a", encoding="utf-8", newline="") as f:
                csv.writer(f).writerow([size, repetition, mismatch_count, "match" if mismatch_count == 0 else "mismatch"])
            print(f"  Ισοδυναμία 53 ελέγχων: {('OK' if mismatch_count == 0 else f'{mismatch_count} διαφορές')}", flush=True)
            if mismatch_count:
                (pair_root / "differences.txt").write_text(details, encoding="utf-8")
                raise RuntimeError(f"Ασυμφωνία αποτελεσμάτων: {pair_root / 'differences.txt'}")

    print(f"\nΌλα ολοκληρώθηκαν. Μετρήσεις: {measurement_file}")
    print(f"Επαλήθευση ισοδυναμίας: {pair_file}")


if __name__ == "__main__":
    main()
