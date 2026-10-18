/*
 * Copyright 2024-2026 the original author or authors.
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
package com.alibaba.cloud.ai.dataagent.workflow.node;

import com.alibaba.cloud.ai.dataagent.dto.prompt.QueryEnhanceOutputDTO;
import com.alibaba.cloud.ai.dataagent.enums.TextType;
import com.alibaba.cloud.ai.dataagent.util.*;
import com.alibaba.cloud.ai.graph.GraphResponse;
import com.alibaba.cloud.ai.graph.OverAllState;
import com.alibaba.cloud.ai.graph.action.NodeAction;
import com.alibaba.cloud.ai.graph.streaming.StreamingOutput;
import com.alibaba.cloud.ai.dataagent.prompt.PromptHelper;
import com.alibaba.cloud.ai.dataagent.service.llm.LlmService;
import lombok.AllArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Flux;

import java.util.Map;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.atomic.AtomicInteger;
import reactor.util.retry.Retry;
import com.alibaba.cloud.ai.dataagent.service.evaluation.EvaluationCapture;

import static com.alibaba.cloud.ai.dataagent.constant.Constant.*;

/**
 * 查询丰富节点，用于根据evidence信息把业务翻译。查询改写，扩展。 此节点不需要提取关键词，如果混合检索，如es等库会自行分词并计算相关性。
 */
@Slf4j
@Component
@AllArgsConstructor
public class QueryEnhanceNode implements NodeAction {

	private final LlmService llmService;

	@Override
	public Map<String, Object> apply(OverAllState state) throws Exception {

		// 获取用户输入
		String userInput = StateUtil.getStringValue(state, INPUT_KEY);
		log.debug("User input for query enhance: {}", userInput);

		String evidence = StateUtil.getStringValue(state, EVIDENCE);
		String multiTurn = StateUtil.getStringValue(state, MULTI_TURN_CONTEXT, "(无)");

		// 构建查询处理提示
		String prompt = PromptHelper.buildQueryEnhancePrompt(multiTurn, userInput, evidence);
		log.debug("Built query enhance prompt as follows \n {} \n", prompt);

		// 调用LLM进行查询处理
		AtomicInteger attempt = new AtomicInteger();
		Flux<ChatResponse> responseFlux = Flux.defer(() -> {
			int currentAttempt = attempt.incrementAndGet();
			int budget = currentAttempt == 1 ? 4096 : 8192;
			return llmService.callUser(prompt, budget).collectList().flatMapMany(responses -> {
				String raw = responses.stream().map(ChatResponseUtil::getText).collect(java.util.stream.Collectors.joining());
				List<String> reasons = responses.stream().flatMap(r -> r.getResults().stream())
					.map(r -> r.getMetadata().getFinishReason()).filter(Objects::nonNull).filter(r -> !r.isBlank()).distinct().toList();
				EvaluationCapture.queryEnhance(state.value(TRACE_THREAD_ID).orElse(null), currentAttempt, raw, reasons, budget);
				try {
					if (reasons.stream().anyMatch(r -> "length".equalsIgnoreCase(r))) {
						throw new IllegalArgumentException("QueryEnhance TRUNCATED_OUTPUT: model reached output limit");
					}
					parseQueryEnhance(raw);
				}
				catch (IllegalArgumentException ex) {
					// Invalid attempts never reach FluxUtil; retain their reported evaluation usage.
					responses.forEach(r -> {
						var usage = r.getMetadata().getUsage();
						if (usage != null && (usage.getPromptTokens() > 0 || usage.getCompletionTokens() > 0)) {
							EvaluationCapture.tokens(state.value(TRACE_THREAD_ID).orElse(null),
									usage.getPromptTokens(), usage.getCompletionTokens());
						}
					});
					throw ex;
				}
				return Flux.fromIterable(responses);
			});
		}).retryWhen(Retry.max(1).filter(IllegalArgumentException.class::isInstance)
			.onRetryExhaustedThrow((spec, signal) -> signal.failure()));

		Flux<GraphResponse<StreamingOutput>> generator = FluxUtil.createStreamingGenerator(this.getClass(), state,
				responseFlux,
				Flux.just(ChatResponseUtil.createResponse("正在进行问题增强..."),
						ChatResponseUtil.createPureResponse(TextType.JSON.getStartSign())),
				Flux.just(ChatResponseUtil.createPureResponse(TextType.JSON.getEndSign()),
						ChatResponseUtil.createResponse("\n问题增强完成！")),
				this::handleQueryEnhance);

		return Map.of(QUERY_ENHANCE_NODE_OUTPUT, generator);
	}

	private Map<String, Object> handleQueryEnhance(String llmOutput) {
		return Map.of(QUERY_ENHANCE_NODE_OUTPUT, parseQueryEnhance(llmOutput));
	}

	private QueryEnhanceOutputDTO parseQueryEnhance(String llmOutput) {
		String text = llmOutput.trim();
		int thinkEnd = text.lastIndexOf("</think>");
		if (thinkEnd >= 0) {
			text = text.substring(thinkEnd + "</think>".length()).trim();
		}
		String result = MarkdownParserUtil.extractRawText(text);
		if (result == null || result.isBlank()) {
			throw new IllegalArgumentException("QueryEnhance returned empty content");
		}
		// Retry the full task with its evidence, rather than repairing JSON without business context.
		QueryEnhanceOutputDTO output;
		try {
			output = JsonUtil.getObjectMapper().readValue(result, QueryEnhanceOutputDTO.class);
		}
		catch (Exception ex) {
			throw new IllegalArgumentException("QueryEnhance returned invalid JSON", ex);
		}
		if (output == null || output.getCanonicalQuery() == null || output.getCanonicalQuery().isBlank()) {
			throw new IllegalArgumentException("QueryEnhance missing canonical_query");
		}
		output.setCanonicalQuery(output.getCanonicalQuery().trim());
		List<String> expanded = output.getExpandedQueries() == null ? List.of()
				: output.getExpandedQueries().stream().filter(Objects::nonNull).map(String::trim)
					.filter(q -> !q.isEmpty()).distinct().toList();
		// Retain legacy optional values without making them a routing prerequisite.
		output.setExpandedQueries(expanded);
		return output;
	}

}
