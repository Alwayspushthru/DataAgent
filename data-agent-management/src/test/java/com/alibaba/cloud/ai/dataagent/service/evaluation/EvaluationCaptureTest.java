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
package com.alibaba.cloud.ai.dataagent.service.evaluation;

import com.alibaba.cloud.ai.dataagent.bo.schema.ResultSetBO;
import com.alibaba.cloud.ai.dataagent.dto.GraphRequest;
import java.util.*;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import static com.alibaba.cloud.ai.dataagent.constant.Constant.*;

class EvaluationCaptureTest {
    @Test void requestsDefaultToKnowledgeOn() {
        assertTrue(new GraphRequest().isBusinessKnowledgeEnabled());
        assertTrue(GraphRequest.builder().build().isBusinessKnowledgeEnabled());
    }

    @Test void captureIsIsolatedAndPreservesSqlNulls() {
        String a=UUID.randomUUID().toString(),b=UUID.randomUUID().toString();
        EvaluationCapture.start(a,false);EvaluationCapture.start(b,true);
        Map<String,String> row=new HashMap<>();row.put("value",null);
        EvaluationCapture.sql(a,1,"SELECT SUM(x) value FROM t",ResultSetBO.builder()
            .column(List.of("value")).data(List.of(row)).build(),null);
        EvaluationCapture.tokens(a,12,4);
        EvaluationCapture.queryEnhance(a,1,"",List.of("length"));
        EvaluationCapture.before(a,EVIDENCE_RECALL_NODE,Map.of(INPUT_KEY,"q"));
        EvaluationCapture.after(a,EVIDENCE_RECALL_NODE,Map.of(EVIDENCE,"无"),null);
        Map<String,Object> result=EvaluationCapture.finish(a,"completed",null);
        assertEquals(false,result.get("businessKnowledgeEnabled"));
        assertEquals(List.of(Map.of("attempt",1,"rawResponse","","finishReasons",List.of("length"))),result.get("queryEnhanceResponses"));
        assertEquals(12L,result.get("promptTokens"));
        assertTrue(result.get("sqlExecutions").toString().contains("value=null"));
        assertFalse(EvaluationCapture.enabled(a));
        Map<String,Object> other=EvaluationCapture.finish(b,"error","test");
        assertNull(other.get("promptTokens"));
        assertEquals(List.of(),other.get("queryEnhanceResponses"));
        assertEquals(List.of(),other.get("sqlExecutions"));
    }

    @Test void nullIdsAndUnregisteredRunsAreSafe() {
        EvaluationCapture.before(null,"node",Map.of());EvaluationCapture.after(null,"node",Map.of(),null);
        EvaluationCapture.tokens(null,1,1);EvaluationCapture.sql(null,1,"q",null,"err");
        assertTrue(EvaluationCapture.finish("missing","error",null).isEmpty());
    }
}
