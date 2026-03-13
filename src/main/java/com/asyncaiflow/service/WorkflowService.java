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
import com.asyncaiflow.web.dto.CreateWorkflowRequest;
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
                .anyMatch(action -> ActionStatus.FAILED.name().equals(action.getStatus()));
        if (anyFailed) {
            return WorkflowStatus.FAILED;
        }
        return WorkflowStatus.RUNNING;
    }
}