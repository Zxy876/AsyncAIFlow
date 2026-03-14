package com.asyncaiflow.service;

import java.time.LocalDateTime;
import java.util.List;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.asyncaiflow.domain.entity.ActionEntity;
import com.asyncaiflow.domain.entity.WorkflowEntity;
import com.asyncaiflow.domain.enums.ActionStatus;
import com.asyncaiflow.domain.enums.WorkflowStatus;
import com.asyncaiflow.mapper.ActionMapper;
import com.asyncaiflow.mapper.WorkflowMapper;
import com.asyncaiflow.support.ApiException;
import com.asyncaiflow.support.RuntimeStatusView;
import com.asyncaiflow.web.dto.CreateWorkflowRequest;
import com.asyncaiflow.web.dto.WorkflowActionSummaryResponse;
import com.asyncaiflow.web.dto.WorkflowExecutionResponse;
import com.asyncaiflow.web.dto.WorkflowListItemResponse;
import com.asyncaiflow.web.dto.WorkflowResponse;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;

@Service
public class WorkflowService {

    private final WorkflowMapper workflowMapper;
    private final ActionMapper actionMapper;

    public WorkflowService(WorkflowMapper workflowMapper, ActionMapper actionMapper) {
        this.workflowMapper = workflowMapper;
        this.actionMapper = actionMapper;
    }

    @Transactional
    public WorkflowResponse createWorkflow(CreateWorkflowRequest request) {
        LocalDateTime now = LocalDateTime.now();
        WorkflowEntity workflow = new WorkflowEntity();
        workflow.setName(request.name().trim());
        workflow.setDescription(request.description());
        workflow.setStatus(WorkflowStatus.CREATED.name());
        workflow.setCreatedAt(now);
        workflow.setUpdatedAt(now);
        workflowMapper.insert(workflow);
        return toResponse(workflow);
    }

    public WorkflowEntity requireWorkflow(Long workflowId) {
        WorkflowEntity workflow = workflowMapper.selectById(workflowId);
        if (workflow == null) {
            throw new ApiException(HttpStatus.NOT_FOUND, "Workflow not found: " + workflowId);
        }
        return workflow;
    }

    public WorkflowExecutionResponse getWorkflowExecution(Long workflowId) {
        WorkflowEntity workflow = requireWorkflow(workflowId);
        List<ActionEntity> actions = listWorkflowActionEntities(workflowId);
        List<WorkflowActionSummaryResponse> actionSummaries = actions.stream()
                .map(this::toActionSummary)
                .toList();

        return new WorkflowExecutionResponse(
                workflow.getId(),
                RuntimeStatusView.workflowStatus(actions),
                workflow.getCreatedAt(),
                actionSummaries
        );
    }

    public List<WorkflowListItemResponse> getRecentWorkflows(int limit) {
        int effectiveLimit = Math.max(1, Math.min(limit, 50));
        return workflowMapper.selectList(new LambdaQueryWrapper<WorkflowEntity>()
                        .orderByDesc(WorkflowEntity::getCreatedAt)
                        .orderByDesc(WorkflowEntity::getId)
                        .last("LIMIT " + effectiveLimit))
                .stream()
                .map(this::toWorkflowListItem)
                .toList();
    }

    public List<WorkflowActionSummaryResponse> getWorkflowActions(Long workflowId) {
        requireWorkflow(workflowId);
        return listWorkflowActionEntities(workflowId).stream()
                .map(this::toActionSummary)
                .toList();
    }

    @Transactional
    public void refreshStatus(Long workflowId) {
        WorkflowEntity workflow = requireWorkflow(workflowId);
        List<ActionEntity> actions = actionMapper.selectList(new LambdaQueryWrapper<ActionEntity>()
                .eq(ActionEntity::getWorkflowId, workflowId));

        WorkflowStatus nextStatus = deriveStatus(actions);
        if (!nextStatus.name().equals(workflow.getStatus())) {
            workflow.setStatus(nextStatus.name());
            workflow.setUpdatedAt(LocalDateTime.now());
            workflowMapper.updateById(workflow);
        }
    }

    public WorkflowResponse toResponse(WorkflowEntity workflow) {
        return new WorkflowResponse(
                workflow.getId(),
                workflow.getName(),
                workflow.getDescription(),
                workflow.getStatus(),
                workflow.getCreatedAt()
        );
    }

    private List<ActionEntity> listWorkflowActionEntities(Long workflowId) {
        return actionMapper.selectList(new LambdaQueryWrapper<ActionEntity>()
                .eq(ActionEntity::getWorkflowId, workflowId)
                .orderByAsc(ActionEntity::getCreatedAt)
                .orderByAsc(ActionEntity::getId));
    }

    private WorkflowActionSummaryResponse toActionSummary(ActionEntity action) {
        String status = RuntimeStatusView.actionStatus(action.getStatus());
        return new WorkflowActionSummaryResponse(
                action.getId(),
                action.getType(),
                status,
                action.getWorkerId(),
                action.getCreatedAt(),
                terminalFinishedAt(status, action)
        );
    }

    private WorkflowListItemResponse toWorkflowListItem(WorkflowEntity workflow) {
        List<ActionEntity> actions = listWorkflowActionEntities(workflow.getId());
        return new WorkflowListItemResponse(
                workflow.getId(),
                RuntimeStatusView.workflowStatus(actions),
                workflow.getCreatedAt(),
                resolveIssue(workflow)
        );
    }

    private LocalDateTime terminalFinishedAt(String status, ActionEntity action) {
        if (!"COMPLETED".equals(status) && !"FAILED".equals(status)) {
            return null;
        }
        if (action.getSubmitTime() != null) {
            return action.getSubmitTime();
        }
        return action.getReclaimTime();
    }

    private String resolveIssue(WorkflowEntity workflow) {
        if (workflow.getDescription() != null && !workflow.getDescription().isBlank()) {
            return workflow.getDescription().trim();
        }
        return workflow.getName();
    }

    private WorkflowStatus deriveStatus(List<ActionEntity> actions) {
        if (actions.isEmpty()) {
            return WorkflowStatus.CREATED;
        }
        boolean allSucceeded = actions.stream()
                .allMatch(action -> ActionStatus.SUCCEEDED.name().equals(action.getStatus()));
        if (allSucceeded) {
            return WorkflowStatus.COMPLETED;
        }
        boolean anyFailed = actions.stream()
                .anyMatch(action -> ActionStatus.FAILED.name().equals(action.getStatus())
                        || ActionStatus.DEAD_LETTER.name().equals(action.getStatus()));
        if (anyFailed) {
            return WorkflowStatus.FAILED;
        }
        return WorkflowStatus.RUNNING;
    }
}