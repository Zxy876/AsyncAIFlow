package com.asyncaiflow.worker.gpt.validation;

import java.util.Optional;

public class ActionSchemaResolver {

    private final String schemaBasePath;

    public ActionSchemaResolver(String schemaBasePath) {
        this.schemaBasePath = normalizeBasePath(schemaBasePath);
    }

    public Optional<SchemaMapping> resolve(String actionType) {
        if ("design_solution".equals(actionType)) {
            return Optional.of(new SchemaMapping(
                    schemaPath("design_solution.payload.schema.json"),
                    schemaPath("design_solution.result.schema.json")
            ));
        }

        if ("review_code".equals(actionType)) {
            return Optional.of(new SchemaMapping(
                    schemaPath("review_code.payload.schema.json"),
                    schemaPath("review_code.result.schema.json")
            ));
        }

        if ("generate_explanation".equals(actionType)) {
            return Optional.of(new SchemaMapping(
                    schemaPath("generate_explanation.payload.schema.json"),
                    schemaPath("generate_explanation.result.schema.json")
            ));
        }

        if ("search_code".equals(actionType)) {
            return Optional.of(new SchemaMapping(
                    schemaPath("search_code.payload.schema.json"),
                    schemaPath("search_code.result.schema.json")
            ));
        }

        if ("read_file".equals(actionType)) {
            return Optional.of(new SchemaMapping(
                    schemaPath("read_file.payload.schema.json"),
                    schemaPath("read_file.result.schema.json")
            ));
        }

        return Optional.empty();
    }

    private String schemaPath(String fileName) {
        return schemaBasePath + "/" + fileName;
    }

    private static String normalizeBasePath(String value) {
        String fallback = "schemas/v1";
        if (value == null || value.isBlank()) {
            return fallback;
        }

        String normalized = value.trim();
        while (normalized.startsWith("/")) {
            normalized = normalized.substring(1);
        }
        while (normalized.endsWith("/")) {
            normalized = normalized.substring(0, normalized.length() - 1);
        }
        return normalized.isBlank() ? fallback : normalized;
    }

    public record SchemaMapping(String payloadSchemaPath, String resultSchemaPath) {
    }
}
