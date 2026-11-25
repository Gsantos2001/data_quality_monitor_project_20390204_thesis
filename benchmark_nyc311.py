"""Εκτέλεση μετρήσεων χρόνου και χρήσης μνήμης
για την αξιολόγηση της εφαρμογής σε δεδομένα NYC 311.
"""

import csv
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import psutil


# Φάκελος του project και διαδρομές αρχείων.
PROJECT_DIR = Path(__file__).resolve().parent
DATASET_DIR = (
    PROJECT_DIR.parent
    / "NYC_311_expiriments"
    / "nyc311_datasets"
)
RULES_FILE = PROJECT_DIR / "examples" / "nyc311_rules_initial.json"

RESULTS_DIR = PROJECT_DIR / "benchmark_results"
RESULTS_DIR.mkdir(exist_ok=True)

# Αρχική δοκιμή μόνο με μικρότερα datasets.
DATASET_SIZES = [1_000, 10_000, 100_000, 1_000_000]
REPETITIONS = 3
MEMORY_INTERVAL = 0.01

RESULTS_FILE = RESULTS_DIR / "benchmark_measurements_final.csv"


def get_memory_mb(process):
    # Υπολογισμός της μνήμης της διεργασίας και των παιδιών της.
    total_bytes = 0

    try:
        processes = [process] + process.children(recursive=True)

        for current in processes:
            try:
                total_bytes += current.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    return total_bytes / (1024 ** 2)


def run_benchmark(size, repetition):
    dataset_file = DATASET_DIR / f"nyc311_{size}.csv"

    if not dataset_file.is_file():
        raise FileNotFoundError(f"Δεν βρέθηκε: {dataset_file}")

    if not RULES_FILE.is_file():
        raise FileNotFoundError(f"Δεν βρέθηκε: {RULES_FILE}")

    run_name = f"nyc311_{size}_final_run_{repetition}"
    output_dir = RESULTS_DIR / "reports" / run_name
    log_file = RESULTS_DIR / f"{run_name}.log"

    command = [
    sys.executable,
    "-m",
    "data_quality_monitor",
    "--input",
    str(dataset_file),
    "--rules",
    str(RULES_FILE),
    "--output",
    str(output_dir),
    "--dataset-id",
    "nyc311",
    "--max-findings",
    "100",
    ]

    print(f"\nΈναρξη: {size:,} εγγραφές, εκτέλεση {repetition}")

    started_at = datetime.now().isoformat(timespec="seconds")

    with log_file.open("w", encoding="utf-8") as log:
        start_time = time.perf_counter()

        process = subprocess.Popen(
            command,
            cwd=PROJECT_DIR,
            stdout=log,
            stderr=subprocess.STDOUT,
        )

        monitored_process = psutil.Process(process.pid)
        peak_memory_mb = 0.0

        while process.poll() is None:
            memory_mb = get_memory_mb(monitored_process)
            peak_memory_mb = max(peak_memory_mb, memory_mb)
            time.sleep(MEMORY_INTERVAL)

        # Τελική δειγματοληψία, εφόσον η διεργασία υπάρχει ακόμη.
        peak_memory_mb = max(
            peak_memory_mb,
            get_memory_mb(monitored_process),
        )

        return_code = process.wait()
        elapsed_seconds = time.perf_counter() - start_time

    status = "success" if return_code == 0 else "failed"

    print(f"Κατάσταση: {status}")
    print(f"Χρόνος: {elapsed_seconds:.3f} δευτερόλεπτα")
    print(f"Μέγιστη παρατηρηθείσα RAM: {peak_memory_mb:.2f} MB")
    print(f"Αρχείο καταγραφής: {log_file.name}")

    return {
        "dataset_rows": size,
        "repetition": repetition,
        "started_at": started_at,
        "elapsed_seconds": round(elapsed_seconds, 6),
        "peak_rss_mb": round(peak_memory_mb, 3),
        "status": status,
        "return_code": return_code,
        "log_file": str(log_file),
    }


def main():
    results = []

    for size in DATASET_SIZES:
        for repetition in range(1, REPETITIONS + 1):
            result = run_benchmark(size, repetition)
            results.append(result)

            # Διακοπή εάν κάποια εκτέλεση αποτύχει.
            if result["status"] != "success":
                print("Η διαδικασία διακόπηκε λόγω αποτυχίας.")
                break

        if results[-1]["status"] != "success":
            break

    with RESULTS_FILE.open(
        "w", encoding="utf-8-sig", newline=""
    ) as file:
        writer = csv.DictWriter(file, fieldnames=[
            "dataset_rows",
            "repetition",
            "started_at",
            "elapsed_seconds",
            "peak_rss_mb",
            "status",
            "return_code",
            "log_file",
        ])

        writer.writeheader()
        writer.writerows(results)

    print(f"\nΟι μετρήσεις αποθηκεύτηκαν στο: {RESULTS_FILE}")


if __name__ == "__main__":
    main()
