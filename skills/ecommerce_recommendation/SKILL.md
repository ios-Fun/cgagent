---
name: ecommerce_recommendation
version: 1.0.0
description: 电商智能导购/商品推荐Agent，帮助用户发现商品并提供个性化购买建议
triggers:
  - 推荐
  - 买
  - 购物
  - 商品
  - 哪个好
  - 对比
tags:
  - ecommerce
  - recommendation
  - shopping
author: Agent Skills Framework
license: MIT
---

# 电商智能导购/商品推荐 Skill

## 功能说明

智能导购/商品推荐Agent通过多轮对话了解用户需求，提供个性化商品推荐。

### 核心能力

1. **需求分析** - 提取用户的购买需求，包括类别、预算、品牌偏好等
2. **用户画像** - 基于历史行为构建用户偏好模型
3. **商品搜索** - 根据约束条件搜索候选商品
4. **推荐排序** - 多维度打分排序，生成推荐理由
5. **推荐解释** - 生成自然语言的推荐说明

## 执行流程

```
用户输入
    │
    ▼
需求分析 (demand_analysis)
    │
    ▼
用户画像 (user_profiling)
    │
    ▼
商品搜索 (product_search)
    │
    ▼
推荐排序 (recommendation_ranking)
    │
    ▼
推荐解释 (recommendation_explanation)
    │
    ▼
最终输出
```

## 输入输出

### 输入参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| user_input | string | 是 | 用户输入文本 |
| user_id | string | 否 | 用户ID，用于个性化 |
| context | object | 否 | 额外上下文 |

### 输出结果

| 字段 | 类型 | 说明 |
|------|------|------|
| response | string | 自然语言回复 |
| recommendations | array | 推荐商品列表 |
| dialogue_state | string | 对话状态 |
| extracted_constraints | object | 提取的约束条件 |

## 配置要求

### 数据源

- 商品数据库（PostgreSQL/MySQL）
- 用户画像服务
- 搜索引擎（可选）

### 环境变量

```bash
# 商品数据库
PRODUCT_DB_URL=postgresql://user:pass@host:port/db

# 用户画像服务
USER_PROFILE_API_URL=https://api.example.com/user-profile

# 搜索服务
SEARCH_API_URL=https://search.example.com
```

## 使用示例

### 场景1：明确需求推荐

**用户输入**：
```
我想买个2000-3000的手机，平时玩游戏比较多
```

**预期输出**：
```
根据您的需求，我为您推荐以下几款手机：

首选推荐：Redmi K70 (¥2499)
- 性能强劲：搭载骁龙8 Gen2处理器，游戏性能出色
- 屏幕优秀：2K分辨率+120Hz高刷屏
- 续航给力：5000mAh大电池+120W快充
- 性价比高：2499元的价格在同档位非常有竞争力
```

### 场景2：模糊需求引导

**用户输入**：
```
我想买个好东西
```

**预期输出**：
```
我可以帮您推荐商品！请告诉我：
1. 您想买什么类型的商品？（如手机、耳机、电脑等）
2. 您的预算大概是多少？
3. 主要用途是什么？
```

## 注意事项

1. **数据安全** - 用户数据需要加密存储，遵守隐私法规
2. **推荐多样性** - 避免过度过滤，给用户更多选择
3. **库存检查** - 推荐的商品需要检查库存状态
4. **价格准确性** - 价格信息需要实时同步
