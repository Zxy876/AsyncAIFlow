package com.asyncaiflow.worker.gpt;

import java.io.IOException;
import java.util.Set;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import com.asyncaiflow.worker.gpt.validation.ActionSchemaValidator;
import com.asyncaiflow.worker.gpt.validation.SchemaValidationMode;
import com.asyncaiflow.worker.sdk.WorkerActionHandler;
import com.asyncaiflow.worker.sdk.WorkerExecutionResult;
import com.asyncaiflow.worker.sdk.model.ActionAssignment;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

public class GptWorkerActionHandler implements WorkerActionHandler {

    private static final Logger LOGGER = LoggerFactory.getLogger(GptWorkerActionHandler.class);

    private static final Set<String> SUPPORTED_ACTION_TYPES = Set.of(
            "design_solution",
            "review_code",
            "generate_explanation"
    );

    private final ObjectMapper objectMapper;
    private final OpenAiCompatibleLlmClient llmClient;
    private final ActionSchemaValidator schemaValidator;
    private final SchemaValidationMode validationMode;

    public GptWorkerActionHandler(
            ObjectMapper objectMapper,
            OpenAiCompatibleLlmClient llmClient,
            ActionSchemaValidator schemaValidator,
            SchemaValidationMode validationMode) {
        this.objectMapper = objectMapper;
        this.llmClient = llmClient;
        this.schemaValidator = schemaValidator;
        this.validationMode = validationMode == null ? SchemaValidationMode.WARN : validationMode;
    }

    @Override
    public WorkerExecutionResult execute(ActionAssignment assignment) {
        if (!SUPPORTED_ACTION_TYPES.contains(assignment.type())) {
            return WorkerExecutionResult.failed(
                    "unsupported action type",
                    "GPT worker supports only design_solution, review_code and generate_explanation"
            );
        }

        PayloadParseResult payloadParseResult = parsePayload(assignment.payload());
        if (!payloadParseResult.parseable()) {
            LOGGER.warn("schema_validation phase=payload_parse mode={} actionId={} actionType={} errors={}",
                    validationMode, assignment.actionId(), assignment.type(), payloadParseResult.errorMessage());
            return WorkerExecutionResult.failed("invalid payload json", payloadParseResult.errorMessage());
        }

        JsonNode payload = payloadParseResult.payloadNode();
        if (validationMode != SchemaValidationMode.OFF) {
            ActionSchemaValidator.ValidationReport payloadValidation =
                schemaValidator.validatePayload(assignment.type(), payload);
            WorkerExecutionResult payloadGateResult = handleValidationGate(
                "payload",
                assignment,
                payloadValidation,
                "payload schema validation failed");
            if (payloadGateResult != null) {
            return payloadGateResult;
            }
        }

        Prompt prompt = buildPrompt(assignment.type(), payload);
        try {
            String completion = llmClient.complete(prompt.systemPrompt(), prompt.userPrompt());
            String resultJson = buildResultJson(assignment, completion);

                if (validationMode != SchemaValidationMode.OFF) {
                ActionSchemaValidator.ValidationReport resultValidation =
                    schemaValidator.validateResult(assignment.type(), resultJson);
                if (!resultValidation.parseable()) {
                    LOGGER.warn("schema_validation phase=result_parse mode={} actionId={} actionType={} errors={}",
                        validationMode, assignment.actionId(), assignment.type(), resultValidation.errorSummary());
                    return WorkerExecutionResult.failed("invalid result json", resultValidation.errorSummary());
                }

                WorkerExecutionResult resultGateResult = handleValidationGate(
                    "result",
                    assignment,
                    resultValidation,
                    "result schema validation failed");
                if (resultGateResult != null) {
                    return resultGateResult;
                }
            }

            LOGGER.info("gpt_execution_succeeded actionId={} actionType={} summary={}",
                    assignment.actionId(), assignment.type(), summarize(completion, 160));

            return WorkerExecutionResult.succeeded(resultJson);
        } catch (RuntimeException | IOException exception) {
            LOGGER.warn("GPT worker failed to execute actionId={} type={}",
                    assignment.actionId(), assignment.type(), exception);
            return WorkerExecutionResult.failed("gpt execution failed", exception.getMessage());
        }
    }

    private WorkerExecutionResult handleValidationGate(
            String phase,
            ActionAssignment assignment,
            ActionSchemaValidator.ValidationReport report,
            String strictFailureResult) {
        if (validationMode == SchemaValidationMode.OFF || report.skipped() || report.valid()) {
            return null;
        }

        String schemaPath = report.schemaPath() == null ? "n/a" : report.schemaPath();
        String errors = report.errorSummary();

        if (validationMode == SchemaValidationMode.STRICT) {
            LOGGER.warn("schema_validation phase={} mode={} actionId={} actionType={} schemaPath={} strict=true errors={}",
                    phase, validationMode, assignment.actionId(), assignment.type(), schemaPath, errors);
            return WorkerExecutionResult.failed(strictFailureResult, errors);
        }

        LOGGER.warn("schema_validation phase={} mode={} actionId={} actionType={} schemaPath={} strict=false errors={}",
                phase, validationMode, assignment.actionId(), assignment.type(), schemaPath, errors);
        return null;
    }

    private Prompt buildPrompt(String actionType, JsonNode payload) {
        return switch (actionType) {
            case "review_code" -> buildReviewCodePrompt(payload);
            case "generate_explanation" -> buildGenerateExplanationPrompt(payload);
            default -> buildDesignSolutionPrompt(payload);
        };
    }

    private Prompt buildDesignSolutionPrompt(JsonNode payload) {
        String issue = firstNonBlank(
                payload.path("issue").asText(null),
                payload.path("problem").asText(null),
                payload.path("title").asText(null),
                "No issue provided"
        );

        String context = payload.path("context").asText("");
        String constraints = payload.path("constraints").asText("");

        String systemPrompt = "You are a pragmatic senior software architect. " +
                "Return implementation-ready solution guidance with trade-offs and risk notes.";

        String userPrompt = """
            Action: design_solution
            Issue:
            %s

            Context:
            %s

            Constraints:
            %s

            Return sections: Proposed Design, Step Plan, Risks.
            """.formatted(issue, context, constraints);

        return new Prompt(systemPrompt, userPrompt);
    }

    private Prompt buildReviewCodePrompt(JsonNode payload) {
        String reviewFocus = firstNonBlank(
                payload.path("focus").asText(null),
                payload.path("reviewFocus").asText(null),
                "correctness, reliability and maintainability"
        );

        String diff = payload.path("diff").asText("");
        String code = payload.path("code").asText("");
        String context = payload.path("context").asText("");

        String systemPrompt = "You are a strict senior reviewer. " +
                "Find defects first, then provide concrete and minimal fixes.";

        String userPrompt = """
            Action: review_code
            Focus:
            %s

            Context:
            %s

            Diff:
            %s

            Code:
            %s

            Return sections: Findings, Suggested Fixes, Residual Risks.
            """.formatted(reviewFocus, context, diff, code);

        return new Prompt(systemPrompt, userPrompt);
    }

    private Prompt buildGenerateExplanationPrompt(JsonNode payload) {
        String issue = firstNonBlank(
                payload.path("issue").asText(null),
                payload.path("problem").asText(null),
                payload.path("title").asText(null),
                "No issue provided"
        );
        String repoContext = firstNonBlank(
                payload.path("repo_context").asText(null),
                payload.path("context").asText(null),
                ""
        );
        String file = payload.path("file").asText("");
        String module = payload.path("module").asText("");
        String gatheredContext = renderPayloadValue(payload.get("gathered_context"));

        String systemPrompt = "You are a pragmatic senior engineer explaining how a codebase works to another engineer. " +
                "Stay concrete, separate confirmed facts from inference, and explicitly call out missing context.";

        String userPrompt = """
            Action: generate_explanation
            Issue:
            %s

            Repo context:
            %s

            File:
            %s

            Module:
            %s

            Gathered context:
            %s

            Return sections: Summary, Interaction Flow, Key Components, Open Questions.
            """.formatted(
            issue,
            promptValue(repoContext),
            promptValue(file),
            promptValue(module),
            promptValue(gatheredContext));

        return new Prompt(systemPrompt, userPrompt);
    }

    private String buildResultJson(ActionAssignment assignment, String completion) throws IOException {
        return switch (assignment.type()) {
            case "review_code" -> buildReviewCodeResultJson(completion);
            case "generate_explanation" -> buildGenerateExplanationResultJson(completion);
            default -> buildDesignSolutionResultJson(completion);
        };
    }

    private String buildDesignSolutionResultJson(String completion) throws IOException {
        ObjectNode result = objectMapper.createObjectNode();
        result.put("schemaVersion", "v1");
        result.put("worker", "gpt-worker");
        result.put("model", llmClient.modelName());
        result.put("summary", summarize(completion, 220));
        result.put("content", completion);
        result.put("confidence", 0.65D);
        return objectMapper.writeValueAsString(result);
    }

    private String buildReviewCodeResultJson(String completion) throws IOException {
        ObjectNode result = objectMapper.createObjectNode();
        result.put("schemaVersion", "v1");
        result.put("worker", "gpt-worker");
        result.put("model", llmClient.modelName());

        ArrayNode findings = result.putArray("findings");
        ObjectNode finding = findings.addObject();
        finding.put("severity", "major");
        finding.put("title", "LLM review summary");
        finding.put("detail", summarize(completion, 900));

        result.put("content", completion);
        result.put("confidence", 0.62D);
        return objectMapper.writeValueAsString(result);
    }

    private String buildGenerateExplanationResultJson(String completion) throws IOException {
        ObjectNode result = objectMapper.createObjectNode();
        result.put("schemaVersion", "v1");
        result.put("worker", "gpt-worker");
        result.put("model", llmClient.modelName());
        result.put("summary", summarize(completion, 220));
        result.put("content", completion);
        result.put("confidence", 0.71D);
        return objectMapper.writeValueAsString(result);
    }

    private static String summarize(String content, int maxLength) {
        if (content == null || content.isBlank()) {
            return "No summary available";
        }

        String normalized = content.replace('\n', ' ').trim();
        if (normalized.length() <= maxLength) {
            return normalized;
        }
        return normalized.substring(0, Math.max(1, maxLength)) + "...";
    }

    private PayloadParseResult parsePayload(String payload) {
        if (payload == null || payload.isBlank()) {
            return PayloadParseResult.success(objectMapper.createObjectNode());
        }

        try {
            return PayloadParseResult.success(objectMapper.readTree(payload));
        } catch (IOException exception) {
            return PayloadParseResult.failure("payload JSON parse failed: " + exception.getMessage());
        }
    }

    private static String firstNonBlank(String... candidates) {
        for (String candidate : candidates) {
            if (candidate != null && !candidate.isBlank()) {
                return candidate;
            }
        }
        return "";
    }

    private String renderPayloadValue(JsonNode node) {
        if (node == null || node.isMissingNode() || node.isNull()) {
            return "";
        }
        if (node.isTextual()) {
            return node.asText("");
        }
        try {
            return objectMapper.writerWithDefaultPrettyPrinter().writeValueAsString(node);
        } catch (IOException exception) {
            return node.toString();
        }
    }

    private String promptValue(String value) {
        return (value == null || value.isBlank()) ? "n/a" : value;
    }

    private record PayloadParseResult(boolean parseable, JsonNode payloadNode, String errorMessage) {

        static PayloadParseResult success(JsonNode payloadNode) {
            return new PayloadParseResult(true, payloadNode, null);
        }

        static PayloadParseResult failure(String errorMessage) {
            return new PayloadParseResult(false, null, errorMessage);
        }
    }

    private record Prompt(String systemPrompt, String userPrompt) {
    }
}
