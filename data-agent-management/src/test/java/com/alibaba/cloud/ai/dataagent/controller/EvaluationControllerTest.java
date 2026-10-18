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
import com.alibaba.cloud.ai.dataagent.service.aimodelconfig.ModelConfigDataService;
import com.alibaba.cloud.ai.dataagent.service.evaluation.EvaluationCapture;
import com.alibaba.cloud.ai.dataagent.service.graph.GraphService;
import com.alibaba.cloud.ai.dataagent.vo.GraphNodeResponse;
import java.net.InetSocketAddress;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Sinks;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class EvaluationControllerTest {
    @Test void runUsesRequestScopedSwitchAndRedactsModelSecrets() {
        GraphService graph=mock(GraphService.class);
        ModelConfigDataService models=mock(ModelConfigDataService.class);
        when(models.getActiveConfigByType(any())).thenReturn(ModelConfigDTO.builder()
            .provider("test").modelName("fixture").apiKey("must-not-leak").build());
        doAnswer(inv -> {
            GraphRequest request=inv.getArgument(1);
            assertFalse(request.isBusinessKnowledgeEnabled());assertTrue(request.isEvaluation());
            assertFalse(request.isNl2sqlOnly());assertNotNull(request.getConversationId());
            request.setThreadId("fixture");
            Sinks.Many<ServerSentEvent<GraphNodeResponse>> sink=inv.getArgument(0);
            sink.tryEmitNext(ServerSentEvent.builder(GraphNodeResponse.builder()
                .eventType(GraphEventType.EVALUATION_RESULT).evaluation(Map.of("status","completed")).build()).build());
            sink.tryEmitComplete();return null;
        }).when(graph).graphStreamProcess(any(),any());
        ServerHttpRequest http=mock(ServerHttpRequest.class);
        when(http.getRemoteAddress()).thenReturn(new InetSocketAddress("127.0.0.1",10));
        Map<String,Object> result=new EvaluationController(graph,models).run(new EvaluationController.Input("1","q",false),http).block();
        assertEquals("completed",result.get("status"));assertFalse(result.toString().contains("must-not-leak"));
    }

    @Test void remoteRequestsAreRejectedBeforeCallingGraph() {
        GraphService graph=mock(GraphService.class);
        ServerHttpRequest http=mock(ServerHttpRequest.class);
        when(http.getRemoteAddress()).thenReturn(new InetSocketAddress("192.0.2.1",10));
        EvaluationController controller=new EvaluationController(graph,mock(ModelConfigDataService.class));
        assertThrows(ResponseStatusException.class,()->controller.run(new EvaluationController.Input("1","q",true),http));
        verifyNoInteractions(graph);
    }

    @Test void graphStartupErrorCleansCapture() {
        GraphService graph=mock(GraphService.class);
        doAnswer(inv -> {
            GraphRequest request=inv.getArgument(1);request.setThreadId("failed-fixture");
            EvaluationCapture.start(request.getThreadId(),true);throw new IllegalStateException("fixture error");
        }).when(graph).graphStreamProcess(any(),any());
        ServerHttpRequest http=mock(ServerHttpRequest.class);
        when(http.getRemoteAddress()).thenReturn(new InetSocketAddress("127.0.0.1",10));
        Map<String,Object> result=new EvaluationController(graph,mock(ModelConfigDataService.class))
            .run(new EvaluationController.Input("1","q",null),http).block();
        assertEquals("error",result.get("status"));assertFalse(EvaluationCapture.enabled("failed-fixture"));
    }
}
