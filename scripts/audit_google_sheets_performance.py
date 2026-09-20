"""Deterministic local Stage 9 payload benchmark; no provider or database access."""

import json
import math
import sys
import time
import tracemalloc
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))

from hub.accounting.xlsx import (  # noqa: E402
    PAYMENT_LABELS,
    WeeklyAccountingXlsxModel,
    XlsxDay,
    XlsxExpense,
    XlsxReport,
    XlsxTotals,
)
from hub.accounting_mirrors.presentation import (  # noqa: E402
    all_tech_payload,
    individual_payload,
)
from hub.accounting_mirrors.provider import (  # noqa: E402
    FORMAT_REQUEST_CHUNK,
    formatting_requests,
    value_chunks,
)

START = date(2026, 9, 14)


def model(report_count=1, expense_count=1, *, name="Audit Technician"):
    report = XlsxReport(
        sequence=1,
        title="Synthetic repair " + "T" * 180,
        location="Synthetic address " + "L" * 300,
        amount=Decimal("193.01"),
        payment_method="CASH",
        closed_by="MYSELF",
        google_reviews=1,
        groupon_reviews=1,
        facebook_reviews=1,
        maintenance=True,
    )
    expense = XlsxExpense(
        business_date=START,
        expense_type="Synthetic supplies",
        amount=Decimal("0.01"),
        note="Synthetic expense " + "N" * 300,
    )
    days = tuple(
        XlsxDay(
            START + timedelta(days=offset),
            tuple(replace(report, sequence=index + 1) for index in range(report_count))
            if offset == 0
            else (),
        )
        for offset in range(7)
    )
    totals = XlsxTotals(
        gross_total=Decimal("193.01") * report_count,
        expense_total=Decimal("0.01") * expense_count,
        report_count=report_count,
        expense_count=expense_count,
        maintenance_count=report_count,
        payments=tuple(
            (code, Decimal("193.01") * report_count if code == "CASH" else Decimal("0.00"))
            for code in PAYMENT_LABELS
        ),
        reviews=(("GOOGLE", report_count), ("GROUPON", report_count), ("FACEBOOK", report_count)),
        closed_by=(("MYSELF", report_count), ("CALL_CENTER", 0)),
    )
    return WeeklyAccountingXlsxModel(
        technician_id=uuid4(),
        technician_name=name,
        accounting_timezone="America/Los_Angeles",
        week_start=START,
        week_end=START + timedelta(days=6),
        days=days,
        expenses=tuple(
            replace(expense, note=f"{expense.note} {index}") for index in range(expense_count)
        ),
        totals=totals,
    )


def measure(label, build):
    tracemalloc.start()
    started = time.perf_counter()
    payload = build()
    elapsed = (time.perf_counter() - started) * 1000
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    value_bodies = list(value_chunks(payload.values))
    format_ops = len(formatting_requests(1, payload, payload.row_count, payload.column_count))
    return {
        "label": label,
        "technicians": payload.technician_count,
        "rows": payload.row_count,
        "columns": payload.column_count,
        "payload_bytes": len(json.dumps(payload.values).encode()),
        "format_operations": format_ops,
        "value_requests": len(value_bodies),
        "format_requests": math.ceil(format_ops / FORMAT_REQUEST_CHUNK),
        "provider_requests_without_add": 2
        + len(value_bodies)
        + math.ceil(format_ops / FORMAT_REQUEST_CHUNK),
        "build_ms": round(elapsed, 2),
        "peak_bytes": peak,
    }


def main():
    typical = model()
    large = model(500, 500, name="Large Audit Technician")
    results = [
        measure("individual_typical", lambda: individual_payload(typical)),
        measure("individual_500_reports_500_expenses", lambda: individual_payload(large)),
    ]
    for count in (10, 50, 100):
        models = tuple(
            replace(typical, technician_id=uuid4(), technician_name=f"Technician {index:03}")
            for index in range(count)
        )
        results.append(
            measure(f"all_tech_{count}", lambda models=models: all_tech_payload(models, START))
        )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
