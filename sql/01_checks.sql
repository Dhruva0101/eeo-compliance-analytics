-- =====================================================================
-- 01_checks.sql  --  Data-quality and reconciliation control checks
--
-- Inputs : raw_hris, raw_ats, job_title_map, title_aliases, params
-- Output : exceptions (one row per record that fails a check)
--
-- Every check writes to the same exceptions table so results can be
-- counted, reviewed, and tied back to the answer key in one place.
-- =====================================================================

DROP TABLE IF EXISTS exceptions;
CREATE TABLE exceptions (
    check_name TEXT NOT NULL,
    source     TEXT NOT NULL,      -- HRIS, ATS, or HRIS vs ATS
    record_id  TEXT NOT NULL,
    detail     TEXT
);

-- ---------------------------------------------------------------------
-- Check 1: duplicate employee IDs in HRIS
-- ---------------------------------------------------------------------
INSERT INTO exceptions
SELECT 'duplicate_employee_id', 'HRIS', employee_id,
       COUNT(*) || ' rows for this employee_id'
FROM raw_hris
GROUP BY employee_id
HAVING COUNT(*) > 1;

-- ---------------------------------------------------------------------
-- Check 2: missing sex or race/ethnicity in HRIS
-- ---------------------------------------------------------------------
INSERT INTO exceptions
SELECT DISTINCT 'missing_demographics', 'HRIS', employee_id,
       CASE WHEN TRIM(COALESCE(sex, '')) = '' THEN 'sex is blank'
            ELSE 'race_ethnicity is blank' END
FROM raw_hris
WHERE TRIM(COALESCE(sex, '')) = ''
   OR TRIM(COALESCE(race_ethnicity, '')) = '';

-- ---------------------------------------------------------------------
-- Check 3: job titles that do not map to an EEO-1 category
-- ---------------------------------------------------------------------
INSERT INTO exceptions
SELECT DISTINCT 'unmapped_job_title', 'HRIS', h.employee_id,
       'title "' || h.job_title || '" not in job_title_map'
FROM raw_hris h
LEFT JOIN job_title_map m ON m.job_title = h.job_title
WHERE m.job_title IS NULL;

-- ---------------------------------------------------------------------
-- Check 4: hire dates that are malformed or after the snapshot date
--   date() returns NULL for impossible dates such as 2024-13-40.
-- ---------------------------------------------------------------------
INSERT INTO exceptions
SELECT DISTINCT 'invalid_hire_date', 'HRIS', employee_id,
       'hire_date "' || hire_date || '" is ' ||
       CASE WHEN date(hire_date) IS NULL OR date(hire_date) <> hire_date
            THEN 'malformed' ELSE 'after snapshot date' END
FROM raw_hris
WHERE date(hire_date) IS NULL
   OR date(hire_date) <> hire_date
   OR hire_date > (SELECT snapshot_date FROM params);

-- ---------------------------------------------------------------------
-- Check 5: applicants marked Hired in ATS with no HRIS record
-- ---------------------------------------------------------------------
INSERT INTO exceptions
SELECT 'ats_hire_missing_in_hris', 'HRIS vs ATS', a.employee_id,
       'applicant ' || a.applicant_id || ' hired but employee not in HRIS'
FROM raw_ats a
LEFT JOIN (SELECT DISTINCT employee_id FROM raw_hris) h
       ON h.employee_id = a.employee_id
WHERE a.disposition = 'Hired'
  AND h.employee_id IS NULL;

-- ---------------------------------------------------------------------
-- Check 6: HRIS hires inside the ATS window with no applicant record
-- ---------------------------------------------------------------------
INSERT INTO exceptions
SELECT DISTINCT 'hris_hire_missing_in_ats', 'HRIS vs ATS', h.employee_id,
       'hired ' || h.hire_date || ' with no applicant record'
FROM raw_hris h
LEFT JOIN raw_ats a
       ON a.employee_id = h.employee_id AND a.disposition = 'Hired'
WHERE date(h.hire_date) = h.hire_date
  AND h.hire_date BETWEEN (SELECT ats_start FROM params)
                      AND (SELECT snapshot_date FROM params)
  AND a.employee_id IS NULL;

-- ---------------------------------------------------------------------
-- Check 7: sex or race recorded differently in ATS and HRIS
--   Only compared when both systems have a disclosed value.
-- ---------------------------------------------------------------------
INSERT INTO exceptions
SELECT DISTINCT 'demographic_mismatch', 'HRIS vs ATS', h.employee_id,
       CASE WHEN h.sex <> a.sex
            THEN 'sex: HRIS=' || h.sex || ', ATS=' || a.sex
            ELSE 'race: HRIS=' || h.race_ethnicity || ', ATS=' || a.race_ethnicity END
FROM raw_hris h
JOIN raw_ats a ON a.employee_id = h.employee_id AND a.disposition = 'Hired'
WHERE (TRIM(h.sex) <> '' AND a.sex <> 'Not disclosed' AND h.sex <> a.sex)
   OR (TRIM(h.race_ethnicity) <> '' AND a.race_ethnicity <> 'Not disclosed'
       AND h.race_ethnicity <> a.race_ethnicity);
