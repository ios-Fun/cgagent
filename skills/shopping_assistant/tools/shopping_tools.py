"""智能导购助手工具定义"""

from typing import Dict, Any, List, Optional
from ..utils import ProductKnowledgeBase
from ..schema import Product


# 全局知识库实例
_knowledge_base = ProductKnowledgeBase()


def search_products_tool(
    category: Optional[str] = None,
    brands: Optional[List[str]] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    keywords: Optional[List[str]] = None,
    limit: int = 10
) -> Dict[str, Any]:
    """
    搜索商品

    根据类别、品牌、价格范围、关键词等条件搜索商品。

    Args:
        category: 商品类别，如"笔记本"、"手机"、"耳机"
        brands: 品牌列表，如["小米", "华为", "苹果"]
        min_price: 最低价格
        max_price: 最高价格
        keywords: 关键词列表，如["游戏", "降噪", "轻薄"]
        limit: 返回结果数量限制

    Returns:
        搜索结果，包含商品列表
    """
    price_range = None
    if min_price is not None or max_price is not None:
        price_range = {
            "min": min_price or 0,
            "max": max_price or float("inf")
        }

    products = _knowledge_base.search(
        category=category,
        brands=brands,
        price_range=price_range,
        keywords=keywords,
        limit=limit
    )

    return {
        "total": len(products),
        "products": [p.to_dict() for p in products]
    }


def compare_products_tool(product_ids: List[str]) -> Dict[str, Any]:
    """
    对比商品

    对比多个商品的规格参数，生成对比结果。

    Args:
        product_ids: 商品ID列表

    Returns:
        对比结果
    """
    products = _knowledge_base.get_products_by_ids(product_ids)

    if len(products) < 2:
        return {
            "error": "至少需要2个商品进行对比"
        }

    # 生成对比
    comparison = {
        "products": [p.to_dict() for p in products],
        "comparison_points": {}
    }

    # 收集所有属性
    all_attrs = set()
    for p in products:
        all_attrs.update(p.attributes.keys())

    # 对比每个属性
    for attr in sorted(all_attrs):
        comparison["comparison_points"][attr] = {
            p.id: p.attributes.get(attr, "-")
            for p in products
        }

    # 价格对比
    comparison["comparison_points"]["价格"] = {
        p.id: f"¥{p.price}"
        for p in products
    }

    # 评分对比
    comparison["comparison_points"]["评分"] = {
        p.id: f"{p.rating}⭐"
        for p in products
    }

    # 推荐
    best = max(products, key=lambda p: (p.rating, p.sales))
    comparison["recommendation"] = f"综合推荐：{best.name}，评分{best.rating}分，销量{best.sales}"

    return comparison


def get_product_detail_tool(product_id: str) -> Dict[str, Any]:
    """
    获取商品详情

    获取指定商品的详细信息。

    Args:
        product_id: 商品ID

    Returns:
        商品详情
    """
    product = _knowledge_base.get_product(product_id)

    if not product:
        return {
            "error": f"商品 {product_id} 不存在"
        }

    return {
        "product": product.to_dict(),
        "display_text": product.to_display_text()
    }


def get_categories_tool() -> Dict[str, Any]:
    """
    获取所有商品类别

    返回系统中所有可用的商品类别。

    Returns:
        类别列表
    """
    categories = _knowledge_base.get_categories()

    category_info = {}
    for cat in categories:
        brands = _knowledge_base.get_brands_by_category(cat)
        category_info[cat] = {
            "brands": brands,
            "brand_count": len(brands)
        }

    return {
        "categories": categories,
        "category_info": category_info
    }


# 工具函数列表，供LLM调用
TOOLS_REGISTRY = {
    "search_products": {
        "function": search_products_tool,
        "description": "搜索商品，支持按类别、品牌、价格、关键词筛选",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "商品类别，如'笔记本'、'手机'、'耳机'"
                },
                "brands": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "品牌列表，如['小米', '华为', '苹果']"
                },
                "min_price": {
                    "type": "number",
                    "description": "最低价格"
                },
                "max_price": {
                    "type": "number",
                    "description": "最高价格"
                },
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "关键词列表，如['游戏', '降噪']"
                },
                "limit": {
                    "type": "integer",
                    "description": "返回数量限制，默认10"
                }
            }
        }
    },
    "compare_products": {
        "function": compare_products_tool,
        "description": "对比多个商品的规格参数",
        "parameters": {
            "type": "object",
            "properties": {
                "product_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "商品ID列表"
                }
            },
            "required": ["product_ids"]
        }
    },
    "get_product_detail": {
        "function": get_product_detail_tool,
        "description": "获取商品的详细信息",
        "parameters": {
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "商品ID"
                }
            },
            "required": ["product_id"]
        }
    },
    "get_categories": {
        "function": get_categories_tool,
        "description": "获取所有商品类别和品牌信息",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    }
}


def format_tools_for_llm() -> str:
    """格式化工具定义供LLM使用"""
    tools_desc = []
    for name, tool_info in TOOLS_REGISTRY.items():
        desc = f"## {name}\n"
        desc += f"描述: {tool_info['description']}\n"
        desc += f"参数: {tool_info['parameters']}\n"
        tools_desc.append(desc)
    return "\n".join(tools_desc)
