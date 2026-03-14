package com.asyncaiflow.service;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import org.junit.jupiter.api.Test;

import com.asyncaiflow.web.dto.PlannerPlanRequest;
import com.asyncaiflow.web.dto.PlannerPlanResponse;

class PlannerServiceTest {

    @Test
    void previewPlanReturnsExpectedExplainPlan() {
        PlannerService plannerService = new PlannerService();

        PlannerPlanResponse response = plannerService.previewPlan(
                new PlannerPlanRequest(
                        "Explain authentication module",
                        "auth package",
                        "src/main/java/com/example/auth/AuthService.java"
                ));

        assertEquals(3, response.plan().size());
        assertEquals("search_code", response.plan().get(0).type());
        assertEquals("analyze_module", response.plan().get(1).type());
        assertEquals("generate_explanation", response.plan().get(2).type());
        assertEquals(List.of(0), response.plan().get(1).dependsOn());
    }

    @Test
        void previewPlanReturnsDiagnosisPlanForBugIssue() {
        PlannerService plannerService = new PlannerService();

        PlannerPlanResponse response = plannerService.previewPlan(
                new PlannerPlanRequest("Fix login bug", "", ""));

                assertEquals(List.of("search_code", "analyze_module", "design_solution"),
                response.plan().stream().map(step -> step.type()).toList());
        assertEquals(List.of(1), response.plan().get(2).dependsOn());
    }

        @Test
        void previewPlanReturnsDiagnosisPlanForDriftMappingIssue() {
                PlannerService plannerService = new PlannerService();

                PlannerPlanResponse response = plannerService.previewPlan(
                                new PlannerPlanRequest(
                                                "Find bug in resource mapping",
                                                "DriftSystem backend app core mapping subsystem",
                                                "/Users/zxydediannao/DriftSystem/backend/app/core/mapping/v2_mapper.py"));

                assertEquals(List.of("search_code", "analyze_module", "design_solution"),
                                response.plan().stream().map(step -> step.type()).toList());
                assertEquals(List.of(1), response.plan().get(2).dependsOn());
        }

            @Test
            void previewPlanReturnsExplainPlanForFlowTraceIssue() {
                PlannerService plannerService = new PlannerService();

                PlannerPlanResponse response = plannerService.previewPlan(
                        new PlannerPlanRequest(
                                "Trace the full flow of rule-event from Minecraft plugin to backend",
                                "DriftSystem system/mc_plugin scene flow and backend routers",
                                ""));

                assertEquals(List.of("search_code", "analyze_module", "generate_explanation"),
                        response.plan().stream().map(step -> step.type()).toList());
                assertEquals(List.of(1), response.plan().get(2).dependsOn());
            }

            @Test
            void previewPlanReturnsDiagnosisPlanForWhyMightFailIssue() {
                PlannerService plannerService = new PlannerService();

                PlannerPlanResponse response = plannerService.previewPlan(
                        new PlannerPlanRequest(
                                "Why might resource mapping fail in v2_mapper.py",
                                "DriftSystem backend app core mapping subsystem",
                                "/Users/zxydediannao/DriftSystem/backend/app/core/mapping/v2_mapper.py"));

                assertEquals(List.of("search_code", "analyze_module", "design_solution"),
                        response.plan().stream().map(step -> step.type()).toList());
                assertEquals(List.of(1), response.plan().get(2).dependsOn());
            }
}
