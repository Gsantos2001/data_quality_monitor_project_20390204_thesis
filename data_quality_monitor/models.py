#Κοινές δομές αποτελεσμάτων που χρησιμοποιούνται από τους ανεξάρτητους ελέγχους ποιότητας.
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Finding:
    check_id: str
    category: str
    row_number: int  #Αρίθμηση γραμμών δεδομένων από το 1, η οποία δεν αντιστοιχεί απαραίτητα στη φυσική γραμμή του αρχείου CSV.
    column: str
    message: str


@dataclass
class CheckResult:
    check_id: str
    category: str
    status: str  #Πιθανές καταστάσεις εκτέλεσης: completed (ολοκληρώθηκε), skipped (παραλείφθηκε), error (σφάλμα).
    checked_count: int = 0
    issue_count: int | None = None
    issue_rate_percent: float | None = None
    not_evaluated_count: int = 0
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        #Τα ευρήματα αποθηκεύονται τόσο σε ξεχωριστό αρχείο CSV όσο και στην αναφορά JSON.
        return asdict(self)


def completed(
    check_id: str,
    category: str,
    checked_count: int,
    findings: list[Finding],
    *,
    not_evaluated_count: int = 0,
    details: dict[str, Any] | None = None,
) -> CheckResult:
    issue_count = len(findings)
    rate = round(100 * issue_count / checked_count, 2) if checked_count else None
    return CheckResult(
        check_id=check_id,
        category=category,
        status="completed",
        checked_count=checked_count,
        issue_count=issue_count,
        issue_rate_percent=rate,
        not_evaluated_count=not_evaluated_count,
        details=details or {},
        findings=findings,
    )


def skipped(check_id: str, category: str, reason: str) -> CheckResult:
    return CheckResult(check_id=check_id, category=category, status="skipped", reason=reason)


def failed(check_id: str, category: str, reason: str) -> CheckResult:
    return CheckResult(check_id=check_id, category=category, status="error", reason=reason)
