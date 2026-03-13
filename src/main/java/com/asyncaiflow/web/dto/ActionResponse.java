package com.asyncaiflow.web.dto;

import java.time.LocalDateTime;
import java.util.List;

public record ActionResponse(
        Long id,
        Long workflowId,
        String type,
        String status,
        String workerId,
        Integer retryCount,
        String payload,
        String errorMessage,
        List<Long> upstreamActionIds,
        LocalDateTime createdAt,
        LocalDateTime updatedAt
) {
}