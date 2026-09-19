from dataclasses import dataclass

LEGACY_BLUE = "7D98D3"
LEGACY_YELLOW = "FFFF00"
BLACK = "000000"
WHITE = "FFFFFF"
CURRENCY_FORMAT = "$#,##0.00"

BLOCK_COLUMN_WIDTHS = (6, 31, 13, 20, 20, 12, 12, 13, 26, 25, 25, 24)
TITLE_ROW_HEIGHT = 30
DAY_HEADER_ROW_HEIGHT = 19.5
COLUMN_HEADER_ROW_HEIGHT = 33.75
DATA_ROW_HEIGHT = 18


@dataclass(frozen=True)
class CellStyle:
    font_name: str = "Arial"
    font_size: int = 9
    bold: bool = False
    font_color: str = BLACK
    fill_color: str | None = None
    horizontal: str | None = None
    vertical: str = "center"
    wrap_text: bool = False
    number_format: str | None = None
    bordered: bool = False


TECHNICIAN_TITLE = CellStyle(font_size=20, bold=True)
WEEK_METADATA = CellStyle(font_size=10, horizontal="center", wrap_text=True)
WEEK_LABEL = CellStyle(font_size=10, bold=True, horizontal="center")
DAY_HEADER = CellStyle(
    font_size=10,
    bold=True,
    font_color=WHITE,
    fill_color=LEGACY_BLUE,
    horizontal="center",
    bordered=True,
)
COLUMN_HEADER = CellStyle(
    font_name="Calibri",
    font_size=9,
    bold=True,
    fill_color=LEGACY_YELLOW,
    horizontal="center",
    wrap_text=True,
    bordered=True,
)
JOB_CELL = CellStyle(bordered=True)
WRAPPED_CELL = CellStyle(wrap_text=True, bordered=True)
JOB_AMOUNT = CellStyle(bold=True, number_format=CURRENCY_FORMAT, bordered=True)
EXPENSE_HEADER = DAY_HEADER
EXPENSE_CELL = WRAPPED_CELL
EXPENSE_AMOUNT = CellStyle(number_format=CURRENCY_FORMAT, bordered=True)
SUMMARY_CELL = CellStyle(wrap_text=True, bordered=True)
SUMMARY_AMOUNT = CellStyle(wrap_text=True, number_format=CURRENCY_FORMAT, bordered=True)
SUMMARY_HEADER = CellStyle(
    bold=True,
    font_color=WHITE,
    fill_color=LEGACY_BLUE,
    wrap_text=True,
    bordered=True,
)
TOTAL_VALUE = CellStyle(
    bold=True,
    font_color=WHITE,
    fill_color=LEGACY_BLUE,
    wrap_text=True,
    number_format=CURRENCY_FORMAT,
    bordered=True,
)


def wrapped_row_height(*values: str, characters_per_line: int) -> int:
    lines = 1
    for value in values:
        if value:
            lines = max(
                lines,
                sum(max(1, -(-len(line) // characters_per_line)) for line in value.splitlines()),
            )
    return max(DATA_ROW_HEIGHT, min(lines * 15, 180))
