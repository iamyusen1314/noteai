-- Test-database guard only. The production candidate DDL is read from the
-- existing scripts/postgres path by the isolated PG16 test; no duplicate body.
DO $$ BEGIN
    IF current_database() !~ '^noteai_item34_test_[0-9a-f]+$' THEN
        RAISE EXCEPTION 'isolated Item34 proposal database required';
    END IF;
END $$;
