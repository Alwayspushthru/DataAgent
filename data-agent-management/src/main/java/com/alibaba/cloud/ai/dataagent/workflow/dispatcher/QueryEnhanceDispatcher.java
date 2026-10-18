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
package com.alibaba.cloud.ai.dataagent.workflow.dispatcher;

import com.alibaba.cloud.ai.dataagent.dto.prompt.QueryEnhanceOutputDTO;
import com.alibaba.cloud.ai.graph.OverAllState;
import com.alibaba.cloud.ai.graph.action.EdgeAction;
import com.alibaba.cloud.ai.dataagent.util.StateUtil;
import lombok.extern.slf4j.Slf4j;

import static com.alibaba.cloud.ai.dataagent.constant.Constant.QUERY_ENHANCE_NODE_OUTPUT;
import static com.alibaba.cloud.ai.dataagent.constant.Constant.SCHEMA_RECALL_NODE;

/**
 * 根据查询增强结果决定下一个节点的分发器
 */
@Slf4j
public class QueryEnhanceDispatcher implements EdgeAction {

	@Override
	public String apply(OverAllState state) throws Exception {
		QueryEnhanceOutputDTO output = StateUtil.getObjectValue(state, QUERY_ENHANCE_NODE_OUTPUT,
				QueryEnhanceOutputDTO.class);
		if (output.getCanonicalQuery() == null || output.getCanonicalQuery().isBlank()) {
			throw new IllegalStateException("QueryEnhance missing canonical_query");
		}
		return SCHEMA_RECALL_NODE;
	}

}
