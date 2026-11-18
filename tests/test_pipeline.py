"""End-to-end tests: the pipeline must find exactly what was planted."""

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from adverse_impact import two_proportion_z  # noqa: E402
from generate_data import generate  # noqa: E402
import run_pipeline  # noqa: E402


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    raw = tmp_path_factory.mktemp("raw")
    out = tmp_path_factory.mktemp("out")
    hris, ats, key = generate(seed=7)          # different seed from the committed data
    hris.to_csv(raw / "hris_employees.csv", index=False)
    ats.to_csv(raw / "ats_applicants.csv", index=False)
    import json
    (raw / "planted_issues.json").write_text(json.dumps(key))
    return run_pipeline.run(raw, out, make_extras=False)


def test_every_check_finds_exactly_the_planted_records(results):
    recon = results["reconciliation"]
    failed = recon[recon.result != "PASS"]
    assert failed.empty, f"checks that missed or over-flagged records:\n{failed}"


def test_eeo1_ties_out(results):
    tie = dict(zip(results["tieout"].line, results["tieout"].value))
    assert tie["Difference (must be 0)"] == 0
    assert results["eeo1_matrix"].loc["Total", "Total"] == tie["Reported in EEO-1 summary"]


def test_no_duplicates_in_clean_workforce(results):
    wf = results["workforce"]
    assert wf.employee_id.is_unique


def test_planted_disparities_are_flagged(results):
    imp = results["impact"]
    flagged = imp[imp.finding == "Adverse impact indicated"]
    for d in results["key"]["planted_disparities"]:
        hit = flagged[(flagged.eeo1_category == d["eeo1_category"]) & (flagged.group == d["group"])]
        assert len(hit) == 1, f"planted disparity not flagged: {d}"


def test_z_test_matches_hand_calculation():
    # 20/100 vs 40/100: pooled p = 0.30, se = sqrt(.3*.7*.02) = 0.0648, z = -3.086
    z, p = two_proportion_z(20, 100, 40, 100)
    assert z == pytest.approx(-3.086, abs=1e-3)
    assert p == pytest.approx(0.00203, abs=1e-4)


def test_selection_rates_are_valid(results):
    imp = results["impact"]
    assert imp.selection_rate.between(0, 1).all()
    assert (imp.hired <= imp.applicants).all()
    assert isinstance(imp, pd.DataFrame)
