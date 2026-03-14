package com.asyncaiflow.service;

import java.util.List;

import org.springframework.stereotype.Service;

import com.asyncaiflow.planner.PlanDraftStep;
import com.asyncaiflow.planner.WorkflowPlanGenerator;
import com.asyncaiflow.web.dto.PlannerPlanRequest;
import com.asyncaiflow.web.dto.PlannerPlanResponse;
import com.asyncaiflow.web.dto.PlannerPlanStep;

@Service
public class PlannerService {

    private final WorkflowPlanGenerator workflowPlanGenerator;

    public PlannerService() {
        this.workflowPlanGenerator = new WorkflowPlanGenerator();
    }

    public PlannerPlanResponse previewPlan(PlannerPlanRequest request) {
        List<PlannerPlanStep> plan = workflowPlanGenerator
                .generatePlan(request.issue(), request.repoContext(), request.file())
                .stream()
                .map(this::toResponseStep)
                .toList();

        return new PlannerPlanResponse(plan);
    }

    private PlannerPlanStep toResponseStep(PlanDraftStep step) {
        return new PlannerPlanStep(step.type(), step.payload(), step.dependsOn());
    }
}
