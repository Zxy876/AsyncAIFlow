package com.asyncaiflow;

import static org.hamcrest.Matchers.hasSize;
import static org.hamcrest.Matchers.is;
import static org.hamcrest.Matchers.notNullValue;
import static org.hamcrest.Matchers.nullValue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.LocalDateTime;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

import com.asyncaiflow.domain.entity.ActionEntity;
import com.asyncaiflow.domain.entity.ActionLogEntity;
import com.asyncaiflow.domain.entity.WorkflowEntity;
import com.asyncaiflow.mapper.ActionLogMapper;
import com.asyncaiflow.mapper.ActionMapper;
import com.asyncaiflow.mapper.WorkflowMapper;

@SpringBootTest(properties = {
        "spring.task.scheduling.enabled=false"
})
@AutoConfigureMockMvc
@ActiveProfiles("local")
class RuntimeObservabilityApiIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private WorkflowMapper workflowMapper;

    @Autowired
    private ActionMapper actionMapper;

    @Autowired
    private ActionLogMapper actionLogMapper;

    @BeforeEach
    void cleanTables() {
        actionLogMapper.delete(null);
        actionMapper.delete(null);
        workflowMapper.delete(null);
    }

    @Test
    void getWorkflowsReturnsLatestWorkflowFirstAndIncludesIssue() throws Exception {
        LocalDateTime base = LocalDateTime.of(2026, 3, 14, 11, 0, 0);
        insertWorkflow(401L, base.minusMinutes(10), "Explain Drift story engine");
        insertWorkflow(402L, base.minusMinutes(2), "Trace auth pipeline");
        insertAction(4001L, 401L, "search_code", "SUCCEEDED", "worker-a", "{}",
                base.minusMinutes(9), base.minusMinutes(9).plusSeconds(5), base.minusMinutes(8), null);
        insertAction(4002L, 402L, "generate_explanation", "RUNNING", "worker-b", "{}",
                base.minusMinutes(1), base.minusMinutes(1).plusSeconds(5), null, null);

        mockMvc.perform(get("/workflows").param("limit", "1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data", hasSize(1)))
                .andExpect(jsonPath("$.data[0].workflowId").value(402))
                .andExpect(jsonPath("$.data[0].status").value("RUNNING"))
                .andExpect(jsonPath("$.data[0].issue").value("Trace auth pipeline"));
    }

    @Test
    void getWorkflowReturnsNormalizedExecutionState() throws Exception {
        LocalDateTime base = LocalDateTime.of(2026, 3, 14, 12, 0, 0);
        insertWorkflow(101L, base.minusMinutes(5), "Explain auth module");
        insertAction(1001L, 101L, "search_code", "SUCCEEDED", "worker-search", "{\"query\":\"auth\"}",
                base.minusMinutes(4), base.minusMinutes(4).plusSeconds(5), base.minusMinutes(3), null);
        insertAction(1002L, 101L, "analyze_module", "SUCCEEDED", "worker-analyze", "{\"module\":\"auth\"}",
                base.minusMinutes(3), base.minusMinutes(3).plusSeconds(5), base.minusMinutes(2), null);
        insertAction(1003L, 101L, "generate_explanation", "RUNNING", "worker-gpt", "{\"topic\":\"auth\"}",
                base.minusMinutes(2), base.minusMinutes(2).plusSeconds(5), null, null);

        mockMvc.perform(get("/workflow/{workflowId}", 101L))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.workflowId").value(101))
                .andExpect(jsonPath("$.data.status").value("RUNNING"))
                .andExpect(jsonPath("$.data.actions", hasSize(3)))
                .andExpect(jsonPath("$.data.actions[0].actionId").value(1001))
                .andExpect(jsonPath("$.data.actions[0].status").value("COMPLETED"))
                .andExpect(jsonPath("$.data.actions[0].finishedAt", notNullValue()))
                .andExpect(jsonPath("$.data.actions[2].status").value("RUNNING"))
                .andExpect(jsonPath("$.data.actions[2].finishedAt").value(nullValue()));
    }

    @Test
    void getWorkflowActionsNormalizesPendingAndFailedStates() throws Exception {
        LocalDateTime base = LocalDateTime.of(2026, 3, 14, 12, 30, 0);
        insertWorkflow(202L, base.minusMinutes(5), "Explain retry state");
        insertAction(2001L, 202L, "search_code", "QUEUED", null, "{}", base.minusMinutes(4), null, null, null);
        insertAction(2002L, 202L, "analyze_module", "RETRY_WAIT", null, "{}", base.minusMinutes(3), null, null, null);
        insertAction(2003L, 202L, "generate_explanation", "DEAD_LETTER", null, "{}", base.minusMinutes(2), null,
                null, base.minusMinutes(1));

        mockMvc.perform(get("/workflow/{workflowId}/actions", 202L))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data", hasSize(3)))
                .andExpect(jsonPath("$.data[0].status").value("PENDING"))
                .andExpect(jsonPath("$.data[1].status").value("PENDING"))
                .andExpect(jsonPath("$.data[2].status").value("FAILED"))
                .andExpect(jsonPath("$.data[2].finishedAt", notNullValue()));
    }

    @Test
    void getActionReturnsStructuredPayloadAndLatestResult() throws Exception {
        LocalDateTime base = LocalDateTime.of(2026, 3, 14, 13, 0, 0);
        insertWorkflow(303L, base.minusMinutes(5), "Explain auth service");
        insertAction(3001L, 303L, "search_code", "SUCCEEDED", "worker-search", "{\"query\":\"auth service\"}",
                base.minusMinutes(4), base.minusMinutes(4).plusSeconds(3), base.minusMinutes(3), null);
        insertActionLog(9001L, 3001L, "worker-search", "{\"summary\":\"stale\"}", "SUCCEEDED",
                base.minusMinutes(3));
        insertActionLog(9002L, 3001L, "worker-search", "{\"summary\":\"fresh\"}", "SUCCEEDED",
                base.minusMinutes(2));

        mockMvc.perform(get("/action/{actionId}", 3001L))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.actionId").value(3001))
                .andExpect(jsonPath("$.data.workflowId").value(303))
                .andExpect(jsonPath("$.data.status").value("COMPLETED"))
                                .andExpect(jsonPath("$.data.workerId").value("worker-search"))
                                .andExpect(jsonPath("$.data.startedAt", notNullValue()))
                                .andExpect(jsonPath("$.data.finishedAt", notNullValue()))
                .andExpect(jsonPath("$.data.payload.query").value("auth service"))
                                .andExpect(jsonPath("$.data.result.summary").value("fresh"))
                                .andExpect(jsonPath("$.data.error").value(nullValue()))
                                .andExpect(jsonPath("$.data.logs", hasSize(2)))
                                .andExpect(jsonPath("$.data.logs[0].status", is("SUCCEEDED")))
                                .andExpect(jsonPath("$.data.logs[1].result.summary").value("fresh"));
    }

        private void insertWorkflow(Long workflowId, LocalDateTime createdAt, String description) {
        WorkflowEntity workflow = new WorkflowEntity();
        workflow.setId(workflowId);
        workflow.setName("workflow-" + workflowId);
                workflow.setDescription(description);
        workflow.setStatus("CREATED");
        workflow.setCreatedAt(createdAt);
        workflow.setUpdatedAt(createdAt);
        workflowMapper.insert(workflow);
    }

    private void insertAction(
            Long actionId,
            Long workflowId,
            String type,
            String status,
            String workerId,
            String payload,
            LocalDateTime createdAt,
                        LocalDateTime claimTime,
            LocalDateTime submitTime,
            LocalDateTime reclaimTime
    ) {
        ActionEntity action = new ActionEntity();
        action.setId(actionId);
        action.setWorkflowId(workflowId);
        action.setType(type);
        action.setStatus(status);
        action.setWorkerId(workerId);
        action.setPayload(payload);
        action.setRetryCount(0);
        action.setMaxRetryCount(3);
        action.setBackoffSeconds(5);
        action.setExecutionTimeoutSeconds(300);
        action.setClaimTime(claimTime);
        action.setSubmitTime(submitTime);
        action.setReclaimTime(reclaimTime);
        action.setLeaseRenewSuccessCount(0);
        action.setLeaseRenewFailureCount(0);
        action.setCreatedAt(createdAt);
        action.setUpdatedAt(createdAt);
        actionMapper.insert(action);
    }

    private void insertActionLog(
            Long logId,
            Long actionId,
            String workerId,
            String result,
            String status,
            LocalDateTime createdAt
    ) {
        ActionLogEntity actionLog = new ActionLogEntity();
        actionLog.setId(logId);
        actionLog.setActionId(actionId);
        actionLog.setWorkerId(workerId);
        actionLog.setResult(result);
        actionLog.setStatus(status);
        actionLog.setCreatedAt(createdAt);
        actionLogMapper.insert(actionLog);
    }
}