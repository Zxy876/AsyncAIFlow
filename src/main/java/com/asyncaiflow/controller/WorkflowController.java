package com.asyncaiflow.controller;

import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.asyncaiflow.service.WorkflowService;
import com.asyncaiflow.web.ApiResponse;
import com.asyncaiflow.web.dto.CreateWorkflowRequest;
import com.asyncaiflow.web.dto.WorkflowResponse;

import jakarta.validation.Valid;

@RestController
@RequestMapping("/workflow")
public class WorkflowController {

    private final WorkflowService workflowService;

    public WorkflowController(WorkflowService workflowService) {
        this.workflowService = workflowService;
    }

    @PostMapping("/create")
    public ApiResponse<WorkflowResponse> createWorkflow(@Valid @RequestBody CreateWorkflowRequest request) {
        return ApiResponse.ok("workflow created", workflowService.createWorkflow(request));
    }
}