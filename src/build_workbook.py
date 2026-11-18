"""Build the Excel workbook: live COUNTIFS EEO-1 report with a tie-out to SQL.

Every number in the EEO-1 Report and Tie-Out sheets is an Excel formula over
the Workforce sheet, so the workbook re-checks the SQL results independently.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

FONT = "Arial"
HEADER_FILL = PatternFill("solid", start_color="1F3864")
TOTAL_FILL = PatternFill("solid", start_color="D9E1F2")
FLAG_FILL = PatternFill("solid", start_color="F8CBAD")
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def f(bold=False, color="000000", size=10, italic=False):
    return Font(name=FONT, bold=bold, color=color, size=size, italic=italic)


def header_row(ws, row, values, start_col=1):
    for i, v in enumerate(values):
        c = ws.cell(row=row, column=start_col + i, value=v)
        c.font = f(bold=True, color="FFFFFF")
        c.fill = HEADER_FILL
        c.alignment = Alignment(wrap_text=True, horizontal="center", vertical="center")
        c.border = BOX


def write_frame(ws, df, table_name, start_row=1):
    header_row(ws, start_row, list(df.columns))
    for r, row in enumerate(df.itertuples(index=False), start_row + 1):
        for c, v in enumerate(row, 1):
            if isinstance(v, float) and pd.isna(v):
                v = None
            ws.cell(row=r, column=c, value=v).font = f()
    end = f"{get_column_letter(len(df.columns))}{start_row + len(df)}"
    t = Table(displayName=table_name, ref=f"A{start_row}:{end}")
    t.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
    ws.add_table(t)
    for i, col in enumerate(df.columns, 1):
        width = max(len(str(col)), *(len(str(x)) for x in df[col].head(200))) + 2
        ws.column_dimensions[get_column_letter(i)].width = min(width, 45)
    ws.freeze_panes = ws.cell(row=start_row + 1, column=1)


def build_workbook(r: dict, path: Path) -> None:
    wb = Workbook()

    # ---------------- About ----------------
    ws = wb.active
    ws.title = "About"
    notes = [
        ("Workforce Compliance Analytics: EEO-1 Workbook", f(bold=True, size=14)),
        ("All data is simulated. Built by src/build_workbook.py from the SQL pipeline outputs.", f(italic=True)),
        ("", f()),
        ("Sheets", f(bold=True)),
        ("Workforce: active employees on the snapshot date after cleaning (from SQL view snapshot_workforce).", f()),
        ("EEO-1 Report: job category x race/ethnicity x sex, every cell a COUNTIFS formula over Workforce.", f()),
        ("Tie-Out: control checks proving every employee is counted once, and that Excel matches SQL.", f()),
        ("Adverse Impact: hiring selection rates, impact ratios (formulas) and z-test results (from Python).", f()),
        ("Exceptions: every record caught by the SQL control checks, plus the reconciliation summary.", f()),
        ("", f()),
        ("Colour key", f(bold=True)),
        ("Blue text = values pasted from the Python/SQL pipeline. Black text = Excel formulas.", f()),
        ("Red fill = adverse impact indicated (fails 80% rule and p < 0.05).", f()),
        ("", f()),
        ("Try it in Excel", f(bold=True)),
        ("1. Data > Get Data > From Text/CSV > outputs/snapshot_workforce.csv to load the data with Power Query.", f()),
        ("2. Insert > PivotTable: Rows = eeo1_category; Columns = race_ethnicity, sex; Values = Count of employee_id.", f()),
        ("3. Compare the PivotTable grand total with Tie-Out!C4. They should match.", f()),
    ]
    for i, (text, font) in enumerate(notes, 1):
        ws.cell(row=i, column=1, value=text).font = font
    ws.column_dimensions["A"].width = 110

    # ---------------- Workforce ----------------
    wf = r["workforce"][["employee_id", "job_title", "eeo1_category", "hire_date",
                         "termination_date", "status", "sex", "race_ethnicity"]]
    ws = wb.create_sheet("Workforce")
    write_frame(ws, wf, "Workforce")
    n = len(wf) + 1
    CAT = f"Workforce!$C$2:$C${n}"
    SEX = f"Workforce!$G$2:$G${n}"
    RACE = f"Workforce!$H$2:$H${n}"
    IDS = f"Workforce!$A$2:$A${n}"

    # ---------------- EEO-1 Report ----------------
    ws = wb.create_sheet("EEO-1 Report")
    m = r["eeo1_matrix"]
    cats = [c for c in m.index if c != "Total"]
    cols = [c for c in m.columns if c != "Total"]
    ws["A1"] = "EEO-1 Component 1 style report: active workforce on snapshot date"
    ws["A1"].font = f(bold=True, size=12)
    ws["A2"] = "Every count is a COUNTIFS formula over the Workforce sheet. Employees with sex or race not reported are excluded (see Tie-Out)."
    ws["A2"].font = f(italic=True)

    # Two header rows: race on row 4 (merged over Male/Female), sex on row 5.
    header_row(ws, 4, ["Job Category"])
    ws.merge_cells("A4:A5")
    col = 2
    races = list(dict.fromkeys(c.rsplit(" - ", 1)[0] for c in cols))
    for race in races:
        header_row(ws, 4, [race], start_col=col)
        ws.merge_cells(start_row=4, start_column=col, end_row=4, end_column=col + 1)
        header_row(ws, 5, ["Male", "Female"], start_col=col)
        col += 2
    total_col = col
    header_row(ws, 4, ["Total"], start_col=total_col)
    ws.merge_cells(start_row=4, start_column=total_col, end_row=5, end_column=total_col)
    ws.row_dimensions[4].height = 45

    first = 6
    for i, cat in enumerate(cats):
        row = first + i
        ws.cell(row=row, column=1, value=cat).font = f(bold=True)
        for j, colname in enumerate(cols):
            race, sex = colname.rsplit(" - ", 1)
            c = ws.cell(row=row, column=2 + j,
                        value=f'=COUNTIFS({CAT},$A{row},{RACE},"{race}",{SEX},"{sex}")')
            c.font, c.border = f(), BOX
        L1, L2 = get_column_letter(2), get_column_letter(total_col - 1)
        c = ws.cell(row=row, column=total_col, value=f"=SUM({L1}{row}:{L2}{row})")
        c.font, c.fill, c.border = f(bold=True), TOTAL_FILL, BOX
    last = first + len(cats) - 1
    trow = last + 1
    ws.cell(row=trow, column=1, value="Total").font = f(bold=True)
    for cidx in range(2, total_col + 1):
        L = get_column_letter(cidx)
        c = ws.cell(row=trow, column=cidx, value=f"=SUM({L}{first}:{L}{last})")
        c.font, c.fill, c.border = f(bold=True), TOTAL_FILL, BOX
    ws.column_dimensions["A"].width = 38
    for cidx in range(2, total_col + 1):
        ws.column_dimensions[get_column_letter(cidx)].width = 9
    ws.freeze_panes = "B6"
    grand_total = f"'EEO-1 Report'!{get_column_letter(total_col)}{trow}"

    # ---------------- Tie-Out ----------------
    ws = wb.create_sheet("Tie-Out")
    tv = dict(zip(r["tieout"].line, r["tieout"].value))
    ws["A1"] = "EEO-1 tie-out and control checks"
    ws["A1"].font = f(bold=True, size=12)
    header_row(ws, 3, ["#", "Line", "Excel (formula)", "SQL pipeline", "Difference"])
    rows = [
        ("Active workforce on snapshot date", f"=COUNTA({IDS})",
         tv["Snapshot headcount (clean, deduplicated)"]),
        ("Reported in EEO-1 Report", f"={grand_total}", tv["Reported in EEO-1 summary"]),
        ("Not reported (sex or race), held for HR follow-up",
         f'=COUNTIF({SEX},"Not reported")+COUNTIF({RACE},"Not reported")'
         f'-COUNTIFS({SEX},"Not reported",{RACE},"Not reported")',
         tv["Excluded: sex or race not reported (HR follow-up)"]),
        ("Unaccounted (row 4 - row 5 - row 6), must be 0", "=C4-C5-C6", tv["Difference (must be 0)"]),
    ]
    for i, (label, formula, sqlv) in enumerate(rows):
        rr = 4 + i
        ws.cell(row=rr, column=1, value=i + 1).font = f()
        ws.cell(row=rr, column=2, value=label).font = f()
        ws.cell(row=rr, column=3, value=formula).font = f()
        ws.cell(row=rr, column=4, value=int(sqlv)).font = f(color="0000FF")
        ws.cell(row=rr, column=5, value=f"=C{rr}-D{rr}").font = f(bold=True)
        for cc in range(1, 6):
            ws.cell(row=rr, column=cc).border = BOX
    ws["B9"] = "Overall control status"
    ws["B9"].font = f(bold=True)
    ws["C9"] = '=IF(AND(C7=0,SUMPRODUCT(ABS(E4:E7))=0),"PASS","FAIL - investigate")'
    ws["C9"].font = f(bold=True)
    ws["B11"] = "SQL pipeline column: pasted from outputs/eeo1_tieout.csv (blue = pasted value)."
    ws["B11"].font = f(italic=True)
    ws.column_dimensions["A"].width = 4
    ws.column_dimensions["B"].width = 52
    for L in "CDE":
        ws.column_dimensions[L].width = 16

    # ---------------- Adverse Impact ----------------
    ws = wb.create_sheet("Adverse Impact")
    imp = r["impact"]
    ws["A1"] = "Hiring adverse impact: four-fifths rule and two-proportion z-test"
    ws["A1"].font = f(bold=True, size=12)
    ws["A2"] = ("Applicants, hires, z and p-values come from src/adverse_impact.py (blue). "
                "Selection rate, impact ratio and the 80% test are Excel formulas (black).")
    ws["A2"].font = f(italic=True)
    ws["A3"] = "Four-fifths threshold"
    ws["A3"].font = f(bold=True)
    ws["B3"] = 0.8
    ws["B3"].font = f(color="0000FF")
    ws["B3"].number_format = "0%"
    ws["C3"] = "Source: Uniform Guidelines on Employee Selection Procedures (1978), 29 CFR 1607.4(D)"
    ws["C3"].font = f(italic=True)
    hdr = ["Job Category", "Dimension", "Group", "Applicants", "Hired", "Selection Rate",
           "Reference Group", "Reference Rate", "Impact Ratio", "Fails 80% Rule",
           "z-score", "p-value", "Finding"]
    header_row(ws, 5, hdr)
    start = 6
    end = start + len(imp) - 1
    for i, row in enumerate(imp.itertuples(index=False)):
        rr = start + i
        vals = [row.eeo1_category, row.dimension, row.group, row.applicants, row.hired]
        for c, v in enumerate(vals, 1):
            ws.cell(row=rr, column=c, value=v).font = f(color="0000FF" if c in (4, 5) else "000000")
        ws.cell(row=rr, column=6, value=f"=IF(D{rr}=0,0,E{rr}/D{rr})").number_format = "0.0%"
        ws.cell(row=rr, column=7, value=row.reference_group).font = f()
        ws.cell(row=rr, column=8, value=(
            f'=SUMIFS($E${start}:$E${end},$A${start}:$A${end},A{rr},$B${start}:$B${end},B{rr},$C${start}:$C${end},G{rr})'
            f'/SUMIFS($D${start}:$D${end},$A${start}:$A${end},A{rr},$B${start}:$B${end},B{rr},$C${start}:$C${end},G{rr})'
        )).number_format = "0.0%"
        ws.cell(row=rr, column=9, value=f"=IF(H{rr}=0,0,F{rr}/H{rr})").number_format = "0.00"
        ws.cell(row=rr, column=10, value=f'=IF(I{rr}<$B$3,"Yes","No")')
        ws.cell(row=rr, column=11, value=row.z_score).font = f(color="0000FF")
        ws.cell(row=rr, column=12, value=row.p_value).font = f(color="0000FF")
        ws.cell(row=rr, column=12).number_format = "0.0000"
        ws.cell(row=rr, column=13, value=row.finding).font = f()
        for c in (6, 8, 9, 10):
            ws.cell(row=rr, column=c).font = f()
        if row.finding == "Adverse impact indicated":
            for c in range(1, 14):
                ws.cell(row=rr, column=c).fill = FLAG_FILL
    widths = [36, 15, 40, 11, 8, 11, 40, 11, 10, 10, 9, 9, 28]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "D6"
    ws.auto_filter.ref = f"A5:M{end}"

    # ---------------- Exceptions ----------------
    ws = wb.create_sheet("Exceptions")
    rec = r["reconciliation"]
    ws["A1"] = "Reconciliation: SQL control checks vs planted answer key"
    ws["A1"].font = f(bold=True, size=12)
    header_row(ws, 3, list(rec.columns))
    for i, row in enumerate(rec.itertuples(index=False)):
        for c, v in enumerate(row, 1):
            ws.cell(row=4 + i, column=c, value=v).font = f(color="0000FF")
    exc_start = 4 + len(rec) + 2
    ws.cell(row=exc_start - 1, column=1, value="Exception detail (one row per record)").font = f(bold=True)
    exc = r["exceptions"]
    header_row(ws, exc_start, list(exc.columns))
    for i, row in enumerate(exc.itertuples(index=False)):
        for c, v in enumerate(row, 1):
            ws.cell(row=exc_start + 1 + i, column=c, value=v).font = f()
    for i, w in enumerate([28, 14, 14, 12, 10, 12, 10], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.column_dimensions["D"].width = 60

    wb.save(path)
