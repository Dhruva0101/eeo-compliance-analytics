-- =====================================================================
-- 02_clean.sql  --  Resolve exceptions and build the clean workforce
--
-- Resolution rules (documented in README):
--   * Duplicate rows       -> keep one row per employee_id
--   * Alias job titles     -> remap via title_aliases, then job_title_map
--   * Invalid hire dates   -> excluded; routed to HR for correction
--   * Missing demographics -> kept, reported as "Not reported"
--   * ATS/HRIS mismatches  -> HRIS is the system of record
-- =====================================================================

DROP TABLE IF EXISTS clean_hris;
CREATE TABLE clean_hris AS
WITH dedup AS (
    SELECT DISTINCT employee_id, job_title, hire_date, termination_date,
                    status, sex, race_ethnicity
    FROM raw_hris
),
titled AS (
    SELECT d.*,
           COALESCE(al.job_title, d.job_title) AS clean_title
    FROM dedup d
    LEFT JOIN title_aliases al ON al.raw_title = d.job_title
)
SELECT t.employee_id,
       t.clean_title                       AS job_title,
       m.eeo1_category,
       t.hire_date,
       NULLIF(t.termination_date, '')      AS termination_date,
       t.status,
       COALESCE(NULLIF(TRIM(t.sex), ''), 'Not reported')            AS sex,
       COALESCE(NULLIF(TRIM(t.race_ethnicity), ''), 'Not reported') AS race_ethnicity,
       CASE WHEN date(t.hire_date) IS NULL
              OR date(t.hire_date) <> t.hire_date
              OR t.hire_date > (SELECT snapshot_date FROM params)
            THEN 1 ELSE 0 END              AS invalid_hire_date
FROM titled t
LEFT JOIN job_title_map m ON m.job_title = t.clean_title;

-- Workforce on the snapshot date: hired on/before it, not yet terminated.
DROP VIEW IF EXISTS snapshot_workforce;
CREATE VIEW snapshot_workforce AS
SELECT *
FROM clean_hris
WHERE invalid_hire_date = 0
  AND hire_date <= (SELECT snapshot_date FROM params)
  AND (termination_date IS NULL
       OR termination_date > (SELECT snapshot_date FROM params));
