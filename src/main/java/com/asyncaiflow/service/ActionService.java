package com.asyncaiflow.service;

import java.time.LocalDateTime;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.asyncaiflow.domain.entity.ActionDependencyEntity;
import com.asyncaiflow.domain.entity.ActionEntity;
import com.asyncaiflow.domain.entity.ActionLogEntity;
import com.asyncaiflow.domain.entity.WorkerEntity;
import com.asyncaiflow.domain.entity.WorkflowEntity;
import com.asyncaiflow.domain.enums.ActionStatus;
import com.asyncaiflow.mapper.ActionDependencyMapper;
import com.asyncaiflow.mapper.ActionLogMapper;
import com.asyncaiflow.mapper.ActionMapper;
import com.asyncaiflow.service.queue.ActionQueueService;
import com.asyncaiflow.support.ApiException;
import com.asyncaiflow.web.dto.ActionAssignmentResponse;
import com.asyncaiflow.web.dto.ActionResponse;
import com.asyncaiflow.web.dto.CreateActionRequest;
import com.asyncaiflow.web.dto.SubmitActionResultRequest;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;

@Service
public class ActionService {

    private final ActionMapper actionMapper;
    private final ActionDependencyMapper actionDependencyMapper;
    private final ActionLogMapper actionLogMapper;
    private final WorkflowService workflowService;
    private final WorkerService workerService;
    private final ActionQueueService actionQueueService;

    public ActionService(
            ActionMapper actionMapper,
            ActionDependencyMapper actionDependencyMapper,
            ActionLogMapper actionLogMapper,
            WorkflowService workflowService,
            WorkerService workerService,
            ActionQueueService actionQueueService
    ) {
        this.actionMapper = actionMapper;
        this.actionDependencyMapper = actionDependencyMapper;
        this.actionLogMapper = actionLogMapper;
        this.workflowService = workflowService;
        this.workerService = workerService;
        this.actionQueueService = actionQueueService;
    }

    @Transactional
    public ActionResponse createAction(CreateActionRequest request) {
        WorkflowEntity workflow = workflowService.requireWorkflow(request.workflowId());
        List<Long> upstreamActionIds = normalizeUpstreamActionIds(request.upstreamActionIds());
        validateUpstreamActions(workflow.getId(), upstreamActionIds);

        LocalDateTime now = LocalDateTime.now();
        ActionEntity action = new ActionEntity();
        action.setWorkflowId(workflow.getId());
        action.setType(request.type().trim());
        action.setStatus(upstreamActionIds.isEmpty() ? ActionStatus.QUEUED.name() : ActionStatus.BLOCKED.name());
        action.setPayload(request.payload());
        action.setRetryCount(0);
        action.setCreatedAt(now);
        action.setUpdatedAt(now);
        actionMapper.insert(action);

        for (Long upstreamActionId : upstreamActionIds) {
            ActionDependencyEntity dependency = new ActionDependencyEntity();
            dependency.setWorkflowId(workflow.getId());
            dependency.setUpstreamActionId(upstreamActionId);
            dependency.setDownstreamActionId(action.getId());
            actionDependencyMapper.insert(dependency);
        }

        if (upstreamActionIds.isEmpty()) {
            actionQueueService.enqueue(action);
        } else if (allDependenciesSucceeded(action.getId())) {
            action.setStatus(ActionStatus.QUEUED.name());
            action.setUpdatedAt(LocalDateTime.now());
            actionMapper.updateById(action);
            actionQueueService.enqueue(action);
        }

        workflowService.refreshStatus(workflow.getId());
        return toResponse(actionMapper.selectById(action.getId()));
    }

    @Transactional
    public Optional<ActionAssignmentResponse> pollAction(String workerId) {
        WorkerEntity worker = workerService.touchHeartbeat(workerId);
        List<String> capabilities = workerService.readCapabilities(worker);
        if (capabilities.isEmpty()) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "Worker has no capabilities");
        }

        for (int attempt = 0; attempt < 20; attempt++) {
            Optional<Long> candidateActionId = actionQueueService.claimNextAction(capabilities, workerId);
            if (candidateActionId.isEmpty()) {
                return Optional.empty();
            }

            ActionEntity action = actionMapper.selectById(candidateActionId.get());
            if (action == null || !ActionStatus.QUEUED.name().equals(action.getStatus())) {
                actionQueueService.releaseLock(candidateActionId.get());
                continue;
            }

            action.setStatus(ActionStatus.RUNNING.name());
            action.setWorkerId(workerId);
            action.setUpdatedAt(LocalDateTime.now());
            actionMapper.updateById(action);
            workflowService.refreshStatus(action.getWorkflowId());

            return Optional.of(new ActionAssignmentResponse(
                    action.getId(),
                    action.getWorkflowId(),
                    action.getType(),
                    action.getPayload(),
                    action.getRetryCount()
            ));
        }

        return Optional.empty();
    }

    @Transactional
    public ActionResponse submitResult(SubmitActionResultRequest request) {
        workerService.touchHeartbeat(request.workerId());
        ActionEntity action = requireAction(request.actionId());

        if (!ActionStatus.RUNNING.name().equals(action.getStatus())) {
            throw new ApiException(HttpStatus.CONFLICT, "Action is not in RUNNING status: " + action.getId());
        }
        if (action.getWorkerId() == null || !action.getWorkerId().equals(request.workerId())) {
            throw new ApiException(HttpStatus.CONFLICT, "Action is not assigned to worker: " + request.workerId());
        }

        ActionStatus terminalStatus = parseTerminalStatus(request.status());
        LocalDateTime now = LocalDateTime.now();
        action.setStatus(terminalStatus.name());
        action.setErrorMessage(request.errorMessage());
        if (terminalStatus == ActionStatus.FAILED) {
            action.setRetryCount(action.getRetryCount() == null ? 1 : action.getRetryCount() + 1);
        }
        action.setUpdatedAt(now);
        actionMapper.updateById(action);

        ActionLogEntity actionLog = new ActionLogEntity();
        actionLog.setActionId(action.getId());
        actionLog.setWorkerId(request.workerId());
        actionLog.setResult(request.result());
        actionLog.setStatus(terminalStatus.name());
        actionLog.setCreatedAt(now);
        actionLogMapper.insert(actionLog);

        actionQueueService.releaseLock(action.getId());

        if (terminalStatus == ActionStatus.SUCCEEDED) {
            triggerDownstreamActions(action);
        }

        workflowService.refreshStatus(action.getWorkflowId());
        return toResponse(actionMapper.selectById(action.getId()));
    }

    private ActionEntity requireAction(Long actionId) {
        ActionEntity action = actionMapper.selectById(actionId);
        if (action == null) {
            throw new ApiException(HttpStatus.NOT_FOUND, "Action not found: " + actionId);
        }
        return action;
    }

    private void validateUpstreamActions(Long workflowId, List<Long> upstreamActionIds) {
        if (upstreamActionIds.isEmpty()) {
            return;
        }

        List<ActionEntity> upstreamActions = actionMapper.selectBatchIds(upstreamActionIds);
        if (upstreamActions.size() != upstreamActionIds.size()) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "Some upstream actions do not exist");
        }

        boolean crossWorkflowDependency = upstreamActions.stream()
                .anyMatch(action -> !workflowId.equals(action.getWorkflowId()));
        if (crossWorkflowDependency) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "Upstream actions must belong to the same workflow");
        }
    }

    private List<Long> normalizeUpstreamActionIds(List<Long> upstreamActionIds) {
        if (upstreamActionIds == null) {
            return List.of();
        }
        return upstreamActionIds.stream()
                .filter(id -> id != null && id > 0)
                .distinct()
                .toList();
    }

    private ActionStatus parseTerminalStatus(String rawStatus) {
        try {
            ActionStatus status = ActionStatus.valueOf(rawStatus.trim().toUpperCase());
            if (!status.isTerminal()) {
                throw new ApiException(HttpStatus.BAD_REQUEST, "Result status must be SUCCEEDED or FAILED");
            }
            return status;
        } catch (IllegalArgumentException exception) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "Unsupported result status: " + rawStatus);
        }
    }

    private void triggerDownstreamActions(ActionEntity completedAction) {
        List<ActionDependencyEntity> downstreamDependencies = actionDependencyMapper.selectList(
                new LambdaQueryWrapper<ActionDependencyEntity>()
                        .eq(ActionDependencyEntity::getUpstreamActionId, completedAction.getId())
        );

        Set<Long> downstreamActionIds = downstreamDependencies.stream()
                .map(ActionDependencyEntity::getDownstreamActionId)
                .collect(java.util.stream.Collectors.toCollection(LinkedHashSet::new));

        for (Long downstreamActionId : downstreamActionIds) {
            if (!allDependenciesSucceeded(downstreamActionId)) {
                continue;
            }
            ActionEntity downstreamAction = actionMapper.selectById(downstreamActionId);
            if (downstreamAction == null || !ActionStatus.BLOCKED.name().equals(downstreamAction.getStatus())) {
                continue;
            }

            downstreamAction.setStatus(ActionStatus.QUEUED.name());
            downstreamAction.setUpdatedAt(LocalDateTime.now());
            actionMapper.updateById(downstreamAction);
            actionQueueService.enqueue(downstreamAction);
        }
    }

    private boolean allDependenciesSucceeded(Long downstreamActionId) {
        List<ActionDependencyEntity> dependencies = actionDependencyMapper.selectList(
                new LambdaQueryWrapper<ActionDependencyEntity>()
                        .eq(ActionDependencyEntity::getDownstreamActionId, downstreamActionId)
        );
        if (dependencies.isEmpty()) {
            return true;
        }

        List<Long> upstreamIds = dependencies.stream()
                .map(ActionDependencyEntity::getUpstreamActionId)
                .toList();
        List<ActionEntity> upstreamActions = actionMapper.selectBatchIds(upstreamIds);
        return upstreamActions.size() == upstreamIds.size()
                && upstreamActions.stream()
                .allMatch(action -> ActionStatus.SUCCEEDED.name().equals(action.getStatus()));
    }

    private List<Long> loadUpstreamActionIds(Long actionId) {
        return actionDependencyMapper.selectList(new LambdaQueryWrapper<ActionDependencyEntity>()
                        .eq(ActionDependencyEntity::getDownstreamActionId, actionId))
                .stream()
                .map(ActionDependencyEntity::getUpstreamActionId)
                .toList();
    }

    private ActionResponse toResponse(ActionEntity action) {
        return new ActionResponse(
                action.getId(),
                action.getWorkflowId(),
                action.getType(),
                action.getStatus(),
                action.getWorkerId(),
                action.getRetryCount(),
                action.getPayload(),
                action.getErrorMessage(),
                loadUpstreamActionIds(action.getId()),
                action.getCreatedAt(),
                action.getUpdatedAt()
        );
    }
}