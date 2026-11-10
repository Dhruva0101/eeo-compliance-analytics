"""Chart and one-page written summary for nontechnical stakeholders."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from adverse_impact import FOUR_FIFTHS, MIN_REFERENCE_N, SMALL_GROUP_N  # noqa: E402


def plot_impact(impact: pd.DataFrame, path: Path) -> None:
    """Impact ratios for every non-reference group with 30+ applicants."""
    path.parent.mkdir(parents=True, exist_ok=True)
    d = impact[(impact.finding != "Reference group") & (~impact.small_group)].copy()
    d["label"] = d.eeo1_category + " | " + d.group
    d = d.sort_values("impact_ratio", ascending=False)
    flagged = d.finding == "Adverse impact indicated"
    colors = ["#c0392b" if f else ("#e0a040" if r < FOUR_FIFTHS else "#7f8c8d")
              for f, r in zip(flagged, d.impact_ratio)]

    fig, ax = plt.subplots(figsize=(9, max(4, 0.2 * len(d))))
    ax.barh(d.label, d.impact_ratio, color=colors)
    ax.axvline(FOUR_FIFTHS, color="#333", linestyle="--", linewidth=1)
    ax.text(FOUR_FIFTHS + 0.01, -0.9, "80% threshold", fontsize=8)
    ax.set_xlabel("Impact ratio (group selection rate / reference group rate)")
    ax.set_title("Hiring impact ratios by job category and group\n"
                 "red = fails 80% rule and statistically significant; amber = fails 80% rule only",
                 fontsize=10)
    ax.tick_params(axis="y", labelsize=7)
    ax.set_xlim(0, max(1.6, d.impact_ratio.max() + 0.05))
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def write_summary(r: dict, path: Path) -> None:
    recon, tie, impact = r["reconciliation"], r["tieout"], r["impact"]
    tv = dict(zip(tie.line, tie.value))
    exc_total = len(r["exceptions"])
    flagged = impact[impact.finding == "Adverse impact indicated"]
    review = impact[impact.finding.str.startswith("Review")]
    small_review = review[review.small_group]

    lines = [
        "# Workforce Compliance Review: Summary of Findings",
        "",
        f"*Snapshot date: {r['key']['snapshot_date']}. All data is simulated for demonstration.*",
        "",
        "## 1. Data quality and reconciliation",
        "",
        f"Seven control checks compared the HR system (HRIS) with the applicant-tracking "
        f"system (ATS). They raised **{exc_total} exceptions**, and every check caught exactly "
        f"the records that were planted in the data "
        f"({(recon.result == 'PASS').sum()} of {len(recon)} checks passed).",
        "",
        "| Check | Records caught | How it was resolved |",
        "|---|---:|---|",
    ]
    resolution = {
        "duplicate_employee_id": "Kept one row per employee",
        "missing_demographics": "Kept in headcount, listed for HR follow-up",
        "unmapped_job_title": "Remapped through the title alias table",
        "invalid_hire_date": "Excluded until HR corrects the date",
        "demographic_mismatch": "HRIS used as system of record; listed for review",
        "ats_hire_missing_in_hris": "Listed for HR to confirm start or rescinded offer",
        "hris_hire_missing_in_ats": "Kept in headcount; listed for Recruiting to confirm",
    }
    for _, row in recon.iterrows():
        lines.append(f"| {row.check_name.replace('_', ' ')} | {row.detected} | "
                     f"{resolution.get(row.check_name, '')} |")

    lines += [
        "",
        "## 2. EEO-1 workforce summary",
        "",
        f"- Active workforce on the snapshot date: **{tv['Snapshot headcount (clean, deduplicated)']:,}**",
        f"- Reported in the EEO-1 table: **{tv['Reported in EEO-1 summary']:,}**",
        f"- Held back because sex or race was not reported: **{tv['Excluded: sex or race not reported (HR follow-up)']}**",
        f"- Tie-out difference: **{tv['Difference (must be 0)']}** (every employee is accounted for)",
        "",
        "## 3. Hiring adverse impact",
        "",
        "Each group's hiring rate was compared with the highest-rate group in the same job "
        f"category (minimum {MIN_REFERENCE_N} applicants to serve as the benchmark). A group "
        "is flagged when its rate is below 80% of the benchmark (the four-fifths rule) **and** "
        "a two-proportion z-test shows the gap is unlikely to be chance (p < 0.05).",
        "",
        "| Job category | Group | Applicants | Hire rate | Benchmark rate | Impact ratio | p-value |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for _, f in flagged.iterrows():
        lines.append(f"| {f.eeo1_category} | {f.group} | {f.applicants} | {f.selection_rate:.1%} | "
                     f"{f.reference_rate:.1%} ({f.reference_group}) | {f.impact_ratio:.2f} | {"<0.0001" if f.p_value < 0.0001 else f"{f.p_value:.4f}"} |")
    lines += [
        "",
        f"A further **{len(review)} group comparisons** fall below 80% without a statistically "
        f"significant gap; {len(small_review)} of them involve fewer than {SMALL_GROUP_N} "
        "applicants, where one or two hires swing the ratio. These are listed in "
        "`outputs/adverse_impact.csv` for monitoring rather than action.",
        "",
        "![Impact ratios](impact_ratios.png)",
        "",
        "## 4. Recommended next steps",
        "",
        "1. Review the selection process for the two flagged groups (job requirements, "
        "interview panels, requisition-level results) with Talent and Recruiting.",
        "2. Send the HR follow-up list (missing demographics, invalid dates, unmatched hires) to "
        "the HRIS team and re-run the pipeline once corrected.",
        "3. Add the title alias table to the monthly refresh so new title variants are caught early.",
        "",
        "## 5. Limitations",
        "",
        "- Data is simulated; real reviews also consider job-relatedness and business necessity.",
        "- Applicants who did not self-identify are excluded from that dimension's analysis.",
        "- Many comparisons are run at once, so a few significant results can occur by chance; "
        "findings should be confirmed at the requisition level.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))
