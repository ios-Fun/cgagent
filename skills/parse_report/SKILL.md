---
name: parse_report
version: 1.0.0
description: 解析体检报告，提取各项检验指标并分类
triggers:
  - 体检报告
  - 化验单
  - 体检数据
  - 解析报告
  - 检验结果
tags:
  - 健康
  - 数据解析
input_schema:
  type: object
  properties:
    raw_report:
      type: object
      description: 原始报告数据
output_schema: ParseReportOutput
tools:
  - check_reference_range
  - calculate_bmi
  - classify_blood_pressure
---

# parse_report Skill

该 Skill 用于解析体检报告，包括：

## 功能

- **BMI 计算** - 根据身高体重计算 BMI 并分类
- **血压分类** - 判断血压水平（正常/正常高值/高血压）
- **指标比对** - 将各项检验指标与参考范围比对
- **概况摘要** - 生成体检结果的自然语言摘要

## 输入格式

支持结构化数据输入：

```json
{
  "height": 175,           // 身高 (cm)
  "weight": 75,            // 体重 (kg)
  "sbp": 130,              // 收缩压 (mmHg)
  "dbp": 85,               // 舒张压 (mmHg)
  "lab_items": [           // 检验指标
    {
      "name": "空腹血糖",
      "value": 7.2,
      "unit": "mmol/L",
      "ref_low": 3.9,
      "ref_high": 6.1
    }
  ]
}
```

## 输出格式

返回结构化数据和自然语言摘要：

```json
{
  "structured": {
    "basic_info": {
      "bmi": {"value": 24.5, "category": "正常"},
      "blood_pressure": {"category": "正常高值"}
    },
    "indicators": [...],
    "summary": {"total_indicators": 15, "abnormal_count": 3}
  },
  "text": "体检概况摘要..."
}
```

## 执行模式

使用 **executor.py** 混合执行模式：
- 规则引擎处理 BMI、血压、指标比对（确定性计算）
- LLM 生成自然语言摘要（灵活表达）
