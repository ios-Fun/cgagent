
PLAN_PROMPT = '''
你需要：
1. 理解用户问题，
2. 制定排查计划
3. 返回 JSON

返回格式：

[
  {
    "step": 1,
    "tool": "工具名称",
    "reason": "为什么执行这一步"
  },
  {
    "step": 2,
    "tool": "工具名称",
    "reason": "为什么执行这一步"
  }
]
'''

PLAN_PROMPT1 = '''
你需要：
1. 理解用户问题，<content></content>的内容
2. 制定排查计划
3. 返回 JSON

输入内容
<content>
{}
</content>
返回格式：

[
  {
    "step": 1,
    "tool": "工具名称",
    "reason": "为什么执行这一步"
  },
  {
    "step": 2,
    "tool": "工具名称",
    "reason": "为什么执行这一步"
  }
]
'''

# INTENT_PROMPT = '''
# 你是一个意图分类器。分析用户输入，识别其中包含的所有意图场景。
#
# 场景列表：
# {}
#
# 规则：
# 1. 返回 JSON，格式：{"scenes":["场景ID1","场景ID2",...],"composite":true/false}
# 2. 如果用户只有单一意图：{"scenes":["场景ID"],"composite":false}
# 3. 如果用户有多个意图（如"审查代码并优化性能再写文档"）：{"scenes":["review","perf","doc"],"composite":true}
# 4. scenes 数组按主次顺序排列，最重要的在前面，最多 5 个
# 5. 如果都不太匹配，返回 {"scenes":["optimize"],"composite":false}
# 6. 不要返回任何其他文字，只返回 JSON`;
#
# '''
