---
name: assess_risk
version: 1.0.0
description: 基于体检数据评估健康风险
triggers:
  - 风险评估
  - 健康风险
  - 疾病风险
  - 风险分析
  - 健康评分
tags:
  - 健康
  - 风险评估
input_schema:
  type: object
  properties:
    parsed_report:
      $ref: "ParseReportOutput"
output_schema: AssessRiskOutput
---

# assess_risk Skill

该 Skill 基于已解析的体检报告，评估四个维度的健康风险：

## 评估维度

1. **心血管风险** - 基于血压、BMI、胆固醇等指标
2. **代谢风险** - 基于血糖、糖化血红蛋白、甘油三酯、尿酸等
3. **肝脏风险** - 基于肝功能指标（转氨酶等）
4. **肾脏风险** - 基于肾功能指标（肌酐、尿素氮等）

## 输入

依赖 `parse_report` skill 的结构化输出。

## 输出

```json
{
  "structured": {
    "risk_scores": {
      "cardiovascular": {"score": 45, "level": "中等风险", "factors": [...]},
      "metabolic": {"score": 60, "level": "中等风险", "factors": [...]},
      "liver": {"score": 20, "level": "低风险", "factors": []},
      "kidney": {"score": 0, "level": "低风险", "factors": []}
    },
    "overall_risk": {
      "score": 31.25,
      "level": "中等风险",
      "recommendation": "建议改善生活方式，定期复查"
    }
  },
  "text": "风险评估说明..."
}
```

## 执行模式

使用 **executor.py** 混合执行模式：
- 规则引擎计算各维度风险评分（确定性）
- LLM 生成风险推理说明（自然语言）
