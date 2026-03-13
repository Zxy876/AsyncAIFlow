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
    error_message VARCHAR(512) NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    INDEX idx_action_workflow (workflow_id),
    INDEX idx_action_status (status),
    INDEX idx_action_type (type)
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
    last_heartbeat DATETIME NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
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