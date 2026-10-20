/*
 * Copyright 2026 the original author or authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package com.alibaba.cloud.ai.dataagent.service.nl2sql;

import com.alibaba.cloud.ai.dataagent.dto.prompt.SemanticConsistencyDTO;
import com.alibaba.cloud.ai.dataagent.dto.prompt.SemanticConsistencyOutputDTO;
import com.alibaba.cloud.ai.dataagent.dto.prompt.SqlGenerationDTO;
import com.alibaba.cloud.ai.dataagent.dto.schema.SchemaDTO;
import com.alibaba.cloud.ai.dataagent.prompt.PromptLoader;
import com.alibaba.cloud.ai.dataagent.service.llm.LlmService;
import com.alibaba.cloud.ai.dataagent.util.ChatResponseUtil;
import com.alibaba.cloud.ai.dataagent.util.JsonParseUtil;
import java.util.List;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.ai.chat.model.ChatResponse;
import reactor.core.publisher.Flux;

import static org.assertj.core.api.Assertions.assertThat;

/** Exercises real prompt rendering and service branches without JVM instrumentation. */
class NumericPrecisionPromptFlowTest {

    @AfterEach
    void clearPrompts() {
        PromptLoader.clearCache();
    }

    @ParameterizedTest
    @ValueSource(strings = { "无", "业务定义：计算当前范围内的占比" })
    void generationIncludesTheSamePrecisionPolicyWithOrWithoutBusinessEvidence(String evidence) {
        RecordingLlm llm = new RecordingLlm();
        Nl2SqlServiceImpl service = new Nl2SqlServiceImpl(llm, new JsonParseUtil(llm));
        SqlGenerationDTO request = request(evidence);

        assertThat(service.generateSql(request).collectList().block()).containsExactly(RecordingLlm.SQL);
        assertThat(llm.path).isEqualTo("system");
        assertPolicy(llm.prompt, evidence);
    }

    @ParameterizedTest
    @ValueSource(strings = { "无", "业务定义：计算当前范围内的占比" })
    void repairPreservesThePrecisionPolicyAndActualFailureContext(String evidence) {
        RecordingLlm llm = new RecordingLlm();
        Nl2SqlServiceImpl service = new Nl2SqlServiceImpl(llm, new JsonParseUtil(llm));
        SqlGenerationDTO request = request(evidence);
        request.setSql("SELECT 1 / 3");
        request.setExceptionMessage("ratio precision insufficient");

        assertThat(service.generateSql(request).collectList().block()).containsExactly(RecordingLlm.SQL);
        assertThat(llm.path).isEqualTo("user");
        assertPolicy(llm.prompt, evidence);
        assertThat(llm.prompt).contains("SELECT 1 / 3", "ratio precision insufficient");
    }

    @ParameterizedTest
    @ValueSource(strings = { "无", "业务定义：计算当前范围内的占比" })
    void semanticAuditReceivesPrecisionRulesAndTheUnmodifiedCandidateSql(String evidence) {
        RecordingLlm llm = new RecordingLlm();
        Nl2SqlServiceImpl service = new Nl2SqlServiceImpl(llm, new JsonParseUtil(llm));
        SemanticConsistencyDTO request = SemanticConsistencyDTO.builder().dialect("mysql")
            .sql("SELECT 1 / 3").schemaInfo("test_schema").executionDescription("计算占比")
            .userQuery("计算占比").evidence(evidence).build();

        assertThat(service.performSemanticConsistency(request).collectList().block()).hasSize(1);
        assertThat(llm.path).isEqualTo("structured");
        assertThat(llm.outputType).isEqualTo(SemanticConsistencyOutputDTO.class);
        assertPolicy(llm.prompt, evidence);
        assertThat(llm.prompt).contains("SELECT 1 / 3");
    }

    private static SqlGenerationDTO request(String evidence) {
        SchemaDTO schema = new SchemaDTO();
        schema.setName("test_schema");
        schema.setTable(List.of());
        return SqlGenerationDTO.builder().dialect("mysql").schemaDTO(schema).query("计算占比")
            .executionDescription("计算占比").evidence(evidence).build();
    }

    private static void assertPolicy(String prompt, String evidence) {
        assertThat(prompt).contains(PromptLoader.loadPrompt("sql-numeric-precision"), evidence)
            .doesNotContain("{numeric_precision_rules}");
    }

    private static final class RecordingLlm implements LlmService {
        private static final String SQL = "SELECT CAST(1 AS DECIMAL(30,12)) / NULLIF(3, 0)";
        private String prompt;
        private String path;
        private Class<?> outputType;

        private Flux<ChatResponse> record(String value, String route) {
            prompt = value;
            path = route;
            return Flux.just(ChatResponseUtil.createPureResponse(SQL));
        }

        @Override public Flux<ChatResponse> callSystem(String system) { return record(system, "system"); }
        @Override public Flux<ChatResponse> callUser(String user) { return record(user, "user"); }
        @Override public Flux<ChatResponse> callUser(String user, Class<?> type) {
            outputType = type;
            return record(user, "structured");
        }
        @Override public Flux<ChatResponse> call(String system, String user) { throw new AssertionError("Unexpected route"); }
        @Override public Flux<ChatResponse> call(String system, String user, Class<?> type) { throw new AssertionError("Unexpected route"); }
        @Override public Flux<ChatResponse> callUser(String user, int maxTokens) { throw new AssertionError("Unexpected route"); }
    }
}
