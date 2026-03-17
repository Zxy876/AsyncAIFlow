package com.asyncaiflow.planner;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

public class WorkflowPlanGenerator {

    public List<PlanDraftStep> generatePlan(String issue, String repoContext, String file) {
        String normalizedIssue = normalize(issue);
        if (normalizedIssue.isBlank()) {
            return List.of();
        }

        String normalizedRepoContext = normalize(repoContext);
        String normalizedFile = normalize(file);

        if (isExplainIntent(normalizedIssue) || isFlowTraceIntent(normalizedIssue)) {
            return List.of(
                    searchSemanticStep(normalizedIssue, normalizedFile),
                    buildContextPackStep(normalizedIssue, normalizedRepoContext, normalizedFile, 0),
                    generateExplanationStep(normalizedIssue, normalizedRepoContext, normalizedFile, 1)
            );
        }

        if (isReviewIntent(normalizedIssue)) {
            return List.of(
                    searchSemanticStep(normalizedIssue, normalizedFile),
                loadCodeStep(normalizedFile, 0),
                buildContextPackStep(normalizedIssue, normalizedRepoContext, normalizedFile, 0),
                reviewCodeStep(normalizedIssue, normalizedRepoContext, List.of(1, 2))
            );
        }

        if (isDiagnosisIntent(normalizedIssue)) {
            return repairPipeline(normalizedIssue, normalizedRepoContext, normalizedFile);
        }

        return repairPipeline(normalizedIssue, normalizedRepoContext, normalizedFile);
    }

    private List<PlanDraftStep> repairPipeline(String issue, String repoContext, String file) {
        return List.of(
                searchSemanticStep(issue, file),
                loadCodeStep(file, 0),
                buildContextPackStep(issue, repoContext, file, 0),
                designSolutionStep(issue, repoContext, 2),
                generatePatchStep(issue, repoContext, file, List.of(1, 2, 3)),
                reviewPatchStep(issue, repoContext, file, List.of(1, 2, 3, 4)),
            applyPatchStep(List.of(0, 1, 5)),
                commitChangesStep(issue, List.of(6))
        );
    }

    private PlanDraftStep searchSemanticStep(String issue, String file) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("schemaVersion", "v1");
        payload.put("query", issue);
        payload.put("topK", 5);

        if (!file.isBlank()) {
            payload.put("scope", Map.of("paths", List.of(file)));
        }

        return new PlanDraftStep("search_semantic", payload, List.of());
    }

    private PlanDraftStep buildContextPackStep(String issue, String repoContext, String file, int dependsOnIndex) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("schemaVersion", "v1");
        payload.put("issue", issue);
        payload.put("query", issue);
        payload.put("maxFiles", 3);
        payload.put("maxCharsPerFile", 4000);
        payload.put("inject", Map.of(
                "retrievalResults", "$upstream[0].result.matches"));

        if (!repoContext.isBlank()) {
            payload.put("repo_context", repoContext);
        }
        if (!file.isBlank()) {
            payload.put("file", file);
            payload.put("scope", Map.of("paths", List.of(file)));
        }

        return new PlanDraftStep("build_context_pack", payload, List.of(dependsOnIndex));
    }

    private PlanDraftStep loadCodeStep(String file, int dependsOnIndex) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("schemaVersion", "v1");
        payload.put("maxFiles", 3);
        payload.put("maxCharsPerFile", 4000);
        if (!file.isBlank()) {
            payload.put("path", file);
        }

        Map<String, Object> pathRule = new LinkedHashMap<>();
        pathRule.put("from", "$upstream[0].result.matches[0].path");
        if (!file.isBlank()) {
            pathRule.put("default", file);
        }
        payload.put("inject", Map.of("path", pathRule));

        return new PlanDraftStep("load_code", payload, List.of(dependsOnIndex));
    }

    private PlanDraftStep generateExplanationStep(String issue, String repoContext, String file, int dependsOnIndex) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("schemaVersion", "v1");
        payload.put("issue", issue);
        if (!repoContext.isBlank()) {
            payload.put("repo_context", repoContext);
        }
        if (!file.isBlank()) {
            payload.put("file", file);
        }
        payload.put("gathered_context", Map.of(
                "source", "build_context_pack",
                "hint", "Use upstream build_context_pack result as the primary repository evidence."));
        payload.put("inject", Map.of(
            "gathered_context", "$upstream[0].result"));

        return new PlanDraftStep("generate_explanation", payload, List.of(dependsOnIndex));
    }

    private PlanDraftStep designSolutionStep(String issue, String repoContext, int dependsOnIndex) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("schemaVersion", "v1");
        payload.put("issue", issue);
        if (!repoContext.isBlank()) {
            payload.put("context", repoContext);
        }
        payload.put("constraints", List.of(
                "respond in Simplified Chinese",
                "format output in Markdown",
                "use sections: 结论, 发现, 代码位置, 建议修复, 风险",
                "keep plan minimal and execution-oriented",
                "base recommendations on build_context_pack evidence"));
        payload.put("inject", Map.of(
            "context", Map.of(
                "from", "$upstreamByType.build_context_pack.result.summary",
                "default", repoContext
            )));

        return new PlanDraftStep("design_solution", payload, List.of(dependsOnIndex));
    }

    private PlanDraftStep generatePatchStep(String issue, String repoContext, String file, List<Integer> dependsOnIndices) {
    Map<String, Object> payload = new LinkedHashMap<>();
    payload.put("schemaVersion", "v1");
    payload.put("issue", issue);
    if (!file.isBlank()) {
        payload.put("file", file);
    }
    if (!repoContext.isBlank()) {
        payload.put("context", repoContext);
    }
    payload.put("constraints", List.of(
        "respond in Simplified Chinese",
        "format output in Markdown",
        "return exactly one fenced unified diff block",
        "keep the patch minimal and directly applicable by git apply",
        "preserve existing behavior except for the required fix"
    ));
    payload.put("inject", Map.of(
        "file", Map.of(
            "from", "$upstreamByType.load_code.result.files[0].path",
            "fallbackFrom", List.of("$upstreamByType.search_semantic.result.matches[0].path"),
            "default", file),
        "context", Map.of(
            "from", "$upstreamByType.build_context_pack.result.summary",
            "default", repoContext),
        "code", Map.of(
            "from", "$upstreamByType.load_code.result.code",
            "fallbackFrom", List.of(
                "$upstreamByType.build_context_pack.result.sources[0].content",
                "$upstreamByType.build_context_pack.result.retrieval[0].chunk"
            ),
            "required", true),
        "designSummary", Map.of(
            "from", "$upstreamByType.design_solution.result.summary",
            "fallbackFrom", List.of("$upstreamByType.design_solution.result.content")
        )
    ));

    return new PlanDraftStep("generate_patch", payload, dependsOnIndices);
    }

    private PlanDraftStep reviewPatchStep(String issue, String repoContext, String file, List<Integer> dependsOnIndices) {
    Map<String, Object> payload = new LinkedHashMap<>();
    payload.put("schemaVersion", "v1");
    payload.put("issue", issue);
    if (!file.isBlank()) {
        payload.put("file", file);
    }
    if (!repoContext.isBlank()) {
        payload.put("context", repoContext);
    }
    payload.put("inject", Map.of(
        "file", Map.of(
            "from", "$upstreamByType.load_code.result.files[0].path",
            "fallbackFrom", List.of("$upstreamByType.search_semantic.result.matches[0].path"),
            "default", file),
        "context", Map.of(
            "from", "$upstreamByType.build_context_pack.result.summary",
            "default", repoContext),
        "code", Map.of(
            "from", "$upstreamByType.load_code.result.code",
            "fallbackFrom", List.of("$upstreamByType.build_context_pack.result.sources[0].content")
        ),
        "designSummary", Map.of(
            "from", "$upstreamByType.design_solution.result.summary",
            "fallbackFrom", List.of("$upstreamByType.design_solution.result.content")
        ),
        "patch", Map.of(
            "from", "$upstreamByType.generate_patch.result.patch",
            "required", true)
    ));

    return new PlanDraftStep("review_patch", payload, dependsOnIndices);
    }

    private PlanDraftStep applyPatchStep(List<Integer> dependsOnIndices) {
    Map<String, Object> payload = new LinkedHashMap<>();
    payload.put("schemaVersion", "v1");
    payload.put("threeWay", true);
    payload.put("inject", Map.of(
        "patch", Map.of(
            "from", "$upstreamByType.review_patch.result.patch",
            "fallbackFrom", List.of("$upstreamByType.generate_patch.result.patch"),
            "required", true),
        "repoPath", Map.of(
            "from", "$upstreamByType.load_code.result.files[0].path",
            "fallbackFrom", List.of("$upstreamByType.search_semantic.result.matches[0].path"),
            "required", true)
    ));

    return new PlanDraftStep("apply_patch", payload, dependsOnIndices);
    }

    private PlanDraftStep commitChangesStep(String issue, List<Integer> dependsOnIndices) {
    Map<String, Object> payload = new LinkedHashMap<>();
    payload.put("schemaVersion", "v1");
    payload.put("message", buildCommitMessage(issue));
    payload.put("all", true);
    payload.put("inject", Map.of(
        "repoPath", Map.of(
            "from", "$upstreamByType.apply_patch.result.repoPath",
            "fallbackFrom", List.of(
                "$upstreamByType.load_code.result.files[0].path",
                "$upstreamByType.search_semantic.result.matches[0].path"
            ),
            "required", true)
    ));

    return new PlanDraftStep("commit_changes", payload, dependsOnIndices);
    }

    private String buildCommitMessage(String issue) {
    String normalized = issue == null ? "" : issue.trim();
    if (normalized.isBlank()) {
        return "Apply AI-generated patch";
    }

    String prefixed = "Apply fix: " + normalized;
    return prefixed.length() <= 72 ? prefixed : prefixed.substring(0, 72);
    }

    private PlanDraftStep reviewCodeStep(String issue, String repoContext, List<Integer> dependsOnIndices) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("schemaVersion", "v1");
        payload.put("focus", "issue-driven review");
        if (!repoContext.isBlank()) {
            payload.put("context", repoContext);
        }
        payload.put("knownIssues", List.of(issue));
        payload.put("code", "No source code payload was retrieved; use retrieval snippets as conservative evidence.");
        payload.put("inject", Map.of(
            "context", Map.of(
                "from", "$upstreamByType.build_context_pack.result.summary",
                "default", repoContext),
                "code", Map.of(
                "from", "$upstreamByType.load_code.result.code",
                "fallbackFrom", List.of(
                    "$upstreamByType.build_context_pack.result.sources[0].content",
                    "$upstreamByType.build_context_pack.result.retrieval[0].chunk"
                ),
                "default", "No source code payload was retrieved; use retrieval snippets as conservative evidence."
                )
        ));

        return new PlanDraftStep("review_code", payload, dependsOnIndices);
    }

    private boolean isExplainIntent(String issue) {
        String normalized = issue.toLowerCase(Locale.ROOT);
        return containsAny(normalized,
                "explain",
                "understand",
                "authentication",
                "module",
                "how does",
                "how do",
                "interacts with",
                "builds");
    }

    private boolean isReviewIntent(String issue) {
        String normalized = issue.toLowerCase(Locale.ROOT);
        return containsAny(normalized, "review", "audit")
                && !containsAny(normalized, "fix", "bug", "error", "failure", "failed");
    }

    private boolean isDiagnosisIntent(String issue) {
        String normalized = issue.toLowerCase(Locale.ROOT);
        return containsAny(normalized,
                "fix",
                "bug",
                "debug",
                "fail",
                "failure",
                "failed",
                "error",
                "why is",
                "why does",
                "why might",
                "root cause");
    }

    private boolean isFlowTraceIntent(String issue) {
        String normalized = issue.toLowerCase(Locale.ROOT);
        return normalized.contains("trace")
                && containsAny(normalized, "flow", "pipeline", "path", "interaction");
    }

    private boolean containsAny(String value, String... candidates) {
        for (String candidate : candidates) {
            if (value.contains(candidate)) {
                return true;
            }
        }
        return false;
    }

    private String normalize(String raw) {
        if (raw == null) {
            return "";
        }

        String normalized = raw.trim();
        if (normalized.toLowerCase(Locale.ROOT).startsWith("describe your issue:")) {
            normalized = normalized.substring("describe your issue:".length()).trim();
        }
        return normalized;
    }
}
