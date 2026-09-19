import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from hub.accounting.xlsx import (
    BAND_GAP_ROWS,
    CLOSER_LABELS,
    JOB_HEADERS,
    PAYMENT_LABELS,
    REVIEW_LABELS,
    TECHNICIAN_BLOCK_COLUMNS,
    TECHNICIAN_COLUMN_STRIDE,
    TECHNICIANS_PER_BAND,
    WEEKDAYS,
    WeeklyAccountingXlsxModel,
    block_layout,
    spreadsheet_text,
)
from hub.accounting.xlsx_styles import (
    BLOCK_COLUMN_WIDTHS,
    COLUMN_HEADER_ROW_HEIGHT,
    DATA_ROW_HEIGHT,
    DAY_HEADER_ROW_HEIGHT,
    TITLE_ROW_HEIGHT,
    wrapped_row_height,
)

LAYOUT_VERSION = "stage9-weekly-v1"


@dataclass(frozen=True)
class FormatRange:
    start_row: int
    end_row: int
    start_column: int
    end_column: int
    role: str


@dataclass(frozen=True)
class Dimension:
    index: int
    pixels: int


@dataclass(frozen=True)
class SheetsPayload:
    title: str
    values: tuple[tuple[object, ...], ...]
    formats: tuple[FormatRange, ...]
    row_heights: tuple[Dimension, ...]
    column_widths: tuple[Dimension, ...]
    row_count: int
    column_count: int
    fingerprint: str
    technician_count: int


def week_title(start: date) -> str:
    return f"{start.isoformat()} - {date.fromordinal(start.toordinal() + 6).isoformat()}"


def money(value: Decimal) -> str:
    # Sheets JSON numbers are IEEE-754. Currency is intentionally exact RAW text.
    return f"${value:,.2f}"


class Grid:
    def __init__(self):
        self.cells: dict[tuple[int, int], object] = {}
        self.formats: list[FormatRange] = []
        self.rows: dict[int, int] = {}
        self.columns: dict[int, int] = {}

    def write(self, row: int, column: int, value: object) -> None:
        self.cells[row, column] = spreadsheet_text(value) if isinstance(value, str) else value

    def style(self, row: int, end_row: int, column: int, end_column: int, role: str) -> None:
        self.formats.append(FormatRange(row, end_row, column, end_column, role))

    def row_height(self, row: int, points: int) -> None:
        self.rows[row] = max(self.rows.get(row, 0), round(points * 4 / 3))

    def widths(self, start_column: int) -> None:
        for offset, width in enumerate(BLOCK_COLUMN_WIDTHS):
            self.columns[start_column + offset] = round(width * 7)

    def payload(self, title: str, technician_count: int) -> SheetsPayload:
        rows = max(
            max((row for row, _ in self.cells), default=0) + 1,
            max(self.rows, default=-1) + 1,
        )
        columns = max(
            max((column for _, column in self.cells), default=0) + 1,
            max(self.columns, default=-1) + 1,
        )
        values = tuple(
            tuple(self.cells.get((row, column), "") for column in range(columns))
            for row in range(rows)
        )
        formats = tuple(self.formats)
        row_heights = tuple(Dimension(*item) for item in sorted(self.rows.items()))
        column_widths = tuple(Dimension(*item) for item in sorted(self.columns.items()))
        canonical = json.dumps(
            {
                "layout": LAYOUT_VERSION,
                "title": title,
                "values": values,
                "formats": [item.__dict__ for item in formats],
                "rows": [item.__dict__ for item in row_heights],
                "columns": [item.__dict__ for item in column_widths],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return SheetsPayload(
            title=title,
            values=values,
            formats=formats,
            row_heights=row_heights,
            column_widths=column_widths,
            row_count=rows,
            column_count=columns,
            fingerprint=hashlib.sha256(canonical.encode()).hexdigest(),
            technician_count=technician_count,
        )


def title(grid: Grid, model: WeeklyAccountingXlsxModel, row: int, column: int) -> None:
    grid.write(row, column, model.technician_name)
    grid.write(row, column + 8, f"Timezone: {model.accounting_timezone or 'Not configured'}")
    grid.write(row, column + 10, "WEEK")
    grid.write(row, column + 11, f"{model.week_start:%m/%d/%Y} - {model.week_end:%m/%d/%Y}")
    grid.style(row, row + 1, column, column + 1, "TECHNICIAN_TITLE")
    grid.style(row, row + 1, column + 8, column + 9, "WEEK_METADATA")
    grid.style(row, row + 1, column + 10, column + 11, "WEEK_LABEL")
    grid.style(row, row + 1, column + 11, column + 12, "WEEK_METADATA")
    grid.row_height(row, TITLE_ROW_HEIGHT)


def block(grid: Grid, model: WeeklyAccountingXlsxModel, origin_row: int, origin_col: int) -> int:
    layout = block_layout(model)
    grid.widths(origin_col)
    for day_index, relative in enumerate(layout.day_rows):
        day = model.days[day_index]
        row = origin_row + relative
        grid.write(row, origin_col, f"{WEEKDAYS[day_index]}  {day.business_date:%m/%d/%Y}")
        for offset, header in enumerate(JOB_HEADERS):
            grid.write(row + 1, origin_col + offset, header)
        grid.style(row, row + 1, origin_col, origin_col + 9, "DAY_HEADER")
        grid.style(row + 1, row + 2, origin_col, origin_col + 9, "COLUMN_HEADER")
        grid.row_height(row, DAY_HEADER_ROW_HEIGHT)
        grid.row_height(row + 1, COLUMN_HEADER_ROW_HEIGHT)
        count = max(15, len(day.reports))
        grid.style(row + 2, row + 2 + count, origin_col, origin_col + 9, "JOB_CELL")
        for wrapped in (1, 4, 8):
            grid.style(
                row + 2,
                row + 2 + count,
                origin_col + wrapped,
                origin_col + wrapped + 1,
                "WRAPPED_CELL",
            )
        grid.style(row + 2, row + 2 + count, origin_col + 2, origin_col + 3, "JOB_AMOUNT")
        for index, report in enumerate(day.reports):
            current = row + 2 + index
            values = (
                report.sequence,
                f"{report.title}\n{report.location}",
                money(report.amount),
                PAYMENT_LABELS[report.payment_method],
                CLOSER_LABELS[report.closed_by].removeprefix("Closed by "),
                report.groupon_reviews,
                report.google_reviews,
                report.facebook_reviews,
                "Yes" if report.maintenance else "No",
            )
            for offset, value in enumerate(values):
                grid.write(current, origin_col + offset, value)
            grid.row_height(
                current,
                wrapped_row_height(report.title, report.location, characters_per_line=44),
            )
    for offset, label in enumerate(("NOTE", "EXPENSES", "AMOUNT"), start=9):
        grid.write(origin_row, origin_col + offset, label)
    grid.style(origin_row, origin_row + 1, origin_col + 9, origin_col + 12, "EXPENSE_HEADER")
    if model.expenses:
        grid.style(
            origin_row + 1,
            origin_row + 1 + len(model.expenses),
            origin_col + 9,
            origin_col + 11,
            "EXPENSE_CELL",
        )
        grid.style(
            origin_row + 1,
            origin_row + 1 + len(model.expenses),
            origin_col + 11,
            origin_col + 12,
            "EXPENSE_AMOUNT",
        )
    for index, expense in enumerate(model.expenses, start=1):
        grid.write(origin_row + index, origin_col + 9, expense.note)
        grid.write(origin_row + index, origin_col + 10, expense.expense_type)
        grid.write(origin_row + index, origin_col + 11, money(expense.amount))
        grid.row_height(
            origin_row + index,
            wrapped_row_height(expense.note, expense.expense_type, characters_per_line=32),
        )
    summary(grid, model, origin_row + layout.summary_row, origin_col)
    for current in range(origin_row, origin_row + layout.row_count):
        grid.row_height(current, DATA_ROW_HEIGHT)
    return layout.row_count


def summary(grid: Grid, model: WeeklyAccountingXlsxModel, row: int, column: int) -> None:
    label_column, value_column = column + 10, column + 11

    def pair(
        offset: int,
        label: str,
        value: object,
        *,
        header: bool = False,
        amount: bool = False,
    ) -> None:
        grid.write(row + offset, label_column, label)
        grid.write(row + offset, value_column, value)
        grid.style(
            row + offset,
            row + offset + 1,
            label_column,
            value_column,
            "SUMMARY_HEADER" if header else "SUMMARY_CELL",
        )
        grid.style(
            row + offset,
            row + offset + 1,
            value_column,
            value_column + 1,
            "TOTAL_VALUE"
            if header and amount
            else "SUMMARY_HEADER"
            if header
            else "SUMMARY_AMOUNT"
            if amount
            else "SUMMARY_CELL",
        )

    pair(0, "TOTAL EXPENSES", "", header=True)
    pair(1, "Expenses", money(model.totals.expense_total), amount=True)
    pair(2, "REVIEWS", "", header=True)
    for index, (code, count) in enumerate(model.totals.reviews, 3):
        pair(index, REVIEW_LABELS[code], count)
    pair(6, "AMOUNTS", "", header=True)
    for index, (code, amount) in enumerate(model.totals.payments, 7):
        pair(index, PAYMENT_LABELS[code], money(amount), amount=True)
    pair(15, "ACTIVITY", "", header=True)
    pair(16, "Reports", model.totals.report_count)
    pair(17, "Expense entries", model.totals.expense_count)
    pair(18, "Maintenance plans", model.totals.maintenance_count)
    for index, (code, count) in enumerate(model.totals.closed_by, 19):
        pair(index, CLOSER_LABELS[code], count)
    pair(21, "TOTAL", money(model.totals.gross_total), header=True, amount=True)
    pair(22, "DATE", f"{model.week_start:%m/%d/%Y} - {model.week_end:%m/%d/%Y}")


def individual_payload(model: WeeklyAccountingXlsxModel) -> SheetsPayload:
    grid = Grid()
    title(grid, model, 0, 0)
    block(grid, model, 1, 0)
    return grid.payload(week_title(model.week_start), 1)


def all_tech_payload(models: tuple[WeeklyAccountingXlsxModel, ...], start: date) -> SheetsPayload:
    grid = Grid()
    if not models:
        grid.write(0, 0, "No technicians included for this week")
        return grid.payload(week_title(start), 0)
    next_row = 0
    for band_start in range(0, len(models), TECHNICIANS_PER_BAND):
        band = models[band_start : band_start + TECHNICIANS_PER_BAND]
        band_height = max(block_layout(model).row_count for model in band)
        for position, model in enumerate(band):
            column = position * TECHNICIAN_COLUMN_STRIDE
            title(grid, model, next_row, column)
            block(grid, model, next_row + 1, column)
            grid.columns[column + TECHNICIAN_BLOCK_COLUMNS] = 21
        next_row += 1 + band_height + BAND_GAP_ROWS
    return grid.payload(week_title(start), len(models))
