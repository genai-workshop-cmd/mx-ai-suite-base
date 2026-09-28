"""Excel output: the Agent 4 test-case workbook and generic tabular exports.

Column set is fixed by blueprint section 4, Agent 4:
Test Case ID, Module, Scenario, Pre-conditions, Test Steps, Expected Result,
Actual Result (blank), Pass/Fail, Notes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from core.logging import get

log = get("suite.render.xlsx")

TESTCASE_COLUMNS = [
    "Test Case ID",
    "Module",
    "Scenario",
    "Type",
    "Pre-conditions",
    "Test Steps",
    "Expected Result",
    "Actual Result",
    "Pass/Fail",
    "Notes",
]

#: Width hints so the workbook is readable without manual resizing.
_WIDTHS = {
    "Test Case ID": 16,
    "Module": 16,
    "Scenario": 46,
    "Type": 14,
    "Pre-conditions": 40,
    "Test Steps": 62,
    "Expected Result": 52,
    "Actual Result": 22,
    "Pass/Fail": 11,
    "Notes": 28,
}

_HEADER_FILL = "1F3A5F"
_HEADER_FONT = "FFFFFF"
_BAND_FILL = "F2F6FA"


@dataclass
class Sheet:
    title: str
    columns: list[str]
    rows: list[list[Any]] = field(default_factory=list)
    freeze: str = "A2"
    autofilter: bool = True


def write_workbook(sheets: Sequence[Sheet], target: Path) -> Path:
    """Write styled sheets to an .xlsx."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    target.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    wb.remove(wb.active)

    thin = Side(style="thin", color="D5DCE4")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    header_fill = PatternFill("solid", fgColor=_HEADER_FILL)
    band_fill = PatternFill("solid", fgColor=_BAND_FILL)
    header_font = Font(bold=True, color=_HEADER_FONT, size=10)
    body_font = Font(size=10)

    for sheet in sheets:
        # Excel forbids these characters in a sheet name, and caps it at 31 chars.
        safe = "".join(c for c in sheet.title if c not in "[]:*?/\\")[:31] or "Sheet"
        ws = wb.create_sheet(safe)

        ws.append(sheet.columns)
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.border = border
            cell.alignment = Alignment(vertical="center", horizontal="left", wrap_text=True)
        ws.row_dimensions[1].height = 26

        for r, row in enumerate(sheet.rows, start=2):
            padded = list(row) + [""] * (len(sheet.columns) - len(row))
            ws.append(padded[: len(sheet.columns)])
            for cell in ws[r]:
                cell.border = border
                cell.font = body_font
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                if r % 2 == 0:
                    cell.fill = band_fill

        for c, name in enumerate(sheet.columns, start=1):
            letter = get_column_letter(c)
            if name in _WIDTHS:
                width = _WIDTHS[name]
            else:
                longest = max([len(str(name))] + [len(str(r[c - 1])) for r in sheet.rows if len(r) >= c] or [10])
                width = min(max(longest + 2, 12), 60)
            ws.column_dimensions[letter].width = width

        if sheet.freeze:
            ws.freeze_panes = sheet.freeze
        if sheet.autofilter and sheet.rows:
            ws.auto_filter.ref = f"A1:{get_column_letter(len(sheet.columns))}{len(sheet.rows) + 1}"

    wb.save(str(target))
    log.info("wrote %s (%d sheet(s))", target.name, len(sheets))
    return target


def write_testcases(
    rows: list[dict[str, Any]],
    target: Path,
    *,
    summary_rows: list[list[Any]] | None = None,
) -> Path:
    """Write the Agent 4 workbook: Test Cases + Coverage Summary."""
    body = [[r.get(col, "") for col in TESTCASE_COLUMNS] for r in rows]
    sheets = [Sheet(title="Test Cases", columns=TESTCASE_COLUMNS, rows=body)]
    if summary_rows:
        sheets.append(
            Sheet(
                title="Coverage Summary",
                columns=["Requirement / Change Item", "Happy path", "Negative", "Integration", "Regression", "Total"],
                rows=summary_rows,
                autofilter=False,
            )
        )
    return write_workbook(sheets, target)
