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
package com.alibaba.cloud.ai.dataagent.controller;

import com.alibaba.cloud.ai.dataagent.dto.GraphRequest;
import com.alibaba.cloud.ai.dataagent.dto.ModelConfigDTO;
import com.alibaba.cloud.ai.dataagent.enums.GraphEventType;
import com.alibaba.cloud.ai.dataagent.enums.ModelType;
import com.alibaba.cloud.ai.dataagent.service.aimodelconfig.ModelConfigDataService;
import com.alibaba.cloud.ai.dataagent.service.evaluation.EvaluationCapture;
import com.alibaba.cloud.ai.dataagent.service.graph.GraphService;
import com.alibaba.cloud.ai.dataagent.vo.GraphNodeResponse;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.time.Duration;
import java.util.*;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Mono;
import reactor.core.publisher.Sinks;

/** Local opt-in evaluation endpoint; regular product traffic does not collect traces. */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/evaluation")
@ConditionalOnProperty(name="data-agent.evaluation.enabled",havingValue="true")
public class EvaluationController {
    private final GraphService graphService;
    private final ModelConfigDataService modelConfigs;

    @org.springframework.beans.factory.annotation.Value("${spring.ai.alibaba.data-agent.vector-store.default-similarity-threshold:0.4}")
    private double retrievalThreshold;

    @org.springframework.beans.factory.annotation.Value("${spring.ai.alibaba.data-agent.max-sql-retry-count:10}")
    private int sqlRetryLimit;

    public record Input(@NotBlank String agentId, @NotBlank @Size(max=20000) String query,
                        Boolean businessKnowledgeEnabled) { }

    @PostMapping("/run")
    public Mono<Map<String,Object>> run(@Valid @RequestBody Input input, ServerHttpRequest httpRequest) {
        if (httpRequest.getRemoteAddress()==null || httpRequest.getRemoteAddress().getAddress()==null
                || !httpRequest.getRemoteAddress().getAddress().isLoopbackAddress()) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN,"Evaluation requires a loopback connection");
        }
        Map<String,Object> models = new LinkedHashMap<>();
        for (ModelType type : List.of(ModelType.CHAT,ModelType.EMBEDDING)) {
            ModelConfigDTO config=modelConfigs.getActiveConfigByType(type);
            if(config!=null) {
                Map<String,Object> m=new LinkedHashMap<>();
                m.put("id",config.getId()); m.put("provider",config.getProvider());
                m.put("model",config.getModelName());m.put("temperature",config.getTemperature());
                m.put("maxTokens",config.getMaxTokens());models.put(type.name(),m);
            }
        }
        GraphRequest request=GraphRequest.builder().agentId(input.agentId()).query(input.query())
            .conversationId(UUID.randomUUID().toString()).nl2sqlOnly(false).evaluation(true)
            .businessKnowledgeEnabled(input.businessKnowledgeEnabled()==null || input.businessKnowledgeEnabled()).build();
        return Mono.defer(() -> {
            Sinks.Many<ServerSentEvent<GraphNodeResponse>> sink=Sinks.many().unicast().onBackpressureBuffer();
            graphService.graphStreamProcess(sink,request);
            return sink.asFlux().filter(e -> e.data()!=null && e.data().getEventType()==GraphEventType.EVALUATION_RESULT)
                .map(e -> e.data().getEvaluation()).next()
                .switchIfEmpty(Mono.fromSupplier(() -> EvaluationCapture.finish(request.getThreadId(),"error","No evaluation terminal event")));
        }).timeout(Duration.ofMinutes(8))
            .onErrorResume(error -> Mono.fromSupplier(() -> {
                Map<String,Object> capture=EvaluationCapture.finish(request.getThreadId(),
                    error instanceof java.util.concurrent.TimeoutException?"timeout":"error",error.toString());
                if(capture.isEmpty()) {
                    capture=new LinkedHashMap<>();capture.put("status","error");capture.put("error",error.toString());
                }
                return capture;
            }))
            .map(capture -> {
                Map<String,Object> result=new LinkedHashMap<>(capture);
                result.put("conversationId",request.getConversationId());result.put("models",models);
                result.put("mode","query_pipeline_without_report");
                result.put("retrievalSettings",Map.of("threshold",retrievalThreshold,"topK",8,"sqlRetryLimit",sqlRetryLimit));
                return result;
            })
            .doFinally(signal -> graphService.stopStreamProcessing(request.getThreadId()));
    }
}
