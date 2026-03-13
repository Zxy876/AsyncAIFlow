package com.asyncaiflow.domain.enums;

public enum ActionStatus {
    BLOCKED,
    QUEUED,
    RUNNING,
    SUCCEEDED,
    FAILED;

    public boolean isTerminal() {
        return this == SUCCEEDED || this == FAILED;
    }
}