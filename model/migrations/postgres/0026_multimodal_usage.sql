-- Disjoint audio input dimensions in the original per-call cost ledger.
-- No historical cost/token reconstruction; old non-audio calls retain zero
-- audio dimensions and NULL price snapshots. No supplier activation here.
ALTER TABLE public.model_usage_records
    ADD COLUMN audio_input_tokens INTEGER NOT NULL DEFAULT 0 CHECK(audio_input_tokens>=0),
    ADD COLUMN audio_cache_read_input_tokens INTEGER NOT NULL DEFAULT 0 CHECK(audio_cache_read_input_tokens>=0),
    ADD COLUMN audio_input_price_per_1m DOUBLE PRECISION,
    ADD COLUMN audio_cache_read_price_per_1m DOUBLE PRECISION;
