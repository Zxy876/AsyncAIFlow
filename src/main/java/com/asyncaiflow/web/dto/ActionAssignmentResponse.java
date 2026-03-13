package com.asyncaiflow.web.dto;

public record ActionAssignmentResponse(
        Long actionId,
        Long workflowId,
        String type,
        String payload,
        Integer retryCount
) {
}