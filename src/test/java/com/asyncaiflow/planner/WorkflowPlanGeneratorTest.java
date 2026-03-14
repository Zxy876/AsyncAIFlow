package com.asyncaiflow.planner;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import org.junit.jupiter.api.Test;

class WorkflowPlanGeneratorTest {

    private final WorkflowPlanGenerator generator = new WorkflowPlanGenerator();

    @Test
    void explainIssueGeneratesExplainPipeline() {
        List<PlanDraftStep> plan = generator.generatePlan(
                "Explain authentication module",
                "auth package",
                "src/main/java/com/example/auth/AuthService.java");

        assertEquals(List.of("search_code", "analyze_module", "generate_explanation"),
                plan.stream().map(PlanDraftStep::type).toList());
        assertEquals(List.of(), plan.get(0).dependsOn());
        assertEquals(List.of(0), plan.get(1).dependsOn());
        assertEquals(List.of(1), plan.get(2).dependsOn());
        assertTrue(plan.get(0).payload().containsKey("scope"));
    }

    @Test
    void bugIssueGeneratesDiagnosisPipeline() {
        List<PlanDraftStep> plan = generator.generatePlan("Fix login bug", "web login flow", "");

        assertEquals(List.of("search_code", "analyze_module", "design_solution"),
                plan.stream().map(PlanDraftStep::type).toList());
        assertEquals(List.of(), plan.get(0).dependsOn());
        assertEquals(List.of(0), plan.get(1).dependsOn());
        assertEquals(List.of(1), plan.get(2).dependsOn());
    }

    @Test
    void driftMappingBugIssueGeneratesDiagnosisPipeline() {
        List<PlanDraftStep> plan = generator.generatePlan(
                "Find bug in resource mapping",
                "DriftSystem backend app core mapping subsystem",
                "/Users/zxydediannao/DriftSystem/backend/app/core/mapping/v2_mapper.py");

        assertEquals(List.of("search_code", "analyze_module", "design_solution"),
                plan.stream().map(PlanDraftStep::type).toList());
        assertTrue(plan.get(0).payload().containsKey("scope"));
        assertEquals(List.of(1), plan.get(2).dependsOn());
    }

        @Test
        void flowTraceIssueGeneratesExplainPipeline() {
        List<PlanDraftStep> plan = generator.generatePlan(
            "Trace the full flow of rule-event from Minecraft plugin to backend",
            "DriftSystem system/mc_plugin scene flow and backend routers",
            "");

        assertEquals(List.of("search_code", "analyze_module", "generate_explanation"),
            plan.stream().map(PlanDraftStep::type).toList());
        assertEquals(List.of(1), plan.get(2).dependsOn());
        }

        @Test
        void whyMightFailIssueGeneratesDiagnosisPipeline() {
        List<PlanDraftStep> plan = generator.generatePlan(
            "Why might resource mapping fail in v2_mapper.py",
            "DriftSystem backend app core mapping subsystem",
            "/Users/zxydediannao/DriftSystem/backend/app/core/mapping/v2_mapper.py");

        assertEquals(List.of("search_code", "analyze_module", "design_solution"),
            plan.stream().map(PlanDraftStep::type).toList());
        assertEquals(List.of(1), plan.get(2).dependsOn());
        }

    @Test
    void blankIssueReturnsEmptyPlan() {
        List<PlanDraftStep> plan = generator.generatePlan("   ", "", "");

        assertTrue(plan.isEmpty());
    }
}
