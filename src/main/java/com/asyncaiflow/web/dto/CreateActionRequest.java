package com.asyncaiflow.web.dto;

import java.util.List;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

public record CreateActionRequest(
        @NotNull(message = "must not be null") Long workflowId,
        @NotBlank(message = "must not be blank") String type,
        String payload,
        List<Long> upstreamActionIds
) {
}