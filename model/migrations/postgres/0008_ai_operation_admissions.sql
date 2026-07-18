CREATE TABLE IF NOT EXISTS ai_operation_admissions (
    operation_id           TEXT NOT NULL PRIMARY KEY
                           REFERENCES ai_operations(id) ON DELETE RESTRICT,
    idempotency_request_id TEXT NOT NULL UNIQUE
                           REFERENCES idempotency_requests(id) ON DELETE RESTRICT,
    created_at             TEXT NOT NULL
);
