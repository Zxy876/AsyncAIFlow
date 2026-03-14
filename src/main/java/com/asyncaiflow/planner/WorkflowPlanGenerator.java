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
                    searchCodeStep(normalizedIssue, normalizedFile),
                    analyzeModuleStep(normalizedIssue, normalizedRepoContext, normalizedFile),
                    generateExplanationStep(normalizedIssue, normalizedRepoContext, normalizedFile)
            );
        }

        if (isReviewIntent(normalizedIssue)) {
            return List.of(
                    searchCodeStep(normalizedIssue, normalizedFile),
                    reviewCodeStep(normalizedIssue, normalizedRepoContext, 0)
            );
        }

        if (isDiagnosisIntent(normalizedIssue)) {
            return List.of(
                    searchCodeStep(normalizedIssue, normalizedFile),
                    analyzeModuleStep(normalizedIssue, normalizedRepoContext, normalizedFile),
                    designSolutionStep(normalizedIssue, normalizedRepoContext, 1)
            );
        }

        return List.of(
                searchCodeStep(normalizedIssue, normalizedFile),
                designSolutionStep(normalizedIssue, normalizedRepoContext, 0),
                reviewCodeStep(normalizedIssue, normalizedRepoContext, 1)
        );
    }

    private PlanDraftStep searchCodeStep(String issue, String file) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("schemaVersion", "v1");
        payload.put("query", issue);

        if (!file.isBlank()) {
            payload.put("scope", Map.of("paths", List.of(file)));
        }

        return new PlanDraftStep("search_code", payload, List.of());
    }

    private PlanDraftStep analyzeModuleStep(String issue, String repoContext, String file) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("schemaVersion", "v1");
        payload.put("issue", issue);
        if (!repoContext.isBlank()) {
            payload.put("repo_context", repoContext);
        }
        if (!file.isBlank()) {
            payload.put("file", file);
        }

        return new PlanDraftStep("analyze_module", payload, List.of(0));
    }

    private PlanDraftStep generateExplanationStep(String issue, String repoContext, String file) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("schemaVersion", "v1");
        payload.put("issue", issue);
        if (!repoContext.isBlank()) {
            payload.put("repo_context", repoContext);
        }
        if (!file.isBlank()) {
            payload.put("file", file);
        }

        return new PlanDraftStep("generate_explanation", payload, List.of(1));
    }

    private PlanDraftStep designSolutionStep(String issue, String repoContext, int dependsOnIndex) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("schemaVersion", "v1");
        payload.put("issue", issue);
        if (!repoContext.isBlank()) {
            payload.put("context", repoContext);
        }
        payload.put("constraints", List.of("keep plan minimal and execution-oriented"));

        return new PlanDraftStep("design_solution", payload, List.of(dependsOnIndex));
    }

    private PlanDraftStep reviewCodeStep(String issue, String repoContext, int dependsOnIndex) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("schemaVersion", "v1");
        payload.put("focus", "issue-driven review");
        if (!repoContext.isBlank()) {
            payload.put("context", repoContext);
        }
        payload.put("knownIssues", List.of(issue));

        return new PlanDraftStep("review_code", payload, List.of(dependsOnIndex));
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
        return raw.trim();
    }
}
