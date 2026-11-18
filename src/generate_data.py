"""Generate simulated HRIS and applicant-tracking (ATS) extracts.

All data is synthetic. The script deliberately plants data-quality problems
and two hiring disparities, and records every planted issue in
data/raw/planted_issues.json so the pipeline's checks can be verified
against a known answer key.

Usage:
    python src/generate_data.py [--seed 42] [--out data/raw]
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "data" / "reference"

SNAPSHOT = date(2025, 12, 31)          # EEO-1 workforce snapshot date
ATS_START = date(2024, 1, 1)           # applicant-tracking window
ATS_END_APPS = date(2025, 10, 31)      # last application date

N_LEGACY = 4_000                       # employees hired before the ATS window
N_APPLICANTS = 10_000

SEX = ["Male", "Female"]
SEX_P = [0.52, 0.48]
RACE = [
    "White",
    "Hispanic or Latino",
    "Black or African American",
    "Asian",
    "Two or More Races",
    "American Indian or Alaska Native",
    "Native Hawaiian or Other Pacific Islander",
]
RACE_P = [0.55, 0.17, 0.13, 0.10, 0.03, 0.01, 0.01]
NOT_DISCLOSED = "Not disclosed"

# Baseline probability that an applicant is hired, by EEO-1 category.
BASE_HIRE_RATE = {
    "Executive/Senior Officials & Managers": 0.08,
    "First/Mid-Level Officials & Managers": 0.12,
    "Professionals": 0.18,
    "Technicians": 0.22,
    "Sales Workers": 0.25,
    "Administrative Support Workers": 0.25,
    "Craft Workers": 0.22,
    "Operatives": 0.30,
    "Laborers & Helpers": 0.35,
    "Service Workers": 0.30,
}

# Planted disparities the adverse impact analysis should find.
PLANTED_DISPARITIES = [
    {"eeo1_category": "Technicians", "dimension": "sex",
     "group": "Female", "multiplier": 0.55},
    {"eeo1_category": "Sales Workers", "dimension": "race_ethnicity",
     "group": "Black or African American", "multiplier": 0.55},
]

# Relative volume of applicants / legacy employees per job title.
TITLE_WEIGHTS = {
    "Chief Operating Officer": 0.2, "Vice President": 0.6, "Director": 1.5,
    "Operations Manager": 3, "Team Lead": 4,
    "Data Analyst": 6, "Software Engineer": 7, "Accountant": 4, "HR Generalist": 3,
    "IT Support Technician": 6, "Lab Technician": 5,
    "Account Executive": 6, "Sales Representative": 8,
    "Administrative Assistant": 5, "Payroll Clerk": 3,
    "Electrician": 3, "Maintenance Mechanic": 3,
    "Machine Operator": 6, "Warehouse Associate": 10, "Security Officer": 5,
}

# How many records of each planted issue to create.
N_DUPLICATES = 60
N_MISSING_DEMO = 90
N_UNMAPPED = 45
N_FUTURE_DATES = 8
N_MALFORMED_DATES = 4
N_ATS_HIRE_NOT_IN_HRIS = 25
N_HRIS_HIRE_NOT_IN_ATS = 20
N_DEMO_MISMATCH = 30


def rand_dates(rng, start: date, end: date, n: int) -> list[date]:
    span = (end - start).days
    return [start + timedelta(days=int(d)) for d in rng.integers(0, span + 1, n)]


def generate(seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    rng = np.random.default_rng(seed)
    title_map = pd.read_csv(REF / "job_title_map.csv")
    cat_of = dict(zip(title_map.job_title, title_map.eeo1_category))
    titles = list(TITLE_WEIGHTS)
    weights = np.array([TITLE_WEIGHTS[t] for t in titles], dtype=float)
    weights /= weights.sum()
    aliases = pd.read_csv(REF / "title_aliases.csv")

    # ---------------- Applicants (ATS) ----------------
    n = N_APPLICANTS
    app = pd.DataFrame({
        "applicant_id": [f"A{i:06d}" for i in range(1, n + 1)],
        "job_title": rng.choice(titles, n, p=weights),
        "application_date": rand_dates(rng, ATS_START, ATS_END_APPS, n),
        "true_sex": rng.choice(SEX, n, p=SEX_P),
        "true_race": rng.choice(RACE, n, p=RACE_P),
    })
    app["eeo1_category"] = app.job_title.map(cat_of)
    # One requisition per title per quarter.
    q = pd.to_datetime(app.application_date).dt.to_period("Q").astype(str)
    req_key = app.job_title + "|" + q
    req_ids = {k: f"R{i:04d}" for i, k in enumerate(sorted(req_key.unique()), 1)}
    app["requisition_id"] = req_key.map(req_ids)

    # Hiring outcome with planted disparities.
    p = app.eeo1_category.map(BASE_HIRE_RATE).astype(float)
    for d in PLANTED_DISPARITIES:
        col = "true_sex" if d["dimension"] == "sex" else "true_race"
        mask = (app.eeo1_category == d["eeo1_category"]) & (app[col] == d["group"])
        p[mask] *= d["multiplier"]
    u = rng.random(n)
    hired = u < p
    withdrew = (~hired) & (rng.random(n) < 0.08)
    app["disposition"] = np.where(hired, "Hired", np.where(withdrew, "Withdrew", "Rejected"))

    # Voluntary self-identification: some applicants decline.
    app["sex"] = np.where(rng.random(n) < 0.05, NOT_DISCLOSED, app.true_sex)
    app["race_ethnicity"] = np.where(rng.random(n) < 0.07, NOT_DISCLOSED, app.true_race)

    hires = app[app.disposition == "Hired"].copy()
    hires["employee_id"] = [f"E{i:05d}" for i in range(N_LEGACY + 1, N_LEGACY + 1 + len(hires))]
    offset = rng.integers(14, 61, len(hires))
    hires["hire_date"] = [
        min(d + timedelta(days=int(o)), SNAPSHOT) for d, o in zip(hires.application_date, offset)
    ]
    app = app.merge(hires[["applicant_id", "employee_id"]], on="applicant_id", how="left")

    # ---------------- Employees (HRIS) ----------------
    legacy = pd.DataFrame({
        "employee_id": [f"E{i:05d}" for i in range(1, N_LEGACY + 1)],
        "job_title": rng.choice(titles, N_LEGACY, p=weights),
        "hire_date": rand_dates(rng, date(2008, 1, 1), date(2023, 12, 31), N_LEGACY),
        "sex": rng.choice(SEX, N_LEGACY, p=SEX_P),
        "race_ethnicity": rng.choice(RACE, N_LEGACY, p=RACE_P),
    })
    new = pd.DataFrame({
        "employee_id": hires.employee_id.values,
        "job_title": hires.job_title.values,
        "hire_date": hires.hire_date.values,
        "sex": hires.true_sex.values,              # HR records the true value
        "race_ethnicity": hires.true_race.values,
    })
    hris = pd.concat([legacy, new], ignore_index=True)
    hris["hire_date"] = hris.hire_date.astype(str)

    # Terminations (about 12% of staff left before the snapshot).
    term = rng.random(len(hris)) < 0.12
    hd = pd.to_datetime(hris.hire_date)
    gap = rng.integers(30, 900, len(hris))
    tdates = [min(h + pd.Timedelta(days=int(g)), pd.Timestamp(SNAPSHOT)) for h, g in zip(hd, gap)]
    hris["termination_date"] = [t.date().isoformat() if x and t.date() < SNAPSHOT else ""
                                for t, x in zip(tdates, term)]
    hris["status"] = np.where(hris.termination_date != "", "Terminated", "Active")

    # ---------------- Plant data-quality issues ----------------
    manifest: dict[str, list[str]] = {}
    legacy_pool = list(rng.permutation(legacy.employee_id.values))

    def take(k: int) -> list[str]:
        out = [legacy_pool.pop() for _ in range(k)]
        return sorted(out)

    idx = hris.set_index("employee_id").index

    # 1. Missing demographics (blank sex or race)
    ids = take(N_MISSING_DEMO)
    for i, e in enumerate(ids):
        col = "sex" if i % 2 == 0 else "race_ethnicity"
        hris.loc[idx == e, col] = ""
    manifest["missing_demographics"] = ids

    # 2. Job titles not in the EEO-1 mapping (alias spellings)
    ids = take(N_UNMAPPED)
    for i, e in enumerate(ids):
        a = aliases.iloc[i % len(aliases)]
        hris.loc[idx == e, "job_title"] = a.raw_title
    manifest["unmapped_job_title"] = ids

    # 3. Invalid hire dates (future or malformed)
    ids = take(N_FUTURE_DATES + N_MALFORMED_DATES)
    for i, e in enumerate(ids):
        bad = "2027-03-15" if i < N_FUTURE_DATES else "2024-13-40"
        hris.loc[idx == e, "hire_date"] = bad
        hris.loc[idx == e, ["termination_date", "status"]] = ["", "Active"]
    manifest["invalid_hire_date"] = ids

    # 4. Duplicate employee rows (exact copies)
    ids = take(N_DUPLICATES)
    dups = hris[hris.employee_id.isin(ids)]
    hris = pd.concat([hris, dups], ignore_index=True)
    manifest["duplicate_employee_id"] = ids

    # 5. Demographic mismatch between ATS and HRIS for the same hire
    eligible = app[(app.disposition == "Hired") & (app.sex != NOT_DISCLOSED)
                   & (app.race_ethnicity != NOT_DISCLOSED)].employee_id
    ids = sorted(rng.choice(eligible.values, N_DEMO_MISMATCH, replace=False))
    for e in ids:
        m = hris.employee_id == e
        cur = hris.loc[m, "sex"].iloc[0]
        hris.loc[m, "sex"] = "Female" if cur == "Male" else "Male"
    manifest["demographic_mismatch"] = list(ids)

    # 6. ATS hires missing from HRIS
    remaining = sorted(set(eligible) - set(ids))
    ids = sorted(rng.choice(remaining, N_ATS_HIRE_NOT_IN_HRIS, replace=False))
    hris = hris[~hris.employee_id.isin(ids)]
    manifest["ats_hire_missing_in_hris"] = list(ids)

    # 7. HRIS hires inside the ATS window with no applicant record
    start_id = N_LEGACY + len(hires) + 1
    orphan = pd.DataFrame({
        "employee_id": [f"E{i:05d}" for i in range(start_id, start_id + N_HRIS_HIRE_NOT_IN_ATS)],
        "job_title": rng.choice(titles, N_HRIS_HIRE_NOT_IN_ATS, p=weights),
        "hire_date": [d.isoformat() for d in rand_dates(rng, date(2024, 2, 1), date(2025, 11, 30), N_HRIS_HIRE_NOT_IN_ATS)],
        "sex": rng.choice(SEX, N_HRIS_HIRE_NOT_IN_ATS, p=SEX_P),
        "race_ethnicity": rng.choice(RACE, N_HRIS_HIRE_NOT_IN_ATS, p=RACE_P),
        "termination_date": "",
        "status": "Active",
    })
    hris = pd.concat([hris, orphan], ignore_index=True)
    manifest["hris_hire_missing_in_ats"] = sorted(orphan.employee_id)

    # Shuffle rows so problems are not clustered.
    hris = hris.sample(frac=1, random_state=seed).reset_index(drop=True)
    hris = hris[["employee_id", "job_title", "hire_date", "termination_date",
                 "status", "sex", "race_ethnicity"]]

    ats = app[["applicant_id", "requisition_id", "job_title", "application_date",
               "sex", "race_ethnicity", "disposition", "employee_id"]].copy()
    ats["application_date"] = ats.application_date.astype(str)
    ats["employee_id"] = ats.employee_id.fillna("")

    answer_key = {
        "seed": seed,
        "snapshot_date": SNAPSHOT.isoformat(),
        "ats_window": [ATS_START.isoformat(), SNAPSHOT.isoformat()],
        "issues": manifest,
        "planted_disparities": PLANTED_DISPARITIES,
    }
    return hris, ats, answer_key


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "raw")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    hris, ats, key = generate(args.seed)
    hris.to_csv(args.out / "hris_employees.csv", index=False)
    ats.to_csv(args.out / "ats_applicants.csv", index=False)
    (args.out / "planted_issues.json").write_text(json.dumps(key, indent=2))

    print(f"HRIS rows: {len(hris):,}  |  ATS rows: {len(ats):,}")
    for k, v in key["issues"].items():
        print(f"  planted {k:<28} {len(v):>4}")


if __name__ == "__main__":
    main()
