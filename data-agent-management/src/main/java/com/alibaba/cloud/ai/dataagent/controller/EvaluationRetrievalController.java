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

import com.alibaba.cloud.ai.dataagent.constant.DocumentMetadataConstant;
import com.alibaba.cloud.ai.dataagent.service.vectorstore.AgentVectorStoreService;
import java.util.*;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequiredArgsConstructor
@ConditionalOnProperty(name="data-agent.evaluation.enabled",havingValue="true")
public class EvaluationRetrievalController {
    private final AgentVectorStoreService vectors;

    @PostMapping("/api/evaluation/retrieval")
    public List<Map<String,Object>> retrieval(@RequestBody EvaluationController.Input input,
            @RequestParam(defaultValue="0.0") double threshold,ServerHttpRequest request) {
        if(request.getRemoteAddress()==null || request.getRemoteAddress().getAddress()==null
                || !request.getRemoteAddress().getAddress().isLoopbackAddress()) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN,"Loopback required");
        }
        return vectors.getDocumentsForAgent(input.agentId(),input.query(),DocumentMetadataConstant.BUSINESS_TERM,8,threshold)
            .stream().map(d -> {
                Map<String,Object> row=new LinkedHashMap<>();row.put("id",d.getId());
                row.put("score",d.getScore());row.put("metadata",d.getMetadata());
                row.put("preview",d.getText().substring(0,Math.min(100,d.getText().length())));return row;
            }).toList();
    }
}
