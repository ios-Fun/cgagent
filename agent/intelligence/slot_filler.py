"""
槽位填充器

从用户输入中提取结构化参数，支持必填/可选槽位、槽位验证和类型转换
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from datetime import datetime
from enum import Enum


class SlotType(Enum):
    """槽位数据类型"""
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    LIST = "list"
    ENUM = "enum"
    REGEX = "regex"


@dataclass
class SlotDefinition:
    """槽位定义"""
    name: str
    description: str = ""
    slot_type: SlotType = SlotType.STRING
    required: bool = True
    default_value: Any = None
    enum_values: Optional[List[str]] = None
    regex_pattern: Optional[str] = None
    validation_func: Optional[Callable[[Any], bool]] = None
    extractor: Optional[Callable[[str], Any]] = None

    def validate(self, value: Any) -> Tuple[bool, str]:
        """验证槽位值"""
        if value is None or value == "":
            if self.required:
                return False, f"槽位 '{self.name}' 是必填项"
            return True, ""

        # 类型验证
        try:
            if self.slot_type == SlotType.INTEGER:
                int(value)
            elif self.slot_type == SlotType.FLOAT:
                float(value)
            elif self.slot_type == SlotType.BOOLEAN:
                if isinstance(value, str):
                    value.lower() in ('true', 'false', 'yes', 'no', '1', '0')
            elif self.slot_type == SlotType.DATE:
                datetime.strptime(str(value), "%Y-%m-%d")
            elif self.slot_type == SlotType.DATETIME:
                datetime.fromisoformat(str(value))
            elif self.slot_type == SlotType.ENUM:
                if self.enum_values and value not in self.enum_values:
                    return False, f"值 '{value}' 不在允许的选项中: {self.enum_values}"
            elif self.slot_type == SlotType.REGEX:
                if self.regex_pattern:
                    if not re.match(self.regex_pattern, str(value)):
                        return False, f"值 '{value}' 不符合要求的格式"
        except (ValueError, TypeError) as e:
            return False, f"类型验证失败: {e}"

        # 自定义验证
        if self.validation_func and not self.validation_func(value):
            return False, f"自定义验证失败"

        return True, ""

    def convert_type(self, value: Any) -> Any:
        """转换值为槽位类型"""
        if value is None:
            return self.default_value

        try:
            if self.slot_type == SlotType.INTEGER:
                return int(value)
            elif self.slot_type == SlotType.FLOAT:
                return float(value)
            elif self.slot_type == SlotType.BOOLEAN:
                if isinstance(value, str):
                    return value.lower() in ('true', 'yes', '1')
                return bool(value)
            elif self.slot_type == SlotType.DATE:
                return datetime.strptime(str(value), "%Y-%m-%d").date()
            elif self.slot_type == SlotType.DATETIME:
                return datetime.fromisoformat(str(value))
            elif self.slot_type == SlotType.LIST:
                if isinstance(value, str):
                    return [v.strip() for v in value.split(',')]
                return list(value)
        except:
            return value

        return value


@dataclass
class SlotValue:
    """槽位值"""
    name: str
    value: Any
    raw_value: Any = None
    confidence: float = 1.0
    source: str = "extract"  # extract, default, inferred
    valid: bool = True
    error_message: str = ""


@dataclass
class SlotFillingResult:
    """槽位填充结果"""
    user_input: str
    slots: Dict[str, SlotValue] = field(default_factory=dict)
    missing_required: List[str] = field(default_factory=list)
    invalid_slots: List[str] = field(default_factory=list)
    complete: bool = False
    follow_up_questions: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)

    def get_value(self, slot_name: str, default: Any = None) -> Any:
        """获取槽位值"""
        if slot_name in self.slots:
            return self.slots[slot_name].value
        return default

    def get_all_values(self) -> Dict[str, Any]:
        """获取所有槽位值"""
        return {name: slot.value for name, slot in self.slots.items()}

    def is_complete(self) -> bool:
        """检查是否所有必填槽位都已填充"""
        return len(self.missing_required) == 0 and len(self.invalid_slots) == 0


class SlotFiller:
    """
    槽位填充器

    从用户输入中提取结构化参数，支持多种槽位类型和验证规则
    """

    def __init__(self, llm_client=None, config: Optional[Dict[str, Any]] = None):
        self.llm_client = llm_client
        self.config = config or {}
        self.slot_definitions: Dict[str, SlotDefinition] = {}
        self.enable_llm_extraction = self.config.get("enable_llm_extraction", True)

        # 注册内置槽位类型提取器
        self._extractors: Dict[SlotType, Callable[[str, SlotDefinition], Any]] = {
            SlotType.DATE: self._extract_date,
            SlotType.DATETIME: self._extract_datetime,
        }

    def register_slot(self, definition: SlotDefinition):
        """注册槽位定义"""
        self.slot_definitions[definition.name] = definition

    def register_slots(self, definitions: List[SlotDefinition]):
        """批量注册槽位定义"""
        for definition in definitions:
            self.register_slot(definition)

    def fill_slots(self, user_input: str,
                   intent_name: Optional[str] = None,
                   context: Optional[Dict[str, Any]] = None) -> SlotFillingResult:
        """
        从用户输入中填充槽位

        Args:
            user_input: 用户输入文本
            intent_name: 意图名称（用于获取相关槽位）
            context: 上下文信息

        Returns:
            SlotFillingResult: 槽位填充结果
        """
        result = SlotFillingResult(user_input=user_input, context=context or {})

        # 确定需要填充的槽位
        target_slots = list(self.slot_definitions.values())

        # 1. 基于规则的提取
        extracted = self._rule_based_extraction(user_input, target_slots)

        # 2. LLM增强提取（如果启用）
        if self.enable_llm_extraction and self.llm_client:
            llm_extracted = self._llm_extraction(user_input, target_slots, extracted)
            extracted.update(llm_extracted)

        # 3. 验证和填充
        for slot_def in target_slots:
            slot_value = self._process_slot_value(slot_def, extracted.get(slot_def.name))
            result.slots[slot_def.name] = slot_value

            if slot_def.required:
                if slot_value.value is None:
                    result.missing_required.append(slot_def.name)
                elif not slot_value.valid:
                    result.invalid_slots.append(slot_def.name)

        # 4. 生成后续问题
        result.follow_up_questions = self._generate_follow_up_questions(result)
        result.complete = result.is_complete()

        return result

    def _rule_based_extraction(self, user_input: str,
                               slot_definitions: List[SlotDefinition]) -> Dict[str, Any]:
        """基于规则的槽位提取"""
        extracted = {}

        for slot_def in slot_definitions:
            # 使用自定义提取器
            if slot_def.extractor:
                value = slot_def.extractor(user_input)
                if value is not None:
                    extracted[slot_def.name] = value
                    continue

            # 内置类型提取
            if slot_def.slot_type in self._extractors:
                value = self._extractors[slot_def.slot_type](user_input, slot_def)
                if value is not None:
                    extracted[slot_def.name] = value
                    continue

            # 基于描述的关键词匹配
            if slot_def.description:
                # 简单的关键词提取逻辑
                pass

        return extracted

    def _llm_extraction(self, user_input: str,
                        slot_definitions: List[SlotDefinition],
                        existing: Dict[str, Any]) -> Dict[str, Any]:
        """使用LLM提取槽位"""

        slot_descriptions = []
        for slot in slot_definitions:
            if slot.name not in existing:
                desc = f"- {slot.name}: {slot.description} (类型: {slot.slot_type.value}"
                if slot.required:
                    desc += ", 必填"
                desc += ")"
                slot_descriptions.append(desc)

        if not slot_descriptions:
            return {}

        prompt = f"""从用户输入中提取以下参数信息:

{chr(10).join(slot_descriptions)}

用户输入: {user_input}

请以JSON格式输出提取的参数:
{{
    "参数名1": "提取的值",
    "参数名2": "提取的值"
}}

如果某个参数无法从输入中提取，不要包含该参数。"""

        try:
            response = self.llm_client.complete(prompt, temperature=0.1)

            # 提取JSON
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return {k: v for k, v in data.items() if v is not None and v != ""}
        except Exception:
            pass

        return {}

    def _process_slot_value(self, slot_def: SlotDefinition,
                           raw_value: Any) -> SlotValue:
        """处理槽位值"""

        if raw_value is None:
            # 使用默认值
            if slot_def.default_value is not None:
                return SlotValue(
                    name=slot_def.name,
                    value=slot_def.default_value,
                    source="default",
                    valid=True
                )
            return SlotValue(
                name=slot_def.name,
                value=None,
                source="extract",
                valid=not slot_def.required
            )

        # 类型转换
        converted_value = slot_def.convert_type(raw_value)

        # 验证
        valid, error_msg = slot_def.validate(converted_value)

        return SlotValue(
            name=slot_def.name,
            value=converted_value,
            raw_value=raw_value,
            source="extract",
            valid=valid,
            error_message=error_msg
        )

    def _generate_follow_up_questions(self, result: SlotFillingResult) -> List[str]:
        """生成后续问题以收集缺失的槽位"""
        questions = []

        for slot_name in result.missing_required:
            slot_def = self.slot_definitions.get(slot_name)
            if slot_def:
                if slot_def.description:
                    questions.append(f"请提供{slot_def.description}")
                else:
                    questions.append(f"请提供{slot_name}")

        for slot_name in result.invalid_slots:
            slot = result.slots.get(slot_name)
            if slot and slot.error_message:
                questions.append(f"{slot_name}格式有误: {slot.error_message}")

        return questions

    def _extract_date(self, text: str, slot_def: SlotDefinition) -> Optional[str]:
        """提取日期"""
        # 匹配YYYY-MM-DD格式
        pattern = r'\d{4}-\d{2}-\d{2}'
        match = re.search(pattern, text)
        if match:
            return match.group()

        # 匹配YYYY/MM/DD格式
        pattern = r'\d{4}/\d{2}/\d{2}'
        match = re.search(pattern, text)
        if match:
            return match.group().replace('/', '-')

        return None

    def _extract_datetime(self, text: str, slot_def: SlotDefinition) -> Optional[str]:
        """提取日期时间"""
        # ISO 8601格式
        pattern = r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?'
        match = re.search(pattern, text)
        if match:
            return match.group()

        return None