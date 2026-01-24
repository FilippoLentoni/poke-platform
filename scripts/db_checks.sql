-- Ops sanity checks for the daily pipeline.
-- Run in psql against the poke database.

-- Universe updater
-- Expect: card_metadata counts non-zero after seeding.
SELECT COUNT(*) AS card_metadata_count FROM card_metadata;
SELECT MAX(snapshot_date) AS latest_card_metadata_snapshot FROM card_metadata;

-- Price extractor
-- Expect: max snapshot_date is today or recent; counts > 0.
SELECT MAX(snapshot_date) AS latest_tcgplayer_snapshot
FROM tcgplayer_price_snapshot;
SELECT COUNT(*) AS tcgplayer_today_count
FROM tcgplayer_price_snapshot
WHERE snapshot_date = CURRENT_DATE;

SELECT MAX(snapshot_date) AS latest_cardmarket_snapshot
FROM cardmarket_price_snapshot;
SELECT COUNT(*) AS cardmarket_today_count
FROM cardmarket_price_snapshot
WHERE snapshot_date = CURRENT_DATE;

-- Strategy runner
-- Expect: valuation_daily rows today.
SELECT COUNT(*) AS valuation_today_count
FROM valuation_daily
WHERE val_date = CURRENT_DATE;
