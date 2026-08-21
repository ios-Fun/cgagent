"""Coordinator - Main orchestration loop for Agent Skills Framework."""

import time
from typing import Dict, Any, Optional, List
from pathlib import Path

from fastapi import params
from langchain_core.tools import BaseTool


from rasa.intent_call import parseIntents
from .config import Config
from .context import AgentContext
from .langchain import reflection
from .llm_client import LLMClient
from .token_budget import TokenBudget
from .planner import Planner
from .replanner import RePlanner
from .skill_executor import SkillExecutor
from .synthesizer import Synthesizer
from .tools import ToolRegistry, create_default_registry
from utils.skill_loader import SkillRegistry,SkillLoader, Skill
from app.gateway.config import settings
from agent.memory.redis_memory import memoryRedis
from agent.langchain.llm import generate_context,generate_intents, generate_reflection, generate_refine, generate_multiintents
# from agent.langchain.prompt import INTENT_PROMPT
from .errors import AgentError, ExecutorError
from dotenv import load_dotenv
import os
import logging
import requests
import json
import uuid
from agent.sql.pgsql import execute_sql
from psycopg import sql
from rasa.rasa_intent import RasaIntent
logger = logging.getLogger(__name__)

# 0--rasa, 1--LLM
INTENT_TYPE = 1

# 是否开启反思
IS_REFLECTION = False
# 反思最高轮次
max_iterations = 2

# 是否开启注入json
INJECT_JSON = True

class Coordinator:
    """Main orchestration coordinator for Agent Skills Framework.

    Coordinates the entire pipeline:
    1. Initialize context with available skills
    2. Planner generates execution plan
    3. Executor executes skills with progressive disclosure
    4. Synthesizer generates final response
    """

    # Process-level singleton: avoid re-creating LLM client + re-scanning skills every request
    _shared: Optional["Coordinator"] = None
    _mcp_tools_cache = []

    def __init__(self, config: Config):
        """Initialize Coordinator.

        Args:
            config: Framework configuration
        """
        self.config = config

        # Initialize LLM client
        llm_provider = self._create_llm_provider()
        token_budget = TokenBudget(
            total_limit=config.budget.total_limit,
            warning_threshold=config.budget.warning_threshold,
            enable_compression=config.budget.enable_compression
        )
        self.llm_client = LLMClient(llm_provider, token_budget)

        # Initialize tool registry
        self.tools = create_default_registry()

        # Initialize skill registry
        self.skill_registry = SkillRegistry.get_instance()
        skills_dir = str(config.skills_dir)
        if not getattr(self.skill_registry, "_loader", None):
            self.skill_registry.initialize(skills_dir)
        else:
            try:
                # already initialized — keep cached skills
                _ = self.skill_registry.get_all_skills()
            except Exception:
                self.skill_registry.initialize(skills_dir)

        # Initialize components
        self.context = AgentContext(enable_audit=config.execution.enable_audit_log)
        self.planner = Planner(
            self.llm_client,
            confidence_threshold=config.execution.confidence_threshold
        )
        self.replanner = RePlanner(self.llm_client)
        self.executor = SkillExecutor(self.llm_client)
        self.synthesizer = Synthesizer(self.llm_client)

        # Performance metrics
        self._metrics = {
            "total_requests": 0,
            "total_execution_time_ms": 0,
            "total_skills_executed": 0,
            "successful_plans": 0,
            "failed_plans": 0
        }

    @classmethod
    def get_shared(cls, config: Optional[Config] = None) -> "Coordinator":
        """Reuse one Coordinator per process."""
        if cls._shared is None:
            cfg = config or Config.from_file()
            cls._shared = cls(cfg)
            logger.info("Coordinator shared instance created")
        return cls._shared

    @classmethod
    def reset_shared(cls) -> None:
        """Drop shared instance."""
        cls._shared = None

    def _create_llm_provider(self):
        """Create LLM provider based on configuration."""
        provider_name = self.config.llm.provider.lower()

        if provider_name == "openai":
            from agent.providers.openai_provider import OpenAIProvider
            return OpenAIProvider(
                api_key=self.config.llm.api_key,
                base_url=self.config.llm.base_url,
                default_model=self.config.llm.model
            )

        elif provider_name == "anthropic":
            from agent.providers.anthropic_provider import AnthropicProvider
            return AnthropicProvider(
                api_key=self.config.llm.api_key,
                base_url=self.config.llm.base_url,
                default_model=self.config.llm.model
            )

        elif provider_name == "ollama":
            from agent.providers.ollama_provider import OllamaProvider
            return OllamaProvider(
                host=self.config.llm.base_url or "localhost",
                port=11434,
                default_model=self.config.llm.model
            )

        elif provider_name == "zhipu":
            from agent.providers.zhipu_provider import ZhipuProvider
            return ZhipuProvider(
                api_key=self.config.llm.api_key,
                base_url=self.config.llm.base_url,
                default_model=self.config.llm.model or "glm-4"
            )

        else:
            raise ValueError(f"Unsupported LLM provider: {provider_name}")

    async def process(
        self,
        session_id: str,
        user_input: str,
        stream: bool = False,
        user_id: Optional[str] = None,
        memory_context: Optional[str] = None,
        mode: str = "default",
    ) -> Dict[str, Any]:
        """Process a user request.

        Args:
            session_id: Session id
            user_input: User's request
            stream: Whether to stream the response
            user_id: User id for long-term memory
            memory_context: Pre-retrieved long-term memory block for system prompt
            mode: Execution mode - "default" (Rasa) or "flash" (Plan + multi-skill Executor)

        Returns:
            Result dictionary with response and metadata
        """
        start_time = time.time()
        self._metrics["total_requests"] += 1
        run_id = str(uuid.uuid4())
        user_appended = False
        try:
            self.context = AgentContext(enable_audit=self.config.execution.enable_audit_log)
            self.context.set_component("coordinator")
            self.context.write_layer1("raw_user_input", user_input, "coordinator")
            if user_id:
                self.context.write_layer1("user_id", user_id, "coordinator")
            else:
                user_id = "admin"
            if memory_context:
                self.context.write_layer1("long_term_memory", memory_context, "coordinator")
            self.context.write_layer3(
                "available_skills",
                self.skill_registry.get_all_skills(),
                "coordinator"
            )
            self.context.write_layer3("token_budget", self.llm_client.budget, "coordinator")
            self.context.write_layer3("tools_registry", self.tools, "coordinator")

            # 会话储存（redis）初始化
            from agent.memory.message_store import message_store
            message_store.append_user(session_id, user_input)
            user_appended = True

            #   flash   -> multi-skill plan + executor
            #   default -> Rasa routing
            mode_norm = (mode or "default").lower()
            first_skill = None
            incident_list = None
            if mode_norm == "flash":
                result = await self._execution_flash(session_id, user_input)
            else:
                result_tuple = await self._plan_execution(session_id, user_input)
                result = result_tuple[0]
                first_skill = result_tuple[1]
                incident_list = result_tuple[2]
                # 测试： 看需要执行哪些mcp
                # list = await self.multi_intent(session_id, user_input)
                # return {'final_response': list}

            # mcp的结果，让大模型生成报告
            final_response = generate_context(
                result,
                memory_context=memory_context,
                user_input=user_input,
                system_prompt=first_skill.prompt
            )

            if INJECT_JSON:
                # 每个诊断单，部分内容固定，加部分大模型生成
                logger.info("Injected JSON")
                marker = "\n## 3. 运行风险评估\n"
                parts = final_response.split(marker, 1)
                if len(parts) == 2:
                    json_result = await self.generate_json_inject(incident_list)
                    # 插入到合适的位置
                    final_response = parts[0] + json_result + marker + parts[1]

            if IS_REFLECTION:
                for i in range(max_iterations):
                    logger.info(f"第 {i} 轮 迭代")
                    # 反思
                    reflection_info = generate_reflection(final_response)

                    if reflection_info["is_sufficient"] is None:
                        break
                    if reflection_info["is_sufficient"] is not None and reflection_info["is_sufficient"]:
                        break
                    if reflection_info["additional_adjusts"] is None:
                        break
                    # 优化
                    final_response = generate_refine(result, final_response, reflection_info["additional_adjusts"])

            # 会话储存（redis）
            message_store.append_assistant(session_id, final_response)

            add_sql = sql.SQL("INSERT INTO runs(run_id, session_id, user_id, status, first_human_message, last_ai_message, created_at, updated_at) VALUES (%s, %s, %s,%s, %s, %s, NOW(), NOW())")
            execute_sql(add_sql, (run_id,session_id,user_id, "success", user_input, final_response))

            metrics = self._get_execution_metrics(start_time)
            metrics["mode"] = (mode or "default").lower()
            return {
                "final_response": final_response,
                "success": True,
                "metrics": metrics,
            }

        except Exception as e:
            if user_appended:
                try:
                    from agent.memory.message_store import message_store
                    message_store.append_error(session_id, str(e))
                except Exception:
                    pass
            add_sql = sql.SQL("INSERT INTO runs(run_id, session_id, user_id, status, first_human_message, last_ai_message, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())")
            execute_sql(add_sql, (run_id,session_id,user_id, "fail", user_input, str(e)))
            return {
                "final_response": f"An error occurred: {str(e)}",
                "success": False,
                "metrics": self._get_execution_metrics(start_time),
                "error": str(e)
            }

    # 查找mcp
    def find_mcp(self, mcp_name: str, mcp_tools_cache: list) -> Optional[BaseTool]:
        from agent.modes.common import tool_name_matches
        for mcp in mcp_tools_cache or []:
            name = getattr(mcp, "name", None)
            if name and tool_name_matches(mcp_name, name):
                return mcp
        return None

    async def multi_intent(self, session_id: str, user_input: str):
        logger.info("multi_intent")
        system_prompt = f"""
        你是一个专业的语义拆分专家。你的任务是基于用户当前输入，判断是否需要拆分语义，并进行拆分。

# Instructions
1. **分析意图**：判断用户输入的是独立问题、追问、还是包含多个子问题。
2. **多意图拆分**：如果用户一次问了两个不同领域的问题（例如“RAGFlow怎么部署？另外今天天气如何？”），请拆分为两个独立的查询。
3. **保持原义**：尽量不要修改原文，拆分时也保持原有语句部分。
4. **不要回答**：绝对不要回答用户的问题，只负责重写。

# Output Format
必须严格输出 JSON 格式，不要包含任何额外文字：
{{
    "rewritten_queries": ["高压跳闸电磁阀活动试验过程中，母管安全油压最大、最小值各为多少？", "拆分后的查询语句2", "拆分后的查询语句3"...]
}}

比如：高压跳闸电磁阀活动试验过程中，母管安全油压最大、最小值各为多少？是否正常？
输出
{{
    "rewritten_queries": ["高压跳闸电磁阀活动试验过程中，母管安全油压最大、最小值各为多少？", "是否正常？"]
}}
                    """

        result = generate_multiintents(system_prompt, user_input)
        if result is not None and len(result) > 0:
            url = 'http://192.168.0.106:5005/webhooks/rest/webhook'
            deerflow_load = False
            # 意图的封装
            intent_list = []
            for intent in result:
                # 调用rasa得到意图数组
                body = {"sender": 'sender001', "message": intent}
                response = requests.post(url, json=body)
                intent_result = response.json()
                logging.info(f"response: {intent_result}")


                if len(intent_result) > 0:
                    intent_value = int(intent_result[0]["text"])

                    params = None
                    if len(intent_result) > 1:
                        params = intent_result[1]["custom"]
                    obj = RasaIntent(intent, intent_value, params)
                    if intent_value == 1 or intent_value == 2:
                        deerflow_load = True
                else:
                    obj = RasaIntent(intent, None, None)
                intent_list.append(obj)
            # 判断下有没有机组健康，设备健康的意图，有则调用deerflow
            if deerflow_load:
                logger.info("deerflow_load")
            else:
                logger.info("no deerflow_load")
                # 否则，根据rasa的参数调用mcp或者java接口

                parseIntents(intent_list)
        return result

    # 生成json注入的内容
    async def generate_json_inject(self, incident_list:list):
        logger.info("generate_json_inject")
        result = "\n\n### 故障模式及原因分析\n"
        # from mcp.mcptools import get_mcp_tools
        # self._mcp_tools_cache = await get_mcp_tools()
        prompt = '''
        你是一名资深电力行业设备智能诊断专家，对该诊断单内容进行分析，以markdown格式，4级标题开始，输出300字左右
        '''
        for item in incident_list:
            incident_id = item["incidentId"]
            name = item["maxDefectSeverityName"]
            title_str = f"\n#### 【诊断单ID: {incident_id}】 {name}\n"
            result += title_str
            json_str = f'''
            ```json{{
  "type": "fault_analysis",
  "version": "1.0",
  "incidentId": {incident_id}
}}
```
            '''
            result += json_str
            result += '\n'

            llm_input = f"{item}\n"
            # 调用mcp的结果
            incident_id_list = [incident_id]
            params = {"incident_ids" : incident_id_list, "thread_id":"1", "unit_id":805126}
            mcp_tool1 = self.find_mcp("mcp-device-sse_unit_mount_path", self._mcp_tools_cache)
            mcp_tool2 = self.find_mcp("mcp-device-sse_unit_graph_show", self._mcp_tools_cache)
            mcp_tool3 = self.find_mcp("mcp-device-sse_unit_tags_realtime", self._mcp_tools_cache)
            call_tool_result1 = await mcp_tool1.ainvoke(input=params)
            llm_input += str(call_tool_result1)
            llm_input += '\n'
            call_tool_result2 = await mcp_tool2.ainvoke(input=params)
            llm_input += str(call_tool_result2)
            llm_input += '\n'
            call_tool_result3 = await mcp_tool3.ainvoke(input=params)
            llm_input += str(call_tool_result3)
            llm_input += '\n'
            # 大模型生成的结果
            final_response = generate_context(
                llm_input,
                memory_context=None,
                user_input=None,
                system_prompt=prompt
            )
            result += final_response

            result += '\n'
            logger.info(f"generate_json_inject result: {final_response}")
        logger.info(f"final result: {result}")
        return result


    # 计划-- 执行功能
    async def _plan_execution(self, session_id: str, user_input: str):
        """Generate execution plan.

        Args:
            user_input: User's request

        Returns:
            ExecutionPlan
        """
        indexList = []
        if INTENT_TYPE == 0:
            # 1. rasa进行意图识别, 可以后续替换为大模型进行
            rasa_url = settings.RASA_URL
            rasa_data = {
                "sender": "sender002", "message": user_input
            }
            rasa_response = requests.post(url=rasa_url, json=rasa_data, headers={"Content-Type": "application/json"})
            logging.info(f"rasa_response: {rasa_response.text}")

            rasa_obj = rasa_response.text
            data = json.loads(rasa_obj)

            logging.info(f"first: {data[0]}")
            first_text = data[0]["text"]
            logging.info(f"first_text: {first_text}")
            # 2. 返回skills, 暂时先只触发一个skill
            indexList = [int(first_text)]

        else:
            # 用大模型来进行意图识别
            available_skills = self.skill_registry.get_all_skills()
            skills_desc = self._format_skills(available_skills)
            # system_prompt = INTENT_PROMPT.format(available_skills)
            system_prompt = f"""
            你是一个意图分类器。分析用户输入，识别其中包含的所有意图场景。
场景列表：
{skills_desc}
规则：
1. 返回 JSON，格式：{{"scenes":["tag-trend","device-healthy",...],"composite":true/false}}
2. 如果用户只有单一意图：{{"scenes":["tag-trend"],"composite":false}}
3. 如果用户有多个意图（如"审查代码并优化性能再写文档"）：{{"scenes":["review","perf","doc"],"composite":true}}
4. scenes 数组按主次顺序排列，最重要的在前面，最多 5 个
5. 如果都不太匹配，返回 {{"scenes":["optimize"],"composite":false}}
6. 不要返回任何其他文字，只返回 JSON`;
            """
            logger.info(f"system_prompt: {system_prompt}")
            result = generate_intents(system_prompt, user_input)
            # 得到index
            for index, name in enumerate(settings.SKILLS):
                for ressult_item in result:
                    if name == ressult_item:
                        indexList.append(index)
        if len(indexList) == 0:
            logging.warning(f"no skills found")
            return "todo：默认处理"

        # 提取诊断单id参数
        incident_id_list = []
        incident_list = []

        # 将结果拼接到字符串
        result = ""
        # 首个加载skill
        first_skill = None

        for index in indexList:
            loadSkill = settings.SKILLS[indexList[index-1]]
            logging.info(f"loadSkill: {loadSkill}")
            skill_dir = Path(settings.SKILLS_DIR) / loadSkill
            skill_md = skill_dir / "SKILL.md"

            skill = SkillRegistry.get_instance().get_skill(loadSkill)
            if first_skill is None:
                first_skill = skill
            skill.load_mcps()
            logging.info(f"skill: {skill}")

            from agent.mcp.mcptools import get_mcp_tools

            logger.info("Initializing MCP tools...")
            self._mcp_tools_cache = await get_mcp_tools()

            # 遍历skill里设置的mcp
            for mcp in skill.tools:
                logger.info(f"mcp: {mcp}")
                mcp_tool = self.find_mcp(mcp.strip(), self._mcp_tools_cache)
                call_tool_result = None
                if mcp.endswith("cg_device_healthy") or mcp.endswith("cg_unit_healthy_v2") or mcp.endswith("unit_alarm_list_statistics_v2"):
                    call_tool_result = await mcp_tool.ainvoke(input={"orginal": user_input, "thread_id": session_id})
                else:
                    # 查看mcp的参数
                    logger.info(f"mcp: {mcp}")
                    args = mcp_tool.args
                    params = {"unit_id":805126}
                    for key in args.keys():
                        if key == "thread_id":
                            params[key] = session_id
                        else:
                            if loadSkill.endswith("unit-healthy"):
                                params["incident_ids"] = incident_id_list
                            else:
                                redis_key = f"{session_id}_{key}"
                                if memoryRedis.has_key(redis_key):
                                    value = memoryRedis.get_cache(redis_key)
                                    params[key] = value
                    logger.info(f"params: {params}")
                    call_tool_result = await mcp_tool.ainvoke(input=params)

                logger.info(f"result1: {call_tool_result}")

                # 处理结果
                text_result = call_tool_result[0]['text']
                json_result = None
                try:
                    json_result = json.loads(text_result)
                except json.JSONDecodeError as e:
                    logger.warning(f"json_result is None:{e}")
                    json_result = None
                if json_result is not None:
                    if mcp.endswith("cg_unit_healthy_v2"):
                        for item in json_result["data"]:
                            incident_list = item["incidents"]
                            for incident in item["incidents"]:
                                incident_id_list.append(incident["incidentId"])

                    if len(json_result) == 0:
                        logger.warn("json_result is 0")

                    for key, value in json_result.items():
                        if key.startswith("cached_"):
                            redis_key = "";
                            if session_id is not None:
                                redis_key = f"{session_id}_{key}"
                            else:
                                redis_key = key
                            memoryRedis.set_cache(redis_key, value)
                    if "llmMsg" in json_result:
                        llmMsg = json_result["llmMsg"]
                        result += llmMsg
                    else:
                        result += text_result
                else:
                    result += text_result
                result += "\n"
        logger.info(f"result: {result}")
        return result, first_skill, incident_list

    def _format_skills(self, available_skills: Dict) -> str:
        """Format available skills for prompt."""
        lines = []
        index = 1
        for name, skill in available_skills.items():
            lines.append(
                f"- {name}: {skill.description}\n"
                # f"  Triggers: {', '.join(skill.triggers)}\n"
                # f"  Tags: {', '.join(skill.tags)}"
            )
        return "\n".join(lines)



    async def _execution_flash(self, session_id: str, user_input: str) -> str:
        from agent.modes.flash import execution_flash
        return await execution_flash(self, session_id, user_input)

    def _execute_plan(self, plan) -> Dict[str, Any]:
        """Execute all steps in plan.

        Args:
            plan: ExecutionPlan

        Returns:
            Execution result dictionary
        """
        self.context.set_component("executor")

        executed_steps = []
        failed_steps = []

        for i, step in enumerate(plan.steps):
            step_number = i + 1
            self.context.scratchpad.current_step = step_number

            # Execute with retry and replan
            result = self._execute_single_step(step, len(executed_steps))

            if result["success"]:
                executed_steps.append(result)
            else:
                failed_steps.append(result)

                # Handle failure
                if self.config.execution.enable_replan:
                    recovery = self._handle_failure(step, result, executed_steps)
                    if recovery["action"] == "skip":
                        continue
                    elif recovery["action"] == "abort":
                        return {
                            "success": False,
                            "error": f"Execution aborted: {recovery.get('reason', 'Unknown reason')}",
                            "executed_steps": executed_steps,
                            "failed_steps": failed_steps
                        }

        self._metrics["total_skills_executed"] += len(executed_steps)

        return {
            "success": len(executed_steps) > 0,
            "executed_steps": executed_steps,
            "failed_steps": failed_steps,
            "summary": {
                "total": len(plan.steps),
                "executed": len(executed_steps),
                "failed": len(failed_steps)
            }
        }

    def _execute_single_step(
        self,
        step: Dict,
        completed_count: int
    ) -> Dict[str, Any]:
        """Execute a single skill step.

        Args:
            step: Step definition
            completed_count: Number of already completed steps

        Returns:
            Execution result
        """
        # Ensure we're in executor context
        self.context.set_component("executor")

        skill_name = step["skill"]
        sub_task = step["sub_task"]

        # Get skill
        try:
            skill = self.skill_registry.get_skill(skill_name)
        except Exception as e:
            return {
                "success": False,
                "skill_name": skill_name,
                "error": f"Skill not found: {skill_name}",
                "step": step
            }

        # Prepare context for step
        include_history = (completed_count == 0)
        step_context = self.context.prepare_for_step(step, include_history)

        # Execute skill
        try:
            result = self.executor.execute(skill, sub_task, step_context)

            if result.get("success"):
                # Store result in scratchpad
                self.context.write_scratchpad(
                    skill_name=skill_name,
                    sub_task=sub_task,
                    structured=result.get("structured", {}),
                    text=result.get("text", ""),
                    execution_time_ms=result.get("execution_time_ms", 0),
                    source="executor"
                )

            return {
                "success": result.get("success", False),
                "skill_name": skill_name,
                "sub_task": sub_task,
                "result": result,
                "step": step
            }

        except Exception as e:
            return {
                "success": False,
                "skill_name": skill_name,
                "error": str(e),
                "step": step
            }

    def _handle_failure(
        self,
        step: Dict,
        failure_result: Dict,
        executed_steps: List
    ) -> Dict[str, str]:
        """Handle execution failure with replanning.

        Args:
            step: Failed step
            failure_result: Failure result
            executed_steps: Previously executed steps

        Returns:
            Recovery action dictionary
        """
        # Build execution status for replanner
        execution_status = {
            "plan": self.context.read_layer1("execution_plan"),
            "completed": executed_steps,
            "available_skills": self.skill_registry.get_all_skills()
        }

        # Get replanner decision
        decision = self.replanner.decide(
            original_request=self.context.read_layer1("raw_user_input"),
            current_step=step,
            execution_status=execution_status,
            failed_step_error=failure_result.get("error", "Unknown error")
        )

        # Log failure
        self.context.scratchpad.record_failure(
            step=step,
            error=failure_result.get("error", ""),
            attempt=1
        )

        return {
            "action": decision.action.value,
            "reason": decision.reason
        }

    def _get_execution_metrics(self, start_time: float) -> Dict:
        """Get execution metrics.

        Args:
            start_time: Start time of processing

        Returns:
            Metrics dictionary
        """
        execution_time_ms = (time.time() - start_time) * 1000
        self._metrics["total_execution_time_ms"] += execution_time_ms

        return {
            "execution_time_ms": execution_time_ms,
            "total_requests": self._metrics["total_requests"],
            "total_skills_executed": self._metrics["total_skills_executed"],
            "llm_metrics": self.llm_client.get_metrics(),
            "token_budget": self.llm_client.budget.get_summary()
        }

    def get_audit_trail(self) -> List[Dict]:
        """Get full audit trail.

        Returns:
            List of audit entries
        """
        return self.context.export_audit()

    def explain(self, question: str) -> str:
        """Get explanation for a decision.

        Args:
            question: Question to answer

        Returns:
            Explanation text
        """
        if self.context.audit_log:
            return self.context.audit_log.explain(question)
        return "Audit logging is not enabled."

    def reset(self) -> None:
        """Reset coordinator state."""
        self.context.clear()
        self.llm_client.budget.reset()
