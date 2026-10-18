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
import com.alibaba.cloud.ai.dataagent.connector.SqlExecutor;
import com.alibaba.cloud.ai.dataagent.service.langfuse.NodeIoRegistry;
import com.alibaba.cloud.ai.dataagent.util.JsonUtil;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import static com.alibaba.cloud.ai.dataagent.constant.Constant.*;

/** Opt-in run-local evidence, independent of whether external tracing is enabled. */
public final class EvaluationCapture {

    private static final Map<String, EvaluationCapture> ACTIVE = new ConcurrentHashMap<>();
    private final long started = System.nanoTime();
    private final List<Map<String,Object>> queryEnhanceResponses = new ArrayList<>();
    private final List<Map<String,Object>> nodes = new ArrayList<>();
    private final List<Map<String,Object>> executions = new ArrayList<>();
    private final Map<String,Integer> attempts = new HashMap<>();
    private final Map<String,Map<String,Object>> running = new HashMap<>();
    private long promptTokens;
    private long completionTokens;
    private int usageEvents;
    private final boolean knowledgeEnabled;

    private EvaluationCapture(boolean enabled) { this.knowledgeEnabled = enabled; }

    public static void start(String id, boolean enabled) { ACTIVE.put(id, new EvaluationCapture(enabled)); }
    public static boolean enabled(Object id) { return id != null && ACTIVE.containsKey(id.toString()); }
    public static void discard(String id) { if (id != null) ACTIVE.remove(id); }

    private static Object copy(Object value) {
        if (value == null) return null;
        try { return JsonUtil.getObjectMapper().readValue(JsonUtil.getObjectMapper().writeValueAsString(value), Object.class); }
        catch (Exception ex) { return "<unresolved:" + value.getClass().getSimpleName() + ">"; }
    }

    public static void before(String id, String node, Map<String,Object> state) {
        if (id == null) return;
        EvaluationCapture c = ACTIVE.get(id);
        if (c == null) return;
        synchronized (c) {
            Map<String,Object> entry = new LinkedHashMap<>();
            entry.put("node",node); entry.put("attempt",c.attempts.merge(node,1,Integer::sum));
            entry.put("startedNanos",System.nanoTime());
            entry.put("inputs",copy(NodeIoRegistry.extractInputs(node,state)));
            c.running.put(node,entry);
        }
    }

    public static void after(String id, String node, Map<String,Object> state, Throwable error) {
        if (id == null) return;
        EvaluationCapture c = ACTIVE.get(id);
        if (c == null) return;
        synchronized (c) {
            Map<String,Object> entry = c.running.remove(node);
            if (entry == null) return;
            entry.put("elapsedMs",(System.nanoTime()-(long)entry.remove("startedNanos"))/1_000_000);
            entry.put("outputs",copy(NodeIoRegistry.extractOutputs(node,state)));
            entry.put("status",error == null ? "completed" : "error");
            if (error != null) entry.put("error",error.toString());
            c.nodes.add(entry);
        }
    }

    public static void queryEnhance(Object id, int attempt, String raw, List<String> finishReasons) {
        queryEnhance(id, attempt, raw, finishReasons, 0);
    }

    public static void queryEnhance(Object id, int attempt, String raw, List<String> finishReasons, int budget) {
        EvaluationCapture c = id == null ? null : ACTIVE.get(id.toString());
        if (c == null) return;
        synchronized (c) {
            Map<String,Object> entry = new LinkedHashMap<>();
            entry.put("attempt", attempt); entry.put("rawResponse", raw);
            entry.put("finishReasons", List.copyOf(finishReasons));
            if (budget > 0) entry.put("maxTokens", budget);
            c.queryEnhanceResponses.add(entry);
        }
    }

    public static void tokens(Object id, long prompt, long completion) {
        EvaluationCapture c = id == null ? null : ACTIVE.get(id.toString());
        if (c != null) synchronized(c) {
            c.promptTokens += prompt; c.completionTokens += completion; c.usageEvents++;
        }
    }

    public static void sql(Object id, int step, String sql, ResultSetBO result, String error) {
        EvaluationCapture c = id == null ? null : ACTIVE.get(id.toString());
        if (c == null) return;
        synchronized (c) {
            Map<String,Object> entry = new LinkedHashMap<>();
            entry.put("step",step); entry.put("sql",sql); entry.put("status",error==null?"success":"error");
            if (result != null) {
                entry.put("columns",copy(result.getColumn())); entry.put("data",copy(result.getData()));
                // JDBC cap does not prove truncation; conservatively mark boundary-sized results.
                entry.put("possiblyTruncated",result.getData()!=null && result.getData().size()>=SqlExecutor.RESULT_SET_LIMIT);
            }
            if (error != null) entry.put("error",error);
            c.executions.add(entry);
        }
    }

    public static Map<String,Object> finish(String id, String status, String error) {
        EvaluationCapture c = ACTIVE.remove(id);
        if (c == null) return Map.of();
        synchronized (c) {
            Map<String,Object> result = new LinkedHashMap<>();
            result.put("threadId",id); result.put("status",status);
            result.put("businessKnowledgeEnabled",c.knowledgeEnabled);
            result.put("elapsedMs",(System.nanoTime()-c.started)/1_000_000);
            result.put("queryEnhanceResponses",c.queryEnhanceResponses);
            result.put("nodes",c.nodes); result.put("sqlExecutions",c.executions);
            result.put("promptTokens",c.usageEvents==0?null:c.promptTokens);
            result.put("completionTokens",c.usageEvents==0?null:c.completionTokens);
            result.put("usageEvents",c.usageEvents);
            result.put("usageScope","reported streaming usage; internal advisor calls may be unavailable");
            if (error!=null) result.put("error",error);
            return result;
        }
    }
}
