package com.asyncaiflow.web.dto;

import io.swagger.v3.oas.annotations.media.Schema;

@Schema(description = "Uploaded file metadata")
public record FileUploadResponse(
        @Schema(description = "Original file name", example = "old-jacket-scan.obj")
        String originalFileName,
        @Schema(description = "Saved file absolute path used as rawScanUrl", example = "/tmp/asyncaiflow_uploads/20260322_abc123.obj")
        String rawScanUrl,
        @Schema(description = "Saved file size in bytes", example = "16384")
        long size
) {
}
