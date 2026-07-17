
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