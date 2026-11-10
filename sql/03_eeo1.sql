-- =====================================================================
-- 03_eeo1.sql  --  EEO-1 style workforce summary and tie-out
--
-- EEO-1 Component 1 layout: job category x race/ethnicity x sex.
-- Hispanic or Latino is reported by sex; other races are non-Hispanic.
-- =====================================================================

DROP TABLE IF EXISTS eeo1_summary;
CREATE TABLE eeo1_summary AS
SELECT eeo1_category,
       race_ethnicity,
       sex,
       COUNT(*) AS headcount
FROM snapshot_workforce
WHERE sex <> 'Not reported'
  AND race_ethnicity <> 'Not reported'
GROUP BY eeo1_category, race_ethnicity, sex;

-- Tie-out: every snapshot employee must be either in the EEO-1 table
-- or in the "Not reported" follow-up list. Difference must be zero.
DROP TABLE IF EXISTS eeo1_tieout;
CREATE TABLE eeo1_tieout AS
SELECT 'Snapshot headcount (clean, deduplicated)' AS line,
       (SELECT COUNT(*) FROM snapshot_workforce) AS value
UNION ALL
SELECT 'Reported in EEO-1 summary',
       (SELECT SUM(headcount) FROM eeo1_summary)
UNION ALL
SELECT 'Excluded: sex or race not reported (HR follow-up)',
       (SELECT COUNT(*) FROM snapshot_workforce
         WHERE sex = 'Not reported' OR race_ethnicity = 'Not reported')
UNION ALL
SELECT 'Difference (must be 0)',
       (SELECT COUNT(*) FROM snapshot_workforce)
     - (SELECT SUM(headcount) FROM eeo1_summary)
     - (SELECT COUNT(*) FROM snapshot_workforce
         WHERE sex = 'Not reported' OR race_ethnicity = 'Not reported')
UNION ALL
SELECT 'Records excluded for invalid hire date (HR follow-up)',
       (SELECT COUNT(*) FROM clean_hris WHERE invalid_hire_date = 1)
UNION ALL
SELECT 'Raw HRIS rows removed as duplicates',
       (SELECT COUNT(*) FROM raw_hris) - (SELECT COUNT(*) FROM clean_hris);

-- Applicant pool for adverse impact: completed decisions only
-- (Hired or Rejected); withdrawn applicants are not part of a selection.
DROP VIEW IF EXISTS applicant_pool;
CREATE VIEW applicant_pool AS
SELECT a.applicant_id,
       a.requisition_id,
       a.job_title,
       m.eeo1_category,
       a.sex,
       a.race_ethnicity,
       CASE WHEN a.disposition = 'Hired' THEN 1 ELSE 0 END AS hired
FROM raw_ats a
JOIN job_title_map m ON m.job_title = a.job_title
WHERE a.disposition IN ('Hired', 'Rejected');
