SET LOCAL TIME ZONE 'UTC';

-- The dedicated Tracking role needs its non-secret runtime switch and the
-- existing cross-run session stop flag.  Keep the
-- policy independent of role creation order, as earlier runtime policies do.
DROP POLICY IF EXISTS noteai_xhs_tracking_config_read_v1
    ON system_settings;
CREATE POLICY noteai_xhs_tracking_config_read_v1
    ON system_settings
FOR SELECT TO PUBLIC
USING (
    current_user = 'noteai_xhs_tracking'
    AND is_secret = 0
    AND key IN ('crawler_config', 'xhs_collection_safety')
);
