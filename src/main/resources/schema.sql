CREATE TABLE IF NOT EXISTS workflow (
    id BIGINT PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    description VARCHAR(512) NULL,
    status VARCHAR(32) NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS action (
    id BIGINT PRIMARY KEY,
    workflow_id BIGINT NOT NULL,
    type VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    payload TEXT NULL,
    worker_id VARCHAR(64) NULL,
    retry_count INT NOT NULL DEFAULT 0,
    max_retry_count INT NOT NULL DEFAULT 3,
    backoff_seconds INT NOT NULL DEFAULT 5,
    execution_timeout_seconds INT NOT NULL DEFAULT 300,
    lease_expire_at DATETIME NULL,
    next_run_at DATETIME NULL,
    claim_time DATETIME NULL,
    first_renew_time DATETIME NULL,
    last_renew_time DATETIME NULL,
    submit_time DATETIME NULL,
    reclaim_time DATETIME NULL,
    lease_renew_success_count INT NOT NULL DEFAULT 0,
    lease_renew_failure_count INT NOT NULL DEFAULT 0,
    last_lease_renew_at DATETIME NULL,
    execution_started_at DATETIME NULL,
    last_execution_duration_ms BIGINT NULL,
    last_reclaim_reason VARCHAR(64) NULL,
    error_message VARCHAR(512) NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    INDEX idx_action_workflow (workflow_id),
    INDEX idx_action_status (status),
    INDEX idx_action_type (type),
    INDEX idx_action_lease_expire (lease_expire_at),
    INDEX idx_action_next_run (next_run_at)
);

CREATE TABLE IF NOT EXISTS action_dependency (
    id BIGINT PRIMARY KEY,
    workflow_id BIGINT NOT NULL,
    upstream_action_id BIGINT NOT NULL,
    downstream_action_id BIGINT NOT NULL,
    UNIQUE KEY uk_action_dependency (upstream_action_id, downstream_action_id),
    INDEX idx_dependency_upstream (upstream_action_id),
    INDEX idx_dependency_downstream (downstream_action_id)
);

CREATE TABLE IF NOT EXISTS worker (
    id VARCHAR(64) PRIMARY KEY,
    capabilities TEXT NOT NULL,
    status VARCHAR(32) NOT NULL,
    last_heartbeat_at DATETIME NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    INDEX idx_worker_status (status),
    INDEX idx_worker_heartbeat (last_heartbeat_at)
);

CREATE TABLE IF NOT EXISTS action_log (
    id BIGINT PRIMARY KEY,
    action_id BIGINT NOT NULL,
    worker_id VARCHAR(64) NOT NULL,
    result TEXT NULL,
    status VARCHAR(32) NOT NULL,
    created_at DATETIME NOT NULL,
    INDEX idx_action_log_action (action_id)
);

ALTER TABLE action ADD COLUMN IF NOT EXISTS max_retry_count INT NOT NULL DEFAULT 3;
ALTER TABLE action ADD COLUMN IF NOT EXISTS backoff_seconds INT NOT NULL DEFAULT 5;
ALTER TABLE action ADD COLUMN IF NOT EXISTS execution_timeout_seconds INT NOT NULL DEFAULT 300;
ALTER TABLE action ADD COLUMN IF NOT EXISTS lease_expire_at DATETIME NULL;
ALTER TABLE action ADD COLUMN IF NOT EXISTS next_run_at DATETIME NULL;
ALTER TABLE action ADD COLUMN IF NOT EXISTS claim_time DATETIME NULL;
ALTER TABLE action ADD COLUMN IF NOT EXISTS first_renew_time DATETIME NULL;
ALTER TABLE action ADD COLUMN IF NOT EXISTS last_renew_time DATETIME NULL;
ALTER TABLE action ADD COLUMN IF NOT EXISTS submit_time DATETIME NULL;
ALTER TABLE action ADD COLUMN IF NOT EXISTS reclaim_time DATETIME NULL;
ALTER TABLE action ADD COLUMN IF NOT EXISTS lease_renew_success_count INT NOT NULL DEFAULT 0;
ALTER TABLE action ADD COLUMN IF NOT EXISTS lease_renew_failure_count INT NOT NULL DEFAULT 0;
ALTER TABLE action ADD COLUMN IF NOT EXISTS last_lease_renew_at DATETIME NULL;
ALTER TABLE action ADD COLUMN IF NOT EXISTS execution_started_at DATETIME NULL;
ALTER TABLE action ADD COLUMN IF NOT EXISTS last_execution_duration_ms BIGINT NULL;
ALTER TABLE action ADD COLUMN IF NOT EXISTS last_reclaim_reason VARCHAR(64) NULL;

ALTER TABLE worker ADD COLUMN IF NOT EXISTS last_heartbeat_at DATETIME NULL;