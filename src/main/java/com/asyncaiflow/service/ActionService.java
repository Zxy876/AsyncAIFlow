package com.asyncaiflow.service;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;

import org.springframework.beans.factory.annotation.Value;
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
import com.asyncaiflow.support.RuntimeStatusView;
import com.asyncaiflow.web.dto.ActionAssignmentResponse;
import com.asyncaiflow.web.dto.ActionExecutionResponse;
import com.asyncaiflow.web.dto.ActionLogEntryResponse;
import com.asyncaiflow.web.dto.ActionResponse;
import com.asyncaiflow.web.dto.CreateActionRequest;
import com.asyncaiflow.web.dto.SubmitActionResultRequest;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;

@Service
public class ActionService {

    private final ActionMapper actionMapper;
    private final ActionDependencyMapper actionDependencyMapper;
    private final ActionLogMapper actionLogMapper;
    private final ActionCapabilityResolver actionCapabilityResolver;
    private final WorkflowService workflowService;
    private final WorkerService workerService;
    private final ActionQueueService actionQueueService;
    private final ObjectMapper objectMapper;

    @Value("${asyncaiflow.action.default-max-retry-count:3}")
    private int defaultMaxRetryCount;

    @Value("${asyncaiflow.action.default-backoff-seconds:5}")
    private int defaultBackoffSeconds;

    @Value("${asyncaiflow.action.default-execution-timeout-seconds:300}")
    private int defaultExecutionTimeoutSeconds;

    public ActionService(
            ActionMapper actionMapper,
            ActionDependencyMapper actionDependencyMapper,
            ActionLogMapper actionLogMapper,
            ActionCapabilityResolver actionCapabilityResolver,
            WorkflowService workflowService,
            WorkerService workerService,
            ActionQueueService actionQueueService,
            ObjectMapper objectMapper
    ) {
        this.actionMapper = actionMapper;
        this.actionDependencyMapper = actionDependencyMapper;
        this.actionLogMapper = actionLogMapper;
        this.actionCapabilityResolver = actionCapabilityResolver;
        this.workflowService = workflowService;
        this.workerService = workerService;
        this.actionQueueService = actionQueueService;
        this.objectMapper = objectMapper;
    }

    public ActionExecutionResponse getActionExecution(Long actionId) {
        ActionEntity action = requireAction(actionId);
        List<ActionLogEntity> actionLogs = loadActionLogs(actionId);
        ActionLogEntity latestLog = actionLogs.isEmpty() ? null : actionLogs.get(actionLogs.size() - 1);
        String status = RuntimeStatusView.actionStatus(action.getStatus());
        return new ActionExecutionResponse(
                action.getId(),
                action.getWorkflowId(),
                action.getType(),
            status,
            action.getWorkerId(),
            resolveStartedAt(action),
            resolveFinishedAt(status, action),
                parseJsonContent(action.getPayload()),
            latestLog == null ? null : parseJsonContent(latestLog.getResult()),
            action.getErrorMessage(),
            actionLogs.stream().map(this::toActionLogEntry).toList()
        );
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
        action.setMaxRetryCount(normalizeNonNegative(request.maxRetryCount(), defaultMaxRetryCount));
        action.setBackoffSeconds(normalizeNonNegative(request.backoffSeconds(), defaultBackoffSeconds));
        action.setExecutionTimeoutSeconds(normalizePositive(request.executionTimeoutSeconds(), defaultExecutionTimeoutSeconds));
        action.setLeaseExpireAt(null);
        action.setNextRunAt(null);
        action.setClaimTime(null);
        action.setFirstRenewTime(null);
        action.setLastRenewTime(null);
        action.setSubmitTime(null);
        action.setReclaimTime(null);
        action.setLeaseRenewSuccessCount(0);
        action.setLeaseRenewFailureCount(0);
        action.setLastLeaseRenewAt(null);
        action.setExecutionStartedAt(null);
        action.setLastExecutionDurationMs(null);
        action.setLastReclaimReason(null);
        action.setCreatedAt(now);
        action.setUpdatedAt(now);

        String requiredCapability = actionCapabilityResolver.resolveRequiredCapability(action.getType());
        if (requiredCapability.isBlank()) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "Action type resolves to empty capability: " + action.getType());
        }

        actionMapper.insert(action);

        for (Long upstreamActionId : upstreamActionIds) {
            ActionDependencyEntity dependency = new ActionDependencyEntity();
            dependency.setWorkflowId(workflow.getId());
            dependency.setUpstreamActionId(upstreamActionId);
            dependency.setDownstreamActionId(action.getId());
            actionDependencyMapper.insert(dependency);
        }

        if (upstreamActionIds.isEmpty()) {
            actionQueueService.enqueue(action, requiredCapability);
        } else if (allDependenciesSucceeded(action.getId())) {
            transitionState(action, ActionStatus.QUEUED);
            action.setUpdatedAt(LocalDateTime.now());
            actionMapper.updateById(action);
            actionQueueService.enqueue(action, requiredCapability);
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

            String requiredCapability = actionCapabilityResolver.resolveRequiredCapability(action.getType());
            if (requiredCapability.isBlank() || !capabilities.contains(requiredCapability)) {
                actionQueueService.releaseLock(candidateActionId.get());
                continue;
            }

            transitionState(action, ActionStatus.RUNNING);
            LocalDateTime now = LocalDateTime.now();
            int executionTimeoutSeconds = normalizePositive(action.getExecutionTimeoutSeconds(), defaultExecutionTimeoutSeconds);
            action.setWorkerId(workerId);
            action.setLeaseExpireAt(now.plusSeconds(executionTimeoutSeconds));
            action.setNextRunAt(null);
            action.setClaimTime(now);
            action.setFirstRenewTime(null);
            action.setLastRenewTime(null);
            action.setSubmitTime(null);
            action.setReclaimTime(null);
            action.setExecutionStartedAt(now);
            action.setLastExecutionDurationMs(null);
            action.setLastReclaimReason(null);
            action.setUpdatedAt(now);
            actionMapper.updateById(action);
            actionQueueService.refreshActionLock(action.getId(), workerId, executionTimeoutSeconds);
            workflowService.refreshStatus(action.getWorkflowId());

            return Optional.of(new ActionAssignmentResponse(
                    action.getId(),
                    action.getWorkflowId(),
                    action.getType(),
                    action.getPayload(),
                    action.getRetryCount(),
                    action.getLeaseExpireAt()
            ));
        }

        return Optional.empty();
    }

    @Transactional
    public ActionResponse submitResult(SubmitActionResultRequest request) {
        workerService.touchHeartbeat(request.workerId());
        ActionEntity action = requireAction(request.actionId());
        ActionStatus currentStatus = parseActionStatus(action.getStatus());
        if (currentStatus != ActionStatus.RUNNING) {
            if (isSafeDuplicateResult(action)) {
                return toResponse(action);
            }
            throw new ApiException(HttpStatus.CONFLICT, "Action is not in RUNNING status: " + action.getId());
        }

        if (action.getWorkerId() == null || !action.getWorkerId().equals(request.workerId())) {
            throw new ApiException(HttpStatus.CONFLICT, "Action is not assigned to worker: " + request.workerId());
        }

        ActionStatus resultOutcome = parseResultOutcome(request.status());
        LocalDateTime now = LocalDateTime.now();

        // Ignore stale submission if lease already expired. Expired leases are reclaimed by scheduler loop.
        if (action.getLeaseExpireAt() != null && action.getLeaseExpireAt().isBefore(now)) {
            return toResponse(action);
        }

        if (resultOutcome == ActionStatus.SUCCEEDED) {
            transitionState(action, ActionStatus.SUCCEEDED);
            action.setErrorMessage(request.errorMessage());
            action.setLeaseExpireAt(null);
            action.setNextRunAt(null);
            action.setSubmitTime(now);
            action.setReclaimTime(null);
            completeExecutionAttempt(action, now);
            action.setLastReclaimReason(null);
            action.setUpdatedAt(now);
            actionMapper.updateById(action);

            recordActionLog(action.getId(), request.workerId(), request.result(), ActionStatus.SUCCEEDED.name(), now);
            actionQueueService.releaseLock(action.getId());
            triggerDownstreamActions(action);
            workflowService.refreshStatus(action.getWorkflowId());
            return toResponse(actionMapper.selectById(action.getId()));
        }

        String failureMessage = (request.errorMessage() == null || request.errorMessage().isBlank())
            ? "Worker execution failed"
            : request.errorMessage();

        action.setSubmitTime(now);
        action.setReclaimTime(null);

        applyFailureWithRetry(
                action,
                now,
                request.workerId(),
                request.result(),
                failureMessage,
                ActionStatus.FAILED.name(),
                ActionStatus.FAILED,
                null
        );

        workflowService.refreshStatus(action.getWorkflowId());
        return toResponse(actionMapper.selectById(action.getId()));
    }

    @Transactional(noRollbackFor = ApiException.class)
    public ActionResponse renewLease(Long actionId, String workerId) {
        workerService.touchHeartbeat(workerId);
        ActionEntity action = requireAction(actionId);
        LocalDateTime now = LocalDateTime.now();

        ActionStatus currentStatus = parseActionStatus(action.getStatus());
        if (currentStatus != ActionStatus.RUNNING) {
            maybeMarkRenewFailure(action, workerId, now);
            throw new ApiException(HttpStatus.CONFLICT, "Action is not in RUNNING status: " + action.getId());
        }
        if (action.getWorkerId() == null || !action.getWorkerId().equals(workerId)) {
            throw new ApiException(HttpStatus.CONFLICT, "Action is not assigned to worker: " + workerId);
        }

        if (action.getLeaseExpireAt() != null && action.getLeaseExpireAt().isBefore(now)) {
            markRenewFailure(action);
            action.setUpdatedAt(now);
            actionMapper.updateById(action);
            throw new ApiException(HttpStatus.CONFLICT, "Action lease already expired: " + action.getId());
        }

        int executionTimeoutSeconds = normalizePositive(action.getExecutionTimeoutSeconds(), defaultExecutionTimeoutSeconds);
        action.setLeaseExpireAt(now.plusSeconds(executionTimeoutSeconds));
        markRenewSuccess(action, now);
        action.setUpdatedAt(now);
        actionMapper.updateById(action);
        actionQueueService.refreshActionLock(action.getId(), workerId, executionTimeoutSeconds);

        return toResponse(actionMapper.selectById(action.getId()));
    }

    @Transactional
    public int reclaimExpiredLeases() {
        LocalDateTime now = LocalDateTime.now();
        List<ActionEntity> expiredRunningActions = actionMapper.selectList(new LambdaQueryWrapper<ActionEntity>()
                .eq(ActionEntity::getStatus, ActionStatus.RUNNING.name())
                .isNotNull(ActionEntity::getLeaseExpireAt)
                .le(ActionEntity::getLeaseExpireAt, now));

        int reclaimedCount = 0;
        Set<Long> impactedWorkflows = new HashSet<>();
        for (ActionEntity action : expiredRunningActions) {
            ActionEntity latest = actionMapper.selectById(action.getId());
            if (latest == null) {
                continue;
            }
            if (!ActionStatus.RUNNING.name().equals(latest.getStatus())) {
                continue;
            }
            if (latest.getLeaseExpireAt() == null || latest.getLeaseExpireAt().isAfter(now)) {
                continue;
            }

            applyFailureWithRetry(
                    latest,
                    now,
                    latest.getWorkerId(),
                    "lease timeout",
                    "Action lease expired before worker result submission",
                    "TIMEOUT",
                    ActionStatus.DEAD_LETTER,
                    "LEASE_EXPIRED"
            );

            impactedWorkflows.add(latest.getWorkflowId());
            reclaimedCount++;
        }

        for (Long workflowId : impactedWorkflows) {
            workflowService.refreshStatus(workflowId);
        }
        return reclaimedCount;
    }

    @Transactional
    public int enqueueDueRetries() {
        LocalDateTime now = LocalDateTime.now();
        List<ActionEntity> dueRetries = actionMapper.selectList(new LambdaQueryWrapper<ActionEntity>()
                .eq(ActionEntity::getStatus, ActionStatus.RETRY_WAIT.name())
                .isNotNull(ActionEntity::getNextRunAt)
                .le(ActionEntity::getNextRunAt, now));

        int enqueuedCount = 0;
        Set<Long> impactedWorkflows = new HashSet<>();
        for (ActionEntity action : dueRetries) {
            ActionEntity latest = actionMapper.selectById(action.getId());
            if (latest == null) {
                continue;
            }
            if (!ActionStatus.RETRY_WAIT.name().equals(latest.getStatus())) {
                continue;
            }
            if (latest.getNextRunAt() == null || latest.getNextRunAt().isAfter(now)) {
                continue;
            }

            transitionState(latest, ActionStatus.QUEUED);
            latest.setWorkerId(null);
            latest.setLeaseExpireAt(null);
            latest.setNextRunAt(null);
            latest.setUpdatedAt(now);
            actionMapper.updateById(latest);
                actionQueueService.enqueue(
                    latest,
                    actionCapabilityResolver.resolveRequiredCapability(latest.getType()));
            impactedWorkflows.add(latest.getWorkflowId());
            enqueuedCount++;
        }

        for (Long workflowId : impactedWorkflows) {
            workflowService.refreshStatus(workflowId);
        }
        return enqueuedCount;
    }

    private ActionEntity requireAction(Long actionId) {
        ActionEntity action = actionMapper.selectById(actionId);
        if (action == null) {
            throw new ApiException(HttpStatus.NOT_FOUND, "Action not found: " + actionId);
        }
        return action;
    }

    private List<ActionLogEntity> loadActionLogs(Long actionId) {
        return actionLogMapper.selectList(new LambdaQueryWrapper<ActionLogEntity>()
                .eq(ActionLogEntity::getActionId, actionId)
                .orderByAsc(ActionLogEntity::getCreatedAt)
                .orderByAsc(ActionLogEntity::getId));
    }

    private Object parseJsonContent(String rawJson) {
        if (rawJson == null || rawJson.isBlank()) {
            return null;
        }
        try {
            return objectMapper.readValue(rawJson, Object.class);
        } catch (JsonProcessingException exception) {
            return rawJson;
        }
    }

    private LocalDateTime resolveStartedAt(ActionEntity action) {
        if (action.getExecutionStartedAt() != null) {
            return action.getExecutionStartedAt();
        }
        return action.getClaimTime();
    }

    private LocalDateTime resolveFinishedAt(String status, ActionEntity action) {
        if (!"COMPLETED".equals(status) && !"FAILED".equals(status)) {
            return null;
        }
        if (action.getSubmitTime() != null) {
            return action.getSubmitTime();
        }
        return action.getReclaimTime();
    }

    private ActionLogEntryResponse toActionLogEntry(ActionLogEntity actionLog) {
        return new ActionLogEntryResponse(
                actionLog.getWorkerId(),
                actionLog.getStatus(),
                actionLog.getCreatedAt(),
                parseJsonContent(actionLog.getResult())
        );
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

    private ActionStatus parseResultOutcome(String rawStatus) {
        try {
            ActionStatus status = ActionStatus.valueOf(rawStatus.trim().toUpperCase());
            if (status != ActionStatus.SUCCEEDED && status != ActionStatus.FAILED) {
                throw new ApiException(HttpStatus.BAD_REQUEST, "Result status must be SUCCEEDED or FAILED");
            }
            return status;
        } catch (IllegalArgumentException exception) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "Unsupported result status: " + rawStatus);
        }
    }

    private ActionStatus parseActionStatus(String rawStatus) {
        try {
            return ActionStatus.valueOf(rawStatus);
        } catch (Exception exception) {
            throw new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "Unknown action status: " + rawStatus);
        }
    }

    private boolean isSafeDuplicateResult(ActionEntity action) {
        ActionStatus status = parseActionStatus(action.getStatus());
        return status.isTerminal() || status == ActionStatus.RETRY_WAIT || status == ActionStatus.QUEUED;
    }

    private void applyFailureWithRetry(
            ActionEntity action,
            LocalDateTime now,
            String workerId,
            String result,
            String failureMessage,
            String logStatus,
            ActionStatus terminalStatusWhenExhausted,
            String reclaimReason
    ) {
        int nextRetryCount = normalizeNonNegative(action.getRetryCount(), 0) + 1;
        int maxRetryCount = normalizeNonNegative(action.getMaxRetryCount(), defaultMaxRetryCount);

        action.setRetryCount(nextRetryCount);
        action.setErrorMessage(failureMessage);
        action.setLeaseExpireAt(null);
        if (reclaimReason == null || reclaimReason.isBlank()) {
            action.setLastReclaimReason(null);
            action.setReclaimTime(null);
        } else {
            action.setLastReclaimReason(reclaimReason);
            action.setReclaimTime(now);
            action.setSubmitTime(null);
        }
        completeExecutionAttempt(action, now);
        action.setWorkerId(null);
        action.setUpdatedAt(now);
        actionQueueService.releaseLock(action.getId());

        if (nextRetryCount <= maxRetryCount) {
            transitionState(action, ActionStatus.RETRY_WAIT);
            long delaySeconds = computeBackoffSeconds(action.getBackoffSeconds(), nextRetryCount);
            action.setNextRunAt(now.plusSeconds(delaySeconds));
        } else {
            transitionState(action, terminalStatusWhenExhausted);
            action.setNextRunAt(null);
        }

        actionMapper.updateById(action);
        recordActionLog(action.getId(), workerId, result, logStatus, now);
    }

    private long computeBackoffSeconds(Integer configuredBackoffSeconds, int retryAttempt) {
        long baseSeconds = Math.max(0, configuredBackoffSeconds == null ? defaultBackoffSeconds : configuredBackoffSeconds);
        if (baseSeconds == 0) {
            return 0;
        }

        int exponent = Math.max(0, retryAttempt - 1);
        long multiplier = 1L << Math.min(10, exponent);
        long delay = baseSeconds * multiplier;
        return Math.min(delay, 3600L);
    }

    private void recordActionLog(Long actionId, String workerId, String result, String status, LocalDateTime createdAt) {
        ActionLogEntity actionLog = new ActionLogEntity();
        actionLog.setActionId(actionId);
        actionLog.setWorkerId((workerId == null || workerId.isBlank()) ? "scheduler" : workerId);
        actionLog.setResult(result);
        actionLog.setStatus(status);
        actionLog.setCreatedAt(createdAt);
        actionLogMapper.insert(actionLog);
    }

    private void maybeMarkRenewFailure(ActionEntity action, String workerId, LocalDateTime now) {
        if (action.getWorkerId() != null && action.getWorkerId().equals(workerId)) {
            markRenewFailure(action);
            action.setUpdatedAt(now);
            actionMapper.updateById(action);
        }
    }

    private void markRenewSuccess(ActionEntity action, LocalDateTime now) {
        action.setLeaseRenewSuccessCount(normalizeNonNegative(action.getLeaseRenewSuccessCount(), 0) + 1);
        if (action.getFirstRenewTime() == null) {
            action.setFirstRenewTime(now);
        }
        action.setLastRenewTime(now);
        action.setLastLeaseRenewAt(now);
    }

    private void markRenewFailure(ActionEntity action) {
        action.setLeaseRenewFailureCount(normalizeNonNegative(action.getLeaseRenewFailureCount(), 0) + 1);
    }

    private void completeExecutionAttempt(ActionEntity action, LocalDateTime completedAt) {
        if (action.getExecutionStartedAt() == null) {
            action.setLastExecutionDurationMs(0L);
            return;
        }

        long durationMs = Math.max(0L, Duration.between(action.getExecutionStartedAt(), completedAt).toMillis());
        action.setLastExecutionDurationMs(durationMs);
        action.setExecutionStartedAt(null);
    }

    private void transitionState(ActionEntity action, ActionStatus target) {
        ActionStatus current = parseActionStatus(action.getStatus());
        if (current == target) {
            return;
        }
        if (!isValidTransition(current, target)) {
            throw new ApiException(HttpStatus.CONFLICT,
                    "Invalid action state transition: " + current + " -> " + target + " for action " + action.getId());
        }
        action.setStatus(target.name());
    }

    private boolean isValidTransition(ActionStatus from, ActionStatus to) {
        return switch (from) {
            case BLOCKED -> to == ActionStatus.QUEUED;
            case QUEUED -> to == ActionStatus.RUNNING;
            case RUNNING -> to == ActionStatus.SUCCEEDED || to == ActionStatus.FAILED || to == ActionStatus.RETRY_WAIT || to == ActionStatus.DEAD_LETTER;
            case RETRY_WAIT -> to == ActionStatus.QUEUED || to == ActionStatus.DEAD_LETTER;
            case SUCCEEDED, FAILED, DEAD_LETTER -> false;
        };
    }

    private int normalizeNonNegative(Integer value, int fallback) {
        if (value == null) {
            return Math.max(0, fallback);
        }
        return Math.max(0, value);
    }

    private int normalizePositive(Integer value, int fallback) {
        int raw = value == null ? fallback : value;
        return Math.max(1, raw);
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

            transitionState(downstreamAction, ActionStatus.QUEUED);
            downstreamAction.setUpdatedAt(LocalDateTime.now());
            actionMapper.updateById(downstreamAction);
            actionQueueService.enqueue(
                    downstreamAction,
                    actionCapabilityResolver.resolveRequiredCapability(downstreamAction.getType()));
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
                action.getMaxRetryCount(),
                action.getBackoffSeconds(),
                action.getExecutionTimeoutSeconds(),
                action.getLeaseExpireAt(),
                action.getNextRunAt(),
                action.getClaimTime(),
                action.getFirstRenewTime(),
                action.getLastRenewTime(),
                action.getSubmitTime(),
                action.getReclaimTime(),
                action.getLeaseRenewSuccessCount(),
                action.getLeaseRenewFailureCount(),
                action.getLastLeaseRenewAt(),
                action.getExecutionStartedAt(),
                action.getLastExecutionDurationMs(),
                action.getLastReclaimReason(),
                action.getPayload(),
                action.getErrorMessage(),
                loadUpstreamActionIds(action.getId()),
                action.getCreatedAt(),
                action.getUpdatedAt()
        );
    }
}