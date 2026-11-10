"""Run the full workforce compliance pipeline end to end.

Steps
  1. Load raw HRIS / ATS extracts and reference tables into SQLite
  2. Run SQL control checks          -> exceptions
  3. Reconcile checks vs answer key  -> reconciliation_summary
  4. Clean data, build EEO-1 summary -> eeo1_summary, eeo1_tieout
  5. Adverse impact analysis         -> adverse_impact
  6. Export CSVs, chart, Excel workbook and written summary

Usage:
    python src/run_pipeline.py            # uses data/raw, writes outputs/
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from adverse_impact import analyze  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = ROOT / "sql"
REF_DIR = ROOT / "data" / "reference"

RACE_ORDER = [
    "Hispanic or Latino", "White", "Black or African American",
    "Native Hawaiian or Other Pacific Islander", "Asian",
    "American Indian or Alaska Native", "Two or More Races",
]
CATEGORY_ORDER = list(pd.read_csv(REF_DIR / "job_title_map.csv").eeo1_category.drop_duplicates())


def read_csv_text(path: Path) -> pd.DataFrame:
    """Read every column as text and keep blanks as '' (as a raw extract would)."""
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def load(con: sqlite3.Connection, raw_dir: Path, key: dict) -> None:
    read_csv_text(raw_dir / "hris_employees.csv").to_sql("raw_hris", con, index=False, if_exists="replace")
    read_csv_text(raw_dir / "ats_applicants.csv").to_sql("raw_ats", con, index=False, if_exists="replace")
    read_csv_text(REF_DIR / "job_title_map.csv").to_sql("job_title_map", con, index=False, if_exists="replace")
    read_csv_text(REF_DIR / "title_aliases.csv").to_sql("title_aliases", con, index=False, if_exists="replace")
    pd.DataFrame([{"snapshot_date": key["snapshot_date"], "ats_start": key["ats_window"][0]}]) \
        .to_sql("params", con, index=False, if_exists="replace")


def run_sql(con: sqlite3.Connection, name: str) -> None:
    con.executescript((SQL_DIR / name).read_text())


def reconcile(exceptions: pd.DataFrame, key: dict) -> pd.DataFrame:
    """Compare records caught by each check with the records planted."""
    rows = []
    for check, planted_ids in key["issues"].items():
        found = set(exceptions.loc[exceptions.check_name == check, "record_id"])
        planted = set(planted_ids)
        rows.append({
            "check_name": check,
            "planted": len(planted),
            "detected": len(found),
            "matched": len(found & planted),
            "missed": len(planted - found),
            "unexpected": len(found - planted),
            "result": "PASS" if found == planted else "FAIL",
        })
    return pd.DataFrame(rows)


def eeo1_matrix(summary: pd.DataFrame) -> pd.DataFrame:
    s = summary.copy()
    s["column"] = s.race_ethnicity + " - " + s.sex
    cols = [f"{r} - {x}" for r in RACE_ORDER for x in ["Male", "Female"]]
    m = s.pivot_table(index="eeo1_category", columns="column", values="headcount",
                      aggfunc="sum", fill_value=0)
    m = m.reindex(index=CATEGORY_ORDER, columns=cols, fill_value=0)
    m["Total"] = m.sum(axis=1)
    m.loc["Total"] = m.sum()
    m.index.name = "EEO-1 Job Category"
    return m.astype(int)


def run(raw_dir: Path, out_dir: Path, make_extras: bool = True) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    key = json.loads((raw_dir / "planted_issues.json").read_text())
    db_path = out_dir / "compliance.db"
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)

    load(con, raw_dir, key)
    for script in ["01_checks.sql", "02_clean.sql", "03_eeo1.sql"]:
        run_sql(con, script)

    q = lambda sql: pd.read_sql_query(sql, con)  # noqa: E731
    exceptions = q("SELECT * FROM exceptions ORDER BY check_name, record_id")
    recon = reconcile(exceptions, key)
    summary = q("SELECT * FROM eeo1_summary")
    tieout = q("SELECT * FROM eeo1_tieout")
    matrix = eeo1_matrix(summary)
    clean = q("SELECT * FROM snapshot_workforce ORDER BY employee_id")
    pool = q("SELECT * FROM applicant_pool")
    impact = analyze(pool)
    con.close()

    exceptions.to_csv(out_dir / "exceptions.csv", index=False)
    recon.to_csv(out_dir / "reconciliation_summary.csv", index=False)
    summary.to_csv(out_dir / "eeo1_summary_long.csv", index=False)
    matrix.to_csv(out_dir / "eeo1_report.csv")
    tieout.to_csv(out_dir / "eeo1_tieout.csv", index=False)
    clean.to_csv(out_dir / "snapshot_workforce.csv", index=False)
    impact.to_csv(out_dir / "adverse_impact.csv", index=False)

    results = {"exceptions": exceptions, "reconciliation": recon, "eeo1_long": summary,
               "eeo1_matrix": matrix, "tieout": tieout, "workforce": clean,
               "impact": impact, "key": key}

    if make_extras:
        from build_workbook import build_workbook
        from report import plot_impact, write_summary
        plot_impact(impact, ROOT / "docs" / "impact_ratios.png")
        build_workbook(results, out_dir / "eeo1_workbook.xlsx")
        write_summary(results, ROOT / "docs" / "summary.md")
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    ap.add_argument("--out", type=Path, default=ROOT / "outputs")
    args = ap.parse_args()

    r = run(args.raw, args.out)
    print("\nReconciliation of control checks vs planted issues")
    print(r["reconciliation"].to_string(index=False))
    print("\nEEO-1 tie-out")
    print(r["tieout"].to_string(index=False))
    flagged = r["impact"][r["impact"].finding == "Adverse impact indicated"]
    print("\nAdverse impact indicated")
    print(flagged[["eeo1_category", "group", "applicants", "selection_rate",
                   "impact_ratio", "p_value"]].to_string(index=False))
    print(f"\nOutputs written to {args.out}")


if __name__ == "__main__":
    main()
