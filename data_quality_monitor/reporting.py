# Παραγωγή αναφορών ποιότητας δεδομένων σε μορφές κατάλληλες για επεξεργασία από προγράμματα και για ανάγνωση από χρήστες.
from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import CheckResult


CHECK_FIELDS = [
    "check_id", "category", "status", "checked_count", "issue_count",
    "issue_rate_percent", "not_evaluated_count", "reason", "details",
]
FINDING_FIELDS = ["check_id", "category", "row_number", "column", "message"]


def create_report(
    results: list[CheckResult],
    *,
    source_name: str,
    row_count: int,
    column_count: int,
    output_base: str | Path,
    rules_name: str,
    metadata_extra: dict[str, Any] | None = None,
) -> tuple[Path, dict[str, Any]]:
    timestamp = datetime.now(timezone.utc)
    folder = Path(output_base) / ("run_" + timestamp.strftime("%Y%m%d_%H%M%S_%fZ"))
    folder.mkdir(parents=True, exist_ok=False)

    status_counts = {s: sum(r.status == s for r in results) for s in ("completed", "skipped", "error")}
    report: dict[str, Any] = {
        "metadata": {
            "input_file": source_name,
            "rules_file": rules_name,
            "generated_at_utc": timestamp.isoformat(),
            "row_count": row_count,
            "column_count": column_count,
            "data_row_numbering": "1-based; does not include header; not physical file line numbers",
            **(metadata_extra or {}),
        },
        "check_status_counts": status_counts,
        "notes": [
            "Τα ποσοστά αφορούν τις εξετασμένες περιπτώσεις κάθε ελέγχου.",
            "Οι κατηγορίες σφαλμάτων μπορεί να επικαλύπτονται: δεν αθροίζονται ως μοναδικές προβληματικές εγγραφές.",
            "Το null σημαίνει μη διαθέσιμο αποτέλεσμα, όχι μηδέν προβλήματα.",
        ],
        "checks": [r.to_dict() for r in results],
    }
    (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    with (folder / "checks.csv").open("w", encoding="utf-8-sig", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=CHECK_FIELDS)
        writer.writeheader()
        for r in results:
            writer.writerow({
                "check_id": r.check_id, "category": r.category,
                "status": r.status, "checked_count": r.checked_count,
                "issue_count": r.issue_count if r.issue_count is not None else "",
                "issue_rate_percent": r.issue_rate_percent if r.issue_rate_percent is not None else "",
                "not_evaluated_count": r.not_evaluated_count,
                "reason": r.reason or "",
                "details": json.dumps(r.details, ensure_ascii=False),
            })

    with (folder / "findings.csv").open("w", encoding="utf-8-sig", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=FINDING_FIELDS)
        writer.writeheader()
        for result in results:
            for finding in result.findings:
                writer.writerow(asdict(finding))

    lines = [
        "ΑΝΑΦΟΡΑ ΑΞΙΟΛΟΓΗΣΗΣ ΠΟΙΟΤΗΤΑΣ ΔΕΔΟΜΕΝΩΝ",
        f"Αρχείο: {source_name}",
        f"Εγγραφές: {row_count} | Στήλες: {column_count}",
        f"Έλεγχοι: {len(results)} | Ολοκληρώθηκαν: {status_counts['completed']}"
        f" | Παραλείφθηκαν: {status_counts['skipped']} | Σφάλματα: {status_counts['error']}",
        "",
    ]
    for r in results:
        if r.status == "completed":
            pct = f"{r.issue_rate_percent:.2f}%" if r.issue_rate_percent is not None else "Μ/Δ"
            lines.append(f"{r.check_id}: {r.issue_count}/{r.checked_count} προβλήματα ({pct})")
        else:
            lines.append(f"{r.check_id}: {r.status.upper()} — {r.reason}")
    lines.extend([
        "",
        "Σημείωση: τα ευρήματα διαφορετικών ελέγχων ενδέχεται να αφορούν την ίδια εγγραφή.",
        "Για λεπτομέρειες δείτε τα report.json, checks.csv και findings.csv.",
    ])
    (folder / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return folder, report
