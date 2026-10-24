-- Stage 1: clean source observations, not the 248-row analytical sample.
-- Run against a dedicated project database. No destructive DROP/TRUNCATE.
-- CREATE IF NOT EXISTS supports repeated setup, not automatic schema migration.

CREATE TABLE IF NOT EXISTS dim_geography (
    zcta text PRIMARY KEY CHECK (zcta ~ '^[0-9]{5}$'),
    study_area text NOT NULL,
    zillow_city text NOT NULL CHECK (btrim(zillow_city) <> ''),
    zillow_county text NOT NULL,
    state text NOT NULL,
    CONSTRAINT valid_study_assignment CHECK (
        (study_area = 'New York City' AND state = 'NY' AND zillow_county IN (
            'Bronx County', 'Kings County', 'New York County',
            'Queens County', 'Richmond County'
        ))
        OR (study_area = 'Washington DC' AND state = 'DC' AND zillow_city = 'Washington')
        OR (study_area = 'Chicago' AND state = 'IL'
            AND zillow_county = 'Cook County' AND zillow_city = 'Chicago')
    )
);

-- These are statistical estimates, not currency ledger balances. Double
-- precision preserves the notebook's numeric representation without rounding
-- Zillow observations to two decimal places. Explicit finite bounds also reject
-- PostgreSQL's NaN and Infinity numeric values.
CREATE TABLE IF NOT EXISTS fact_housing (
    zcta text NOT NULL REFERENCES dim_geography (zcta),
    observation_date date NOT NULL CHECK (isfinite(observation_date)),
    zhvi double precision NOT NULL CHECK (zhvi > 0 AND zhvi < 'Infinity'::double precision),
    PRIMARY KEY (zcta, observation_date)
);

-- acs_year identifies the END year of an ACS five-year estimate.
-- Percentages retain the source's 0–100 units. SQL analytical views will convert
-- them to 0–1 shares. NULL means unavailable, never an imputed zero.
CREATE TABLE IF NOT EXISTS fact_acs (
    zcta text NOT NULL REFERENCES dim_geography (zcta),
    acs_year smallint NOT NULL CHECK (acs_year >= 2009),
    median_income double precision CHECK (median_income > 0 AND median_income < 'Infinity'::double precision),
    median_rent double precision CHECK (median_rent > 0 AND median_rent < 'Infinity'::double precision),
    median_home_value double precision CHECK (median_home_value > 0 AND median_home_value < 'Infinity'::double precision),
    percent_car double precision NOT NULL CHECK (percent_car BETWEEN 0 AND 100),
    percent_public_transit double precision NOT NULL CHECK (percent_public_transit BETWEEN 0 AND 100),
    percent_walk double precision NOT NULL CHECK (percent_walk BETWEEN 0 AND 100),
    percent_bike double precision NOT NULL CHECK (percent_bike BETWEEN 0 AND 100),
    commute_minutes double precision CHECK (commute_minutes >= 0 AND commute_minutes < 'Infinity'::double precision),
    percent_renter double precision NOT NULL CHECK (percent_renter BETWEEN 0 AND 100),
    percent_owner double precision NOT NULL CHECK (percent_owner BETWEEN 0 AND 100),
    percent_bachelors_plus double precision NOT NULL CHECK (percent_bachelors_plus BETWEEN 0 AND 100),
    population integer CHECK (population > 0),
    PRIMARY KEY (zcta, acs_year)
);

-- Primary keys already supply the indexes needed for the current joins and
-- upserts. Additional indexes are not justified for approximately 250 rows.