-- 1. City context: correlation uses natural-log ZHVI, as in the notebook.
SELECT study_area, count(*) AS zcta_count,
       avg(zhvi) AS mean_zhvi,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY zhvi) AS median_zhvi,
       avg(walkability_score) AS mean_walkability,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY walkability_score) AS median_walkability,
       count(*) FILTER (WHERE is_walkable_and_affordable) AS flagged_zctas,
       (count(*) FILTER (WHERE is_walkable_and_affordable))::double precision / NULLIF(count(*), 0) AS flagged_share,
       corr(walkability_score, log_zhvi) AS score_log_zhvi_correlation
FROM public.vw_analysis_features
GROUP BY study_area ORDER BY study_area;

-- 2. The original GLOBAL-sample median screen, enriched by city-relative ranks.
-- Rank 1 is highest score / most expensive housing; percent-ranks are 0–1.
SELECT study_area, zcta, zillow_city, zhvi, walkability_score,
       walkability_rank, housing_value_rank,
       walkability_percent_rank, housing_value_percent_rank
FROM public.vw_city_rankings
WHERE is_walkable_and_affordable
ORDER BY study_area, walkability_score DESC, zcta;

-- 3. Supplemental city-mean comparison, NOT the original affordability flag.
SELECT study_area, zcta, zhvi, city_mean_zhvi, zhvi_minus_city_mean,
       walkability_score, city_mean_walkability, walkability_minus_city_mean,
       walkability_percent_rank, housing_value_percent_rank, is_walkable_and_affordable
FROM public.vw_city_rankings
WHERE walkability_minus_city_mean > 0 AND zhvi_minus_city_mean < 0
ORDER BY study_area, walkability_minus_city_mean DESC, zcta;

-- 4. Missing records stay visible because period predicates are in JOIN ... ON.
-- Nullable estimates are distinct from absent records. Required percentage and
-- ZHVI fields cannot be NULL under schema.sql; list the nullable required fields.
-- Keep this query aligned with database.SOURCE_AUDIT_QUERY.
WITH audited AS (
    SELECT g.zcta, g.study_area,
           h.zcta IS NOT NULL AS housing_present,
           a.zcta IS NOT NULL AS acs_present,
           concat_ws(', ',
               CASE WHEN h.zcta IS NOT NULL AND h.zhvi IS NULL THEN 'zhvi' END,
               CASE WHEN a.zcta IS NOT NULL AND a.median_income IS NULL THEN 'median_income' END,
               CASE WHEN a.zcta IS NOT NULL AND a.median_rent IS NULL THEN 'median_rent' END,
               CASE WHEN a.zcta IS NOT NULL AND a.median_home_value IS NULL THEN 'median_home_value' END,
               CASE WHEN a.zcta IS NOT NULL AND a.commute_minutes IS NULL THEN 'commute_minutes' END,
               CASE WHEN a.zcta IS NOT NULL AND a.population IS NULL THEN 'population' END
           ) AS missing_required_fields,
           f.zcta IS NOT NULL AS included_in_analysis
    FROM public.dim_geography g
    LEFT JOIN public.fact_housing h ON h.zcta=g.zcta AND h.observation_date=DATE '2025-03-31'
    LEFT JOIN public.fact_acs a ON a.zcta=g.zcta AND a.acs_year=2022
    LEFT JOIN public.vw_analysis_features f ON f.zcta=g.zcta
)
SELECT zcta, study_area, housing_present, acs_present, missing_required_fields,
       included_in_analysis,
       CASE WHEN NOT housing_present THEN 'missing_housing_record'
            WHEN NOT acs_present THEN 'missing_acs_record'
            WHEN missing_required_fields <> '' THEN 'missing_required_estimate'
            WHEN NOT included_in_analysis THEN 'excluded_by_rules'
            ELSE 'included' END AS status
FROM audited ORDER BY study_area, zcta;