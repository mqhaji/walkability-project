-- Fixed study periods must match config.py. Ordinary views reflect source
-- updates immediately; the caller controls the installation transaction.
CREATE OR REPLACE VIEW public.vw_analysis_features AS
WITH study_period AS (
    SELECT DATE '2025-03-31' AS observation_date, 2022::smallint AS acs_year
), joined_source AS (
    SELECT g.zcta, g.zillow_city, g.zillow_county, g.state, g.study_area,
           h.observation_date, h.zhvi,
           a.median_income, a.median_rent, a.median_home_value,
           a.percent_car, a.percent_public_transit, a.percent_walk, a.percent_bike,
           a.commute_minutes, a.percent_renter, a.percent_owner,
           a.percent_bachelors_plus, a.population, a.acs_year
    FROM public.dim_geography g
    CROSS JOIN study_period p
    INNER JOIN public.fact_housing h
        ON h.zcta = g.zcta AND h.observation_date = p.observation_date
    INNER JOIN public.fact_acs a ON a.zcta = g.zcta AND a.acs_year = p.acs_year
), eligible_source AS (
    SELECT * FROM joined_source
    WHERE zhvi > 0 AND zhvi < 'Infinity'::double precision
      AND median_income > 0 AND median_income < 'Infinity'::double precision
      AND median_rent > 0 AND median_rent < 'Infinity'::double precision
      -- Preserve the reference's complete-case requirement even though home
      -- value is used only by a sensitivity model. Never impute NULL to zero.
      AND median_home_value > '-Infinity'::double precision
      AND median_home_value < 'Infinity'::double precision
      AND population > 0
      AND commute_minutes >= 0 AND commute_minutes < 'Infinity'::double precision
      AND percent_car BETWEEN 0 AND 100
      AND percent_public_transit BETWEEN 0 AND 100
      AND percent_walk BETWEEN 0 AND 100
      AND percent_bike BETWEEN 0 AND 100
      AND percent_renter BETWEEN 0 AND 100
      AND percent_owner BETWEEN 0 AND 100
      AND percent_bachelors_plus BETWEEN 0 AND 100
), derived_features AS (
    SELECT e.*,
        CASE WHEN zhvi > 0 AND zhvi < 'Infinity'::double precision THEN ln(zhvi) END AS log_zhvi,
        CASE WHEN median_income > 0 AND median_income < 'Infinity'::double precision THEN ln(median_income) END AS log_median_income,
        CASE WHEN population > 0 THEN ln(population::double precision) END AS log_population,
        median_income / NULLIF(median_rent * 12.0::double precision, 0.0) AS income_to_rent,
        median_home_value / NULLIF(median_income, 0.0) AS home_value_to_income,
        percent_walk / 100.0::double precision AS walk_share,
        percent_public_transit / 100.0::double precision AS transit_share,
        percent_bike / 100.0::double precision AS bike_share,
        percent_car / 100.0::double precision AS car_share,
        percent_renter / 100.0::double precision AS rent_share,
        percent_owner / 100.0::double precision AS owner_share,
        percent_bachelors_plus / 100.0::double precision AS college_grad_share,
        population::double precision / 1000.0::double precision AS population_k,
        commute_minutes AS commute_min
    FROM eligible_source e
), scored AS (
    SELECT d.*, walk_share * 0.5::double precision
        + transit_share * 0.4::double precision
        + bike_share * 0.1::double precision AS walkability_score
    FROM derived_features d
), sample_thresholds AS (
    -- GLOBAL medians over eligible observations, not within-city medians.
    SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY zhvi) AS median_zhvi,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY walkability_score) AS median_walkability
    FROM scored
)
SELECT s.zcta, s.zillow_city, s.zillow_county, s.state, s.study_area,
       s.observation_date, s.zhvi, s.median_income, s.median_rent, s.median_home_value,
       s.percent_car, s.percent_public_transit, s.percent_walk, s.percent_bike,
       s.commute_minutes, s.percent_renter, s.percent_owner, s.percent_bachelors_plus,
       s.population, s.log_zhvi, s.log_median_income, s.log_population,
       s.income_to_rent, s.home_value_to_income,
       s.walk_share, s.transit_share, s.bike_share, s.car_share,
       s.rent_share, s.owner_share, s.college_grad_share, s.population_k,
       s.commute_min, s.walkability_score,
       (s.zhvi < t.median_zhvi AND s.walkability_score > t.median_walkability) AS is_walkable_and_affordable,
       s.acs_year
FROM scored s CROSS JOIN sample_thresholds t;

CREATE OR REPLACE VIEW public.vw_city_rankings AS
WITH ranked AS (
    SELECT zcta, study_area, zillow_city, zillow_county, state,
           observation_date, acs_year, zhvi, walkability_score, is_walkable_and_affordable,
           -- Do not break ties in statistical ranks. Higher percent-rank means
           -- higher score / more expensive housing, not better affordability.
           rank() OVER (PARTITION BY study_area ORDER BY walkability_score DESC) AS walkability_rank,
           rank() OVER (PARTITION BY study_area ORDER BY zhvi DESC) AS housing_value_rank,
           percent_rank() OVER (PARTITION BY study_area ORDER BY walkability_score) AS walkability_percent_rank,
           percent_rank() OVER (PARTITION BY study_area ORDER BY zhvi) AS housing_value_percent_rank,
           avg(walkability_score) OVER (PARTITION BY study_area) AS city_mean_walkability,
           avg(zhvi) OVER (PARTITION BY study_area) AS city_mean_zhvi,
           -- Separate deterministic orders select exactly five when available.
           row_number() OVER (PARTITION BY study_area ORDER BY walkability_score DESC, zcta) AS walkability_top_order,
           row_number() OVER (PARTITION BY study_area ORDER BY walkability_score, zcta) AS walkability_bottom_order
    FROM public.vw_analysis_features
)
SELECT zcta, study_area, zillow_city, zillow_county, state,
       observation_date, acs_year, zhvi, walkability_score, is_walkable_and_affordable,
       walkability_rank, housing_value_rank, walkability_percent_rank, housing_value_percent_rank,
       city_mean_walkability, city_mean_zhvi,
       walkability_score - city_mean_walkability AS walkability_minus_city_mean,
       zhvi - city_mean_zhvi AS zhvi_minus_city_mean,
       walkability_top_order, walkability_bottom_order
FROM ranked;