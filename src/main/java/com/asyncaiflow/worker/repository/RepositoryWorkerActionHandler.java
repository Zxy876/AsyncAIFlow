package com.asyncaiflow.worker.repository;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.FileVisitResult;
import java.nio.file.Files;
import java.nio.file.InvalidPathException;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.SimpleFileVisitor;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
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

public class RepositoryWorkerActionHandler implements WorkerActionHandler {

    private static final Logger LOGGER = LoggerFactory.getLogger(RepositoryWorkerActionHandler.class);

    private static final String WORKER_NAME = "repository-worker";

    private static final Set<String> SUPPORTED_ACTION_TYPES = Set.of(
            "search_code",
            "read_file",
            "analyze_module"
    );

    private final ObjectMapper objectMapper;
    private final Path workspaceRoot;
    private final ActionSchemaValidator schemaValidator;
    private final SchemaValidationMode validationMode;
    private final int maxSearchResults;
    private final int maxReadBytes;
    private final Set<String> ignoredDirectoryNames;

    public RepositoryWorkerActionHandler(
            ObjectMapper objectMapper,
            Path workspaceRoot,
            ActionSchemaValidator schemaValidator,
            SchemaValidationMode validationMode,
            int maxSearchResults,
            int maxReadBytes,
            Collection<String> ignoredDirectoryNames) {
        this.objectMapper = objectMapper;
        this.workspaceRoot = workspaceRoot == null
                ? Path.of("").toAbsolutePath().normalize()
                : workspaceRoot.toAbsolutePath().normalize();
        this.schemaValidator = schemaValidator;
        this.validationMode = validationMode == null ? SchemaValidationMode.WARN : validationMode;
        this.maxSearchResults = Math.max(1, maxSearchResults);
        this.maxReadBytes = Math.max(1024, maxReadBytes);
        this.ignoredDirectoryNames = normalizeIgnoredDirectories(ignoredDirectoryNames);
    }

    @Override
    public WorkerExecutionResult execute(ActionAssignment assignment) {
        if (!SUPPORTED_ACTION_TYPES.contains(assignment.type())) {
            return WorkerExecutionResult.failed(
                    "unsupported action type",
                    "Repository worker supports only search_code, read_file and analyze_module"
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

        try {
            String resultJson = buildResultJson(assignment.type(), payload);

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

            LOGGER.info("repository_execution_succeeded actionId={} actionType={} workspaceRoot={}",
                    assignment.actionId(), assignment.type(), workspaceRoot);
            return WorkerExecutionResult.succeeded(resultJson);
        } catch (RuntimeException | IOException exception) {
            LOGGER.warn("Repository worker failed to execute actionId={} type={}",
                    assignment.actionId(), assignment.type(), exception);
            return WorkerExecutionResult.failed("repository execution failed", exception.getMessage());
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

    private String buildResultJson(String actionType, JsonNode payload) throws IOException {
        return switch (actionType) {
            case "search_code" -> buildSearchCodeResultJson(payload);
            case "read_file" -> buildReadFileResultJson(payload);
            default -> buildAnalyzeModuleResultJson(payload);
        };
    }

    private String buildSearchCodeResultJson(JsonNode payload) throws IOException {
        String query = firstNonBlank(
                payload.path("query").asText(null),
                payload.path("needle").asText(null));
        if (query.isBlank()) {
            throw new IllegalArgumentException("query is required for search_code");
        }

        SearchOutcome outcome = searchCode(query, extractScopePaths(payload));
        ObjectNode result = baseResultNode();
        result.put("query", query);
        result.put("matchCount", outcome.matches().size());
        result.put("truncated", outcome.truncated());

        ArrayNode matches = result.putArray("matches");
        for (SearchMatch match : outcome.matches()) {
            ObjectNode item = matches.addObject();
            item.put("path", match.path());
            item.put("lineNumber", match.lineNumber());
            item.put("lineText", match.lineText());
        }
        return objectMapper.writeValueAsString(result);
    }

    private String buildReadFileResultJson(JsonNode payload) throws IOException {
        ReadFileOutcome outcome = readRequestedFile(payload, true);
        ObjectNode result = baseResultNode();
        result.put("path", outcome.path());
        result.put("lineCount", outcome.lineCount());
        result.put("truncated", outcome.truncated());
        result.put("fileSizeBytes", outcome.fileSizeBytes());
        result.put("content", outcome.content());
        return objectMapper.writeValueAsString(result);
    }

    private String buildAnalyzeModuleResultJson(JsonNode payload) throws IOException {
        ReadFileOutcome outcome = readRequestedFile(payload, false);
        ObjectNode result = baseResultNode();

        String issue = payload.path("issue").asText("");
        if (!issue.isBlank()) {
            result.put("issue", issue);
        }

        String repoContext = firstNonBlank(
                payload.path("repo_context").asText(null),
                payload.path("context").asText(null));
        if (!repoContext.isBlank()) {
            result.put("repoContext", repoContext);
        }

        if (outcome.exists()) {
            result.put("path", outcome.path());
            result.put("lineCount", outcome.lineCount());
            result.put("truncated", outcome.truncated());
            result.put("fileSizeBytes", outcome.fileSizeBytes());
            result.put("content", outcome.content());
            result.put("note", "analyze_module compatibility path executed through repository file read");
        } else {
            result.putNull("path");
            result.put("lineCount", 0);
            result.put("truncated", false);
            result.put("fileSizeBytes", 0L);
            result.put("content", "");
            result.put("note", "No file path provided; analyze_module completed with metadata-only context");
        }

        return objectMapper.writeValueAsString(result);
    }

    private ObjectNode baseResultNode() {
        ObjectNode result = objectMapper.createObjectNode();
        result.put("schemaVersion", "v1");
        result.put("worker", WORKER_NAME);
        return result;
    }

    private SearchOutcome searchCode(String query, List<String> requestedPaths) throws IOException {
        List<SearchMatch> matches = new ArrayList<>();
        boolean truncated = false;
        String normalizedQuery = query.toLowerCase(Locale.ROOT);

        for (Path searchRoot : resolveSearchRoots(requestedPaths)) {
            if (Files.isRegularFile(searchRoot)) {
                if (searchFile(searchRoot, normalizedQuery, matches)) {
                    truncated = true;
                    break;
                }
                continue;
            }

            if (!Files.isDirectory(searchRoot)) {
                continue;
            }

            SearchFileVisitor visitor = new SearchFileVisitor(normalizedQuery, matches);
            Files.walkFileTree(searchRoot, visitor);
            if (visitor.truncated()) {
                truncated = true;
                break;
            }
        }

        return new SearchOutcome(List.copyOf(matches), truncated);
    }

    private boolean searchFile(Path file, String normalizedQuery, List<SearchMatch> matches) {
        try {
            if (Files.size(file) > maxReadBytes) {
                return false;
            }
        } catch (IOException exception) {
            LOGGER.debug("Skipping unreadable file during search: {}", file, exception);
            return false;
        }

        try (BufferedReader reader = Files.newBufferedReader(file, StandardCharsets.UTF_8)) {
            String line;
            int lineNumber = 0;
            while ((line = reader.readLine()) != null) {
                lineNumber++;
                if (!line.toLowerCase(Locale.ROOT).contains(normalizedQuery)) {
                    continue;
                }

                matches.add(new SearchMatch(
                        relativePathString(file),
                        lineNumber,
                        abbreviate(line.trim(), 240)));
                if (matches.size() >= maxSearchResults) {
                    return true;
                }
            }
        } catch (IOException exception) {
            LOGGER.debug("Skipping file during search because it could not be decoded as text: {}", file, exception);
        }

        return false;
    }

    private ReadFileOutcome readRequestedFile(JsonNode payload, boolean requirePath) throws IOException {
        String rawPath = firstNonBlank(
                payload.path("path").asText(null),
                payload.path("file").asText(null));

        if (rawPath.isBlank()) {
            if (requirePath) {
                throw new IllegalArgumentException("path or file is required");
            }
            return ReadFileOutcome.empty();
        }

        Path resolved = resolveWorkspacePath(rawPath);
        if (!Files.exists(resolved) || !Files.isRegularFile(resolved)) {
            throw new IllegalArgumentException("file not found: " + rawPath);
        }

        return readFile(resolved);
    }

    private ReadFileOutcome readFile(Path file) throws IOException {
        long fileSize = Files.size(file);
        boolean truncated = fileSize > maxReadBytes;
        byte[] bytes;

        if (truncated) {
            try (InputStream inputStream = Files.newInputStream(file)) {
                bytes = inputStream.readNBytes(maxReadBytes);
            }
        } else {
            bytes = Files.readAllBytes(file);
        }

        if (containsBinaryContent(bytes)) {
            throw new IllegalArgumentException("binary files are not supported: " + relativePathString(file));
        }

        String content = new String(bytes, StandardCharsets.UTF_8);
        return new ReadFileOutcome(
                true,
                relativePathString(file),
                content,
                countLines(content),
                truncated,
                fileSize);
    }

    private List<Path> resolveSearchRoots(List<String> requestedPaths) {
        if (requestedPaths.isEmpty()) {
            return List.of(workspaceRoot);
        }

        LinkedHashSet<Path> resolvedRoots = new LinkedHashSet<>();
        for (String requestedPath : requestedPaths) {
            if (requestedPath == null || requestedPath.isBlank()) {
                continue;
            }

            Path resolved = resolveWorkspacePath(requestedPath);
            if (Files.exists(resolved)) {
                resolvedRoots.add(resolved);
            }
        }
        return resolvedRoots.isEmpty() ? List.of(workspaceRoot) : List.copyOf(resolvedRoots);
    }

    private List<String> extractScopePaths(JsonNode payload) {
        ArrayList<String> paths = new ArrayList<>();
        collectTextArray(payload.path("scope").path("paths"), paths);
        collectTextArray(payload.path("paths"), paths);
        String directPath = firstNonBlank(payload.path("path").asText(null), payload.path("file").asText(null));
        if (!directPath.isBlank()) {
            paths.add(directPath);
        }
        return paths.stream().distinct().toList();
    }

    private void collectTextArray(JsonNode node, List<String> target) {
        if (node == null || !node.isArray()) {
            return;
        }
        for (JsonNode item : node) {
            if (item != null && item.isTextual() && !item.asText().isBlank()) {
                target.add(item.asText());
            }
        }
    }

    private Path resolveWorkspacePath(String rawPath) {
        try {
            Path candidate = Paths.get(rawPath.trim());
            Path resolved = candidate.isAbsolute()
                    ? candidate.normalize()
                    : workspaceRoot.resolve(candidate).normalize();
            if (!resolved.startsWith(workspaceRoot)) {
                throw new IllegalArgumentException("path must stay within workspace root: " + rawPath);
            }
            return resolved;
        } catch (InvalidPathException exception) {
            throw new IllegalArgumentException("invalid path: " + rawPath, exception);
        }
    }

    private String relativePathString(Path path) {
        Path normalized = path.toAbsolutePath().normalize();
        if (normalized.startsWith(workspaceRoot)) {
            return workspaceRoot.relativize(normalized).toString().replace('\\', '/');
        }
        return normalized.toString().replace('\\', '/');
    }

    private boolean shouldSkipDirectory(Path directory) {
        if (directory == null || directory.equals(workspaceRoot)) {
            return false;
        }
        Path fileName = directory.getFileName();
        return fileName != null && ignoredDirectoryNames.contains(fileName.toString());
    }

    private Set<String> normalizeIgnoredDirectories(Collection<String> directories) {
        LinkedHashSet<String> normalized = new LinkedHashSet<>();
        if (directories != null) {
            for (String directory : directories) {
                if (directory != null && !directory.isBlank()) {
                    normalized.add(directory.trim());
                }
            }
        }
        return Set.copyOf(normalized);
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

    private static String abbreviate(String value, int maxLength) {
        if (value == null || value.length() <= maxLength) {
            return value == null ? "" : value;
        }
        return value.substring(0, Math.max(1, maxLength)) + "...";
    }

    private static boolean containsBinaryContent(byte[] bytes) {
        for (byte current : bytes) {
            if (current == 0) {
                return true;
            }
        }
        return false;
    }

    private static int countLines(String content) {
        if (content == null || content.isEmpty()) {
            return 0;
        }
        return (int) content.lines().count();
    }

    private record PayloadParseResult(boolean parseable, JsonNode payloadNode, String errorMessage) {

        static PayloadParseResult success(JsonNode payloadNode) {
            return new PayloadParseResult(true, payloadNode, null);
        }

        static PayloadParseResult failure(String errorMessage) {
            return new PayloadParseResult(false, null, errorMessage);
        }
    }

    private record SearchMatch(String path, int lineNumber, String lineText) {
    }

    private record SearchOutcome(List<SearchMatch> matches, boolean truncated) {
    }

    private record ReadFileOutcome(
            boolean exists,
            String path,
            String content,
            int lineCount,
            boolean truncated,
            long fileSizeBytes
    ) {
        static ReadFileOutcome empty() {
            return new ReadFileOutcome(false, "", "", 0, false, 0L);
        }
    }

    private final class SearchFileVisitor extends SimpleFileVisitor<Path> {

        private final String normalizedQuery;
        private final List<SearchMatch> matches;
        private boolean truncated;

        private SearchFileVisitor(String normalizedQuery, List<SearchMatch> matches) {
            this.normalizedQuery = normalizedQuery;
            this.matches = matches;
        }

        @Override
        public FileVisitResult preVisitDirectory(Path dir, BasicFileAttributes attrs) {
            return shouldSkipDirectory(dir) ? FileVisitResult.SKIP_SUBTREE : FileVisitResult.CONTINUE;
        }

        @Override
        public FileVisitResult visitFile(Path file, BasicFileAttributes attrs) {
            if (!attrs.isRegularFile()) {
                return FileVisitResult.CONTINUE;
            }

            if (searchFile(file, normalizedQuery, matches)) {
                truncated = true;
                return FileVisitResult.TERMINATE;
            }
            return FileVisitResult.CONTINUE;
        }

        boolean truncated() {
            return truncated;
        }
    }
}