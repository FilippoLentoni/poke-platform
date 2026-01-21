-- Ops sanity checks for the daily pipeline.
-- Run in psql against the poke database.

-- Universe updater
-- Expect: newest run finished, new_sets/new_cards > 0 on first run,
-- tracked_asset + card_metadata counts non-zero after seeding.
SELECT run_id, ts_started, ts_finished, new_sets, new_cards, note
FROM universe_run
ORDER BY ts_started DESC
LIMIT 5;

SELECT COUNT(*) AS tracked_asset_count FROM tracked_asset;
SELECT COUNT(*) AS card_metadata_count FROM card_metadata;

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
-- Expect: recent strategy_run entries and valuation_daily rows today.
SELECT run_id, run_date, strategy_name, strategy_version, inserted_proposals, note
FROM strategy_run
ORDER BY run_date DESC
LIMIT 5;

SELECT COUNT(*) AS valuation_today_count
FROM valuation_daily
WHERE val_date = CURRENT_DATE;

-- Proposals
-- Expect: trade_proposal rows for today and recent timestamps.
SELECT COUNT(*) AS proposals_today_count
FROM trade_proposal
WHERE proposal_date = CURRENT_DATE;

SELECT proposal_id, proposal_date, action, asset_id, target_price, confidence, status, ts_created
FROM trade_proposal
ORDER BY ts_created DESC
LIMIT 10;
