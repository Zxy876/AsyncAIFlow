CREATE TABLE IF NOT EXISTS workflow (
    id BIGINT PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    description VARCHAR(512),
    status VARCHAR(32) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS action (
    id BIGINT PRIMARY KEY,
    workflow_id BIGINT NOT NULL,
    type VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    payload CLOB,
    worker_id VARCHAR(64),
    retry_count INT NOT NULL DEFAULT 0,
    error_message VARCHAR(512),
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS action_dependency (
    id BIGINT PRIMARY KEY,
    workflow_id BIGINT NOT NULL,
    upstream_action_id BIGINT NOT NULL,
    downstream_action_id BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS worker (
    id VARCHAR(64) PRIMARY KEY,
    capabilities CLOB NOT NULL,
    status VARCHAR(32) NOT NULL,
    last_heartbeat TIMESTAMP,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS action_log (
    id BIGINT PRIMARY KEY,
    action_id BIGINT NOT NULL,
    worker_id VARCHAR(64) NOT NULL,
    result CLOB,
    status VARCHAR(32) NOT NULL,
    created_at TIMESTAMP NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_action_dependency
    ON action_dependency (upstream_action_id, downstream_action_id);

CREATE INDEX IF NOT EXISTS idx_action_workflow ON action (workflow_id);
CREATE INDEX IF NOT EXISTS idx_action_status ON action (status);
CREATE INDEX IF NOT EXISTS idx_action_type ON action (type);
CREATE INDEX IF NOT EXISTS idx_dependency_upstream ON action_dependency (upstream_action_id);
CREATE INDEX IF NOT EXISTS idx_dependency_downstream ON action_dependency (downstream_action_id);
CREATE INDEX IF NOT EXISTS idx_action_log_action ON action_log (action_id);