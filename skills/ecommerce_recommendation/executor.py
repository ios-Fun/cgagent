"""电商推荐Skill执行器

实现智能导购/商品推荐的核心逻辑
"""

import asyncio
import json
import logging
import re
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from .schema import (
    DialogueState,
    UserIntent,
    Constraint,
    DemandAnalysis,
    UserProfile,
    Product,
    RecommendedProduct,
    RecommendationResult,
    ProductComparison
)
from agent.connectors import BaseConnector, get_global_registry

logger = logging.getLogger(__name__)


class EcommerceRecommendationExecutor:
    """
    电商推荐执行器

    协调需求分析、用户画像、商品搜索、推荐排序等子模块
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.connector_registry = get_global_registry()

        # 子模块
        self.demand_analyzer = DemandAnalyzer()
        self.user_profiler = UserProfiler()
        self.product_searcher = ProductSearcher()
        self.recommendation_ranker = RecommendationRanker()
        self.recommendation_explainer = RecommendationExplainer()

    async def execute(
        self,
        user_input: str,
        user_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> RecommendationResult:
        """
        执行推荐流程

        Args:
            user_input: 用户输入
            user_id: 用户ID
            context: 额外上下文

        Returns:
            RecommendationResult: 推荐结果
        """
        logger.info(f"执行推荐流程: user_input={user_input[:50]}, user_id={user_id}")

        # 步骤1: 需求分析
        demand_analysis = await self.demand_analyzer.analyze(user_input, context)

        # 检查是否需要澄清
        if demand_analysis.missing_info:
            return await self._generate_clarification_response(
                user_input, user_id, demand_analysis
            )

        # 步骤2: 用户画像
        user_profile = None
        if user_id:
            user_profile = await self.user_profiler.get_profile(user_id, demand_analysis.category)

        # 步骤3: 商品搜索
        search_results = await self.product_searcher.search(
            demand_analysis=demand_analysis,
            user_profile=user_profile
        )

        if not search_results["products"]:
            return await self._generate_no_result_response(
                user_input, user_id, demand_analysis
            )

        # 步骤4: 推荐排序
        ranked_products = await self.recommendation_ranker.rank(
            candidates=search_results["products"],
            demand_analysis=demand_analysis,
            user_profile=user_profile
        )

        # 步骤5: 推荐解释
        response_text = await self.recommendation_explainer.explain(
            user_input=user_input,
            demand_analysis=demand_analysis,
            recommendations=ranked_products[:5]  # Top 5
        )

        return RecommendationResult(
            query_id=f"query_{asyncio.get_event_loop().time()}",
            user_id=user_id,
            dialogue_state=DialogueState.RECOMMENDATION_READY,
            demand_analysis=demand_analysis,
            user_profile=user_profile,
            recommendations=ranked_products[:5],
            total_candidates=len(search_results["products"]),
            response_text=response_text,
            metadata={
                "search_time": search_results.get("search_time"),
                "total_found": search_results.get("total_found", 0)
            }
        )

    async def compare_products(
        self,
        product_names: List[str],
        user_id: Optional[str] = None
    ) -> ProductComparison:
        """对比商品"""
        products = await self.product_searcher.search_by_names(product_names)
        comparison = await self._generate_comparison(products)
        return comparison

    async def _generate_clarification_response(
        self,
        user_input: str,
        user_id: Optional[str],
        demand_analysis: DemandAnalysis
    ) -> RecommendationResult:
        """生成澄清响应"""
        clarifications = []
        for info in demand_analysis.missing_info[:3]:
            clarifications.append(f"- 请问您的{info}是什么？")

        response_text = (
            f"我理解您想要{demand_analysis.category or '商品'}。\n"
            f"为了给您更精准的推荐，请补充以下信息：\n"
            f"\n{''.join(clarifications)}"
        )

        return RecommendationResult(
            query_id=f"query_clarify_{asyncio.get_event_loop().time()}",
            user_id=user_id,
            dialogue_state=DialogueState.AWAITING_CLARIFICATION,
            demand_analysis=demand_analysis,
            user_profile=None,
            recommendations=[],
            total_candidates=0,
            response_text=response_text
        )

    async def _generate_no_result_response(
        self,
        user_input: str,
        user_id: Optional[str],
        demand_analysis: DemandAnalysis
    ) -> RecommendationResult:
        """生成无结果响应"""
        response_text = (
            f"抱歉，没有找到符合您要求的{demand_analysis.category or '商品'}。\n"
            f"建议您：\n"
            f"- 调整预算范围\n"
            f"- 尝试其他品牌\n"
            f"- 放宽部分筛选条件"
        )

        return RecommendationResult(
            query_id=f"query_no_result_{asyncio.get_event_loop().time()}",
            user_id=user_id,
            dialogue_state=DialogueState.INFORMATION_GATHERING,
            demand_analysis=demand_analysis,
            user_profile=None,
            recommendations=[],
            total_candidates=0,
            response_text=response_text
        )

    async def _generate_comparison(self, products: List[Product]) -> ProductComparison:
        """生成对比结果"""
        if len(products) < 2:
            raise ValueError("至少需要2个商品进行对比")

        comparison_points = {}

        # 价格对比
        comparison_points["price"] = {
            p.name: {"value": p.price, "text": f"¥{p.price}"}
            for p in products
        }

        # 评分对比
        comparison_points["rating"] = {
            p.name: {"value": p.rating, "text": f"{p.rating}分"}
            for p in products
        }

        # 属性对比
        all_attributes = set()
        for p in products:
            all_attributes.update(p.attributes.keys())

        for attr in all_attributes:
            comparison_points[attr] = {
                p.name: {"value": p.attributes.get(attr), "text": str(p.attributes.get(attr, "-"))}
                for p in products
            }

        # 推荐结论
        best_product = max(products, key=lambda p: (p.rating, p.sales))
        recommendation = f"综合来看，{best_product.name} 性价比较高，评分{best_product.rating}分"

        return ProductComparison(
            products=products,
            comparison_points=comparison_points,
            recommendation=recommendation
        )


class DemandAnalyzer:
    """需求分析器"""

    async def analyze(
        self,
        user_input: str,
        context: Optional[Dict[str, Any]] = None
    ) -> DemandAnalysis:
        """分析用户需求"""
        # 简化版实现 - 实际应使用LLM或NLP模型
        constraints = []
        missing_info = []

        # 判断是否是澄清回答（简短的回答式输入）
        is_clarification_response = self._is_clarification_response(user_input)

        # 检测类别（优先从上下文获取，特别是澄清回答时）
        category = self._extract_category(user_input)
        if not category and (context or is_clarification_response):
            category = context.get("category") if context else None
            if category:
                logger.info(f"从上下文获取商品类别: {category}")
        if not category:
            missing_info.append("商品类别")

        # 检测价格区间（优先从上下文获取）
        price_range = self._extract_price_range(user_input)
        if not price_range and (context or is_clarification_response):
            price_range = context.get("price_range") if context else None
            if price_range:
                logger.info(f"从上下文获取价格范围: {price_range}")
        if price_range:
            constraints.append(Constraint(
                type="price_range",
                value=price_range,
                required=True
            ))
        else:
            # 只有在非澄清回答时才提示缺失价格
            if not is_clarification_response:
                missing_info.append("预算范围")

        # 检测品牌（保存到上下文）
        brands = self._extract_brands(user_input)
        if brands:
            constraints.append(Constraint(
                type="brand",
                value=brands,
                required=False
            ))

        # 检测用途
        use_case = self._extract_use_case(user_input)
        if use_case:
            constraints.append(Constraint(
                type="use_case",
                value=use_case,
                required=False
            ))

        # 检测意图
        intent = self._detect_intent(user_input)

        return DemandAnalysis(
            intent=intent,
            category=category,
            constraints=constraints,
            missing_info=missing_info
        )

    def _is_clarification_response(self, text: str) -> bool:
        """判断是否是澄清回答（简短的补充信息）"""
        # 简短的回答（少于20字且包含数字或品牌）
        if len(text) < 20:
            # 包含价格信息
            if re.search(r'\d{3,5}', text):
                return True
            # 包含品牌名
            if any(brand in text for brand in ["小米", "华为", "苹果", "拯救者", "联想"]):
                return True
            # 纯数字
            if text.strip().isdigit():
                return True
        return False

    def _extract_category(self, text: str) -> Optional[str]:
        """提取商品类别"""
        categories = ["手机", "耳机", "电脑", "平板", "手表", "相机", "音箱", "笔记本"]
        for cat in categories:
            if cat in text:
                return cat

        # 特殊处理：拯救者是游戏笔记本品牌
        if "拯救者" in text:
            return "笔记本"

        return None

    def _extract_price_range(self, text: str) -> Optional[Dict[str, float]]:
        """提取价格区间"""
        import re
        # 匹配 "2000-3000" 或 "2000到3000" 或 "2000~3000"
        pattern = r'(\d+)[-~到](\d+)'
        match = re.search(pattern, text)
        if match:
            return {"min": float(match.group(1)), "max": float(match.group(2))}

        # 匹配 "500元左右" 或 "500元以内" 或 "预算500左右"
        pattern = r'(\d+)(?:元)?(?:左右|以内|以下)'
        match = re.search(pattern, text)
        if match:
            price = float(match.group(1))
            return {"min": 0, "max": price * 1.2}

        # 匹配 "预算8000" 或 "8000预算"
        pattern = r'(?:预算)?(\d{3,5})(?:元)?(?:预算)?'
        match = re.search(pattern, text)
        if match:
            price = float(match.group(1))
            return {"min": 0, "max": price * 1.1}

        return None

    def _extract_brands(self, text: str) -> Optional[List[str]]:
        """提取品牌"""
        brands = ["小米", "华为", "苹果", "三星", "OPPO", "vivo", "一加", "iQOO", "红米", "荣耀", "拯救者", "联想", "戴尔", "惠普", "华硕", "雷神"]
        found = [b for b in brands if b in text]
        return found if found else None

    def _extract_use_case(self, text: str) -> Optional[str]:
        """提取用途"""
        use_cases = {
            "游戏": ["游戏", "玩游戏", "电竞"],
            "拍照": ["拍照", "摄影", "相机"],
            "办公": ["办公", "工作", "商务"],
            "音乐": ["音乐", "听歌", "音质"]
        }
        for use_case, keywords in use_cases.items():
            if any(kw in text for kw in keywords):
                return use_case
        return None

    def _detect_intent(self, text: str) -> UserIntent:
        """检测用户意图"""
        if any(kw in text for kw in ["推荐", "推荐一下", "有什么好"]):
            return UserIntent.RECOMMENDATION_REQUEST
        elif any(kw in text for kw in ["对比", "哪个好", "区别"]):
            return UserIntent.COMPARISON_REQUEST
        elif "买" in text or "购" in text:
            return UserIntent.PRODUCT_INQUIRY
        else:
            return UserIntent.GENERAL_CHAT


class UserProfiler:
    """用户画像器"""

    async def get_profile(
        self,
        user_id: str,
        category: Optional[str] = None
    ) -> Optional[UserProfile]:
        """获取用户画像"""
        # 简化版 - 实际应从数据库或用户服务获取
        # 这里返回一个示例画像
        return UserProfile(
            user_id=user_id,
            preferred_brands=["小米", "华为"],
            price_preference="medium",
            recent_views=["Redmi K70", "华为Mate60"],
            purchase_history=[
                {"product": "小米13", "date": "2023-10", "price": 3999}
            ],
            preference_tags=["性价比", "游戏"],
            demographics={"age_group": "25-35", "city_level": 1}
        )


class ProductSearcher:
    """商品搜索器"""

    async def search(
        self,
        demand_analysis: DemandAnalysis,
        user_profile: Optional[UserProfile] = None
    ) -> Dict[str, Any]:
        """搜索商品"""
        # 简化版 - 返回模拟数据
        # 实际应从数据库或搜索引擎查询

        category = demand_analysis.category or "手机"

        # 模拟商品数据
        if category == "耳机":
            mock_products = [
                Product(
                    product_id="e_001",
                    name="小米Air2 SE",
                    brand="小米",
                    price=199,
                    category=category,
                    description="半入耳式无线耳机，续航20小时",
                    attributes={
                        "type": "半入耳式",
                        "connectivity": "蓝牙5.0",
                        "battery": "4小时",
                        "charging_case": "20小时"
                    },
                    rating=4.3,
                    sales=100000,
                    stock=5000
                ),
                Product(
                    product_id="e_002",
                    name="华为FreeBuds 4i",
                    brand="华为",
                    price=499,
                    category=category,
                    description="主动降噪耳机，续航22小时",
                    attributes={
                        "type": "入耳式",
                        "connectivity": "蓝牙5.2",
                        "battery": "7.5小时",
                        "charging_case": "22小时",
                        "noise_cancelling": "主动降噪"
                    },
                    rating=4.5,
                    sales=50000,
                    stock=2000
                ),
                Product(
                    product_id="e_003",
                    name="Apple AirPods Pro",
                    brand="苹果",
                    price=1899,
                    category=category,
                    description="苹果旗舰降噪耳机，空间音频",
                    attributes={
                        "type": "入耳式",
                        "connectivity": "蓝牙5.3",
                        "battery": "6小时",
                        "charging_case": "30小时",
                        "noise_cancelling": "主动降噪",
                        "spatial_audio": "空间音频"
                    },
                    rating=4.7,
                    sales=80000,
                    stock=1500
                ),
                Product(
                    product_id="e_004",
                    name="索尼WF-1000XM4",
                    brand="索尼",
                    price=1299,
                    category=category,
                    description="索尼旗舰降噪耳机，音质出色",
                    attributes={
                        "type": "入耳式",
                        "connectivity": "蓝牙5.2",
                        "battery": "8小时",
                        "charging_case": "24小时",
                        "noise_cancelling": "主动降噪"
                    },
                    rating=4.6,
                    sales=60000,
                    stock=1800
                ),
                Product(
                    product_id="e_005",
                    name="JBL Free X",
                    brand="JBL",
                    price=599,
                    category=category,
                    description="JBL运动耳机，防水防汗",
                    attributes={
                        "type": "入耳式",
                        "connectivity": "蓝牙5.0",
                        "battery": "4小时",
                        "charging_case": "16小时",
                        "waterproof": "IPX5",
                        "sports": "运动型"
                    },
                    rating=4.4,
                    sales=30000,
                    stock=1000
                )
            ]
        else:
            # 根据类别返回不同的商品
            if category == "笔记本":
                mock_products = [
                    Product(
                        product_id="l_001",
                        name="拯救者Y7000P",
                        brand="拯救者",
                        price=7999,
                        category=category,
                        description="联想拯救者游戏本，i7处理器，RTX4060",
                        attributes={
                            "screen": "15.6英寸 2.5K 165Hz",
                            "processor": "i7-13700HX",
                            "gpu": "RTX 4060",
                            "battery": "80Wh",
                            "ram": "16GB DDR5",
                            "storage": "1TB SSD"
                        },
                        rating=4.8,
                        sales=80000,
                        stock=500
                    ),
                    Product(
                        product_id="l_002",
                        name="拯救者Y9000P",
                        brand="拯救者",
                        price=9999,
                        category=category,
                        description="联想拯救者高端游戏本，i9处理器，RTX4070",
                        attributes={
                            "screen": "16英寸 2.5K 240Hz",
                            "processor": "i9-13900HX",
                            "gpu": "RTX 4070",
                            "battery": "99.9Wh",
                            "ram": "32GB DDR5",
                            "storage": "1TB SSD"
                        },
                        rating=4.9,
                        sales=60000,
                        stock=300
                    ),
                    Product(
                        product_id="l_003",
                        name="联想小新Pro16",
                        brand="联想",
                        price=5999,
                        category=category,
                        description="轻薄高性能本，适合办公和学习",
                        attributes={
                            "screen": "16英寸 2.5K 120Hz",
                            "processor": "i7-13700H",
                            "battery": "75Wh",
                            "ram": "16GB DDR5",
                            "storage": "512GB SSD"
                        },
                        rating=4.6,
                        sales=40000,
                        stock=800
                    )
                ]
            else:
                # 默认手机商品
                mock_products = [
                    Product(
                        product_id="p_001",
                        name="Redmi K70",
                        brand="小米",
                        price=2499,
                        category=category,
                        description="骁龙8 Gen2处理器，2K 120Hz屏幕",
                        attributes={
                            "screen": "6.67英寸 2K 120Hz",
                            "processor": "骁龙8 Gen2",
                            "battery": "5000mAh",
                            "charging": "120W快充"
                        },
                        rating=4.7,
                        sales=50000,
                        stock=1000
                    ),
                    Product(
                        product_id="p_002",
                        name="iQOO Neo9",
                        brand="iQOO",
                        price=2299,
                        category=category,
                        description="144Hz电竞屏，专为游戏优化",
                        attributes={
                            "screen": "6.78英寸 144Hz",
                            "processor": "骁龙8 Gen2",
                            "battery": "5160mAh",
                            "charging": "120W快充"
                        },
                        rating=4.6,
                        sales=30000,
                        stock=800
                    ),
                    Product(
                        product_id="p_003",
                        name="一加Ace 3",
                        brand="一加",
                        price=2599,
                        category=category,
                        description="质感出色，系统流畅",
                        attributes={
                            "screen": "6.78英寸 1.5K 120Hz",
                            "processor": "骁龙8 Gen2",
                            "battery": "5500mAh",
                            "charging": "100W快充"
                        },
                        rating=4.5,
                        sales=25000,
                        stock=600
                    )
                ]

        # 应用价格过滤
        price_constraint = next(
            (c for c in demand_analysis.constraints if c.type == "price_range"),
            None
        )
        if price_constraint:
            min_price = price_constraint.value.get("min", 0)
            max_price = price_constraint.value.get("max", float("inf"))
            mock_products = [
                p for p in mock_products
                if min_price <= p.price <= max_price
            ]

        return {
            "products": mock_products,
            "total_found": len(mock_products),
            "search_time": 0.05
        }

    async def search_by_names(self, product_names: List[str]) -> List[Product]:
        """根据名称搜索商品"""
        # 简化实现
        mock_products = {
            "Redmi K70": Product(
                product_id="p_001",
                name="Redmi K70",
                brand="小米",
                price=2499,
                category="手机",
                rating=4.7,
                attributes={"processor": "骁龙8 Gen2"}
            ),
            "iQOO Neo9": Product(
                product_id="p_002",
                name="iQOO Neo9",
                brand="iQOO",
                price=2299,
                category="手机",
                rating=4.6,
                attributes={"processor": "骁龙8 Gen2"}
            )
        }
        return [mock_products.get(name) for name in product_names if name in mock_products]


class RecommendationRanker:
    """推荐排序器"""

    async def rank(
        self,
        candidates: List[Product],
        demand_analysis: DemandAnalysis,
        user_profile: Optional[UserProfile] = None
    ) -> List[RecommendedProduct]:
        """对商品进行排序"""
        scored_products = []

        for product in candidates:
            # 计算匹配分数
            match_factors = {}
            total_score = 0.0

            # 价格匹配
            price_constraint = next(
                (c for c in demand_analysis.constraints if c.type == "price_range"),
                None
            )
            if price_constraint:
                price_range = price_constraint.value
                mid_price = (price_range["min"] + price_range["max"]) / 2
                price_diff = abs(product.price - mid_price) / mid_price
                price_score = max(0, 1 - price_diff)
                match_factors["price_match"] = price_score
                total_score += price_score * 0.3

            # 品牌偏好
            if user_profile and product.brand in user_profile.preferred_brands:
                match_factors["brand_preference"] = 0.9
                total_score += 0.9 * 0.2
            else:
                match_factors["brand_preference"] = 0.5
                total_score += 0.5 * 0.2

            # 评分
            rating_score = product.rating / 5.0
            match_factors["rating"] = rating_score
            total_score += rating_score * 0.3

            # 销量
            sales_score = min(1.0, product.sales / 100000)
            match_factors["sales"] = sales_score
            total_score += sales_score * 0.2

            # 生成推荐理由
            reasons = self._generate_reasons(product, match_factors)

            scored_products.append(
                RecommendedProduct(
                    rank=0,  # 稍后设置
                    product=product,
                    total_score=total_score,
                    match_factors=match_factors,
                    recommendation_reasons=reasons
                )
            )

        # 排序
        scored_products.sort(key=lambda x: x.total_score, reverse=True)

        # 设置排名
        for i, p in enumerate(scored_products, 1):
            p.rank = i

        return scored_products

    def _generate_reasons(
        self,
        product: Product,
        match_factors: Dict[str, float]
    ) -> List[str]:
        """生成推荐理由"""
        reasons = []

        if match_factors.get("price_match", 0) > 0.8:
            reasons.append(f"价格符合您的预算范围 (¥{product.price})")

        if match_factors.get("rating", 0) > 0.8:
            reasons.append(f"好评率高 ({product.rating}分)")

        if product.attributes.get("processor"):
            reasons.append(f"性能强劲 ({product.attributes['processor']})")

        if product.attributes.get("charging"):
            reasons.append(f"快充支持 ({product.attributes['charging']})")

        return reasons


class RecommendationExplainer:
    """推荐解释生成器"""

    async def explain(
        self,
        user_input: str,
        demand_analysis: DemandAnalysis,
        recommendations: List[RecommendedProduct]
    ) -> str:
        """生成推荐说明"""
        if not recommendations:
            return "抱歉，没有找到符合您要求的商品。"

        top_product = recommendations[0]
        product = top_product.product

        # 生成推荐文本
        lines = [
            f"根据您的需求，我为您推荐以下商品：\n",
            f"**首选推荐：{product.name} (¥{product.price})**\n",
            "推荐理由："
        ]

        # 添加推荐理由
        for reason in top_product.recommendation_reasons[:4]:
            lines.append(f"- {reason}")

        # 添加备选方案
        if len(recommendations) > 1:
            lines.append("\n**备选方案：**\n")
            for rec in recommendations[1:4]:
                p = rec.product
                lines.append(
                    f"{rec.rank}. {p.name} (¥{p.price}) - "
                    f"{', '.join(rec.recommendation_reasons[:2])}"
                )

        lines.append(f"\n需要我详细介绍哪款商品的更多信息吗？")

        return "\n".join(lines)
