package com.asyncaiflow.service;

import java.time.LocalDateTime;
import java.util.List;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.asyncaiflow.domain.entity.WorkerEntity;
import com.asyncaiflow.domain.enums.WorkerStatus;
import com.asyncaiflow.mapper.WorkerMapper;
import com.asyncaiflow.service.queue.ActionQueueService;
import com.asyncaiflow.support.ApiException;
import com.asyncaiflow.support.JsonCodec;
import com.asyncaiflow.web.dto.RegisterWorkerRequest;
import com.asyncaiflow.web.dto.WorkerResponse;

@Service
public class WorkerService {

    private final WorkerMapper workerMapper;
    private final JsonCodec jsonCodec;
    private final ActionQueueService actionQueueService;

    public WorkerService(WorkerMapper workerMapper, JsonCodec jsonCodec, ActionQueueService actionQueueService) {
        this.workerMapper = workerMapper;
        this.jsonCodec = jsonCodec;
        this.actionQueueService = actionQueueService;
    }

    @Transactional
    public WorkerResponse register(RegisterWorkerRequest request) {
        LocalDateTime now = LocalDateTime.now();
        List<String> normalizedCapabilities = normalizeCapabilities(request.capabilities());
        if (normalizedCapabilities.isEmpty()) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "Worker capabilities must not be empty");
        }

        WorkerEntity existingWorker = workerMapper.selectById(request.workerId());
        boolean isNewWorker = existingWorker == null;
        WorkerEntity worker = existingWorker == null ? new WorkerEntity() : existingWorker;
        if (isNewWorker) {
            worker = new WorkerEntity();
            worker.setId(request.workerId());
            worker.setCreatedAt(now);
        }

        worker.setCapabilities(jsonCodec.write(normalizedCapabilities));
        worker.setStatus(WorkerStatus.ONLINE.name());
        worker.setLastHeartbeat(now);
        worker.setUpdatedAt(now);

        if (isNewWorker) {
            workerMapper.insert(worker);
        } else {
            workerMapper.updateById(worker);
        }

        actionQueueService.refreshHeartbeat(worker.getId());
        return toResponse(worker);
    }

    public WorkerEntity requireWorker(String workerId) {
        WorkerEntity worker = workerMapper.selectById(workerId);
        if (worker == null) {
            throw new ApiException(HttpStatus.NOT_FOUND, "Worker not found: " + workerId);
        }
        return worker;
    }

    @Transactional
    public WorkerEntity touchHeartbeat(String workerId) {
        WorkerEntity worker = requireWorker(workerId);
        LocalDateTime now = LocalDateTime.now();
        worker.setStatus(WorkerStatus.ONLINE.name());
        worker.setLastHeartbeat(now);
        worker.setUpdatedAt(now);
        workerMapper.updateById(worker);
        actionQueueService.refreshHeartbeat(workerId);
        return worker;
    }

    public List<String> readCapabilities(WorkerEntity worker) {
        return normalizeCapabilities(jsonCodec.readList(worker.getCapabilities(), String.class));
    }

    public WorkerResponse toResponse(WorkerEntity worker) {
        return new WorkerResponse(
                worker.getId(),
                readCapabilities(worker),
                worker.getStatus(),
                worker.getLastHeartbeat()
        );
    }

    private List<String> normalizeCapabilities(List<String> capabilities) {
        return capabilities.stream()
                .filter(capability -> capability != null && !capability.isBlank())
                .map(String::trim)
                .distinct()
                .toList();
    }
}