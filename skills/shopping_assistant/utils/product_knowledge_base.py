"""商品知识库 - 存储和检索商品信息"""

from typing import List, Dict, Any, Optional
from ..schema import Product


class ProductKnowledgeBase:
    """商品知识库"""

    def __init__(self):
        self._products: Dict[str, Product] = {}
        self._category_index: Dict[str, List[str]] = {}
        self._brand_index: Dict[str, List[str]] = {}
        self._price_index: Dict[tuple, List[str]] = {}  # (category, price_range) -> product_ids

        # 初始化商品数据
        self._init_products()

    def _init_products(self):
        """初始化商品数据"""

        # ========== 笔记本电脑 ==========
        laptops = [
            Product(
                id="l_001",
                name="拯救者Y7000P",
                brand="拯救者",
                price=7999,
                category="笔记本",
                description="联想拯救者游戏本，强劲散热，适合游戏和创作",
                attributes={
                    "screen": "15.6英寸 2.5K 165Hz IPS",
                    "processor": "i7-13700HX",
                    "gpu": "RTX 4060 6GB",
                    "ram": "16GB DDR5 4800MHz",
                    "storage": "1TB NVMe SSD",
                    "battery": "80Wh",
                    "weight": "2.55kg",
                    "cooling": "霜刃Pro散热系统5.0"
                },
                rating=4.8,
                sales=85000,
                stock=500,
                tags=["游戏", "高性能", "电竞", "创作"]
            ),
            Product(
                id="l_002",
                name="拯救者Y9000P",
                brand="拯救者",
                price=12999,
                category="笔记本",
                description="联想拯救者旗舰游戏本，顶级配置，专业电竞",
                attributes={
                    "screen": "16英寸 2.5K 240Hz IPS",
                    "processor": "i9-13900HX",
                    "gpu": "RTX 4070 8GB",
                    "ram": "32GB DDR5 5600MHz",
                    "storage": "1TB NVMe SSD",
                    "battery": "99.9Wh",
                    "weight": "2.7kg",
                    "cooling": "霜刃Pro散热系统5.0"
                },
                rating=4.9,
                sales=65000,
                stock=300,
                tags=["游戏", "旗舰", "电竞", "专业", "创作"]
            ),
            Product(
                id="l_003",
                name="联想小新Pro16",
                brand="联想",
                price=5999,
                category="笔记本",
                description="轻薄高性能本，适合办公、学习和轻度创作",
                attributes={
                    "screen": "16英寸 2.5K 120Hz IPS",
                    "processor": "i7-13700H",
                    "gpu": "集成显卡",
                    "ram": "16GB DDR5",
                    "storage": "512GB NVMe SSD",
                    "battery": "75Wh",
                    "weight": "1.93kg"
                },
                rating=4.6,
                sales=120000,
                stock=1000,
                tags=["办公", "轻薄", "学生", "性价比"]
            ),
            Product(
                id="l_004",
                name="MacBook Pro 14",
                brand="苹果",
                price=14999,
                category="笔记本",
                description="苹果专业笔记本，M3芯片，适合创作者",
                attributes={
                    "screen": "14英寸 Liquid Retina XDR",
                    "processor": "M3 Pro",
                    "gpu": "18核GPU",
                    "ram": "18GB",
                    "storage": "512GB SSD",
                    "battery": "70Wh",
                    "weight": "1.61kg"
                },
                rating=4.9,
                sales=45000,
                stock=200,
                tags=["苹果", "创作", "专业", "轻薄"]
            ),
            Product(
                id="l_005",
                name="华硕天选5 Pro",
                brand="华硕",
                price=7499,
                category="笔记本",
                description="二次元电竞游戏本，高颜值高性能",
                attributes={
                    "screen": "16英寸 2.5K 165Hz",
                    "processor": "R9-7940HX",
                    "gpu": "RTX 4060",
                    "ram": "16GB DDR5",
                    "storage": "1TB SSD",
                    "battery": "90Wh",
                    "weight": "2.5kg"
                },
                rating=4.7,
                sales=55000,
                stock=400,
                tags=["游戏", "电竞", "二次元", "性价比"]
            ),
        ]

        # ========== 手机 ==========
        phones = [
            Product(
                id="p_001",
                name="小米14 Pro",
                brand="小米",
                price=4999,
                category="手机",
                description="徕卡光学镜头，骁龙8 Gen3，全能旗舰",
                attributes={
                    "screen": "6.73英寸 2K AMOLED 120Hz",
                    "processor": "骁龙8 Gen3",
                    "ram": "12GB",
                    "storage": "256GB",
                    "battery": "4880mAh",
                    "charging": "120W有线 + 50W无线",
                    "camera": "徕卡三主摄 50MP"
                },
                rating=4.7,
                sales=95000,
                stock=2000,
                tags=["旗舰", "拍照", "徕卡", "性价比"]
            ),
            Product(
                id="p_002",
                name="华为Mate 60 Pro",
                brand="华为",
                price=6999,
                category="手机",
                description="卫星通信，玄武架构，回归之作",
                attributes={
                    "screen": "6.82英寸 OLED 120Hz",
                    "processor": "麒麟9000S",
                    "ram": "12GB",
                    "storage": "256GB",
                    "battery": "5000mAh",
                    "charging": "88W有线 + 50W无线",
                    "camera": "XMAGE可变光圈 50MP"
                },
                rating=4.8,
                sales=150000,
                stock=800,
                tags=["旗舰", "拍照", "卫星通信", "华为"]
            ),
            Product(
                id="p_003",
                name="iPhone 15 Pro",
                brand="苹果",
                price=7999,
                category="手机",
                description="钛金属设计，A17 Pro芯片，专业级性能",
                attributes={
                    "screen": "6.1英寸 Super Retina XDR 120Hz",
                    "processor": "A17 Pro",
                    "ram": "8GB",
                    "storage": "128GB",
                    "battery": "3274mAh",
                    "charging": "20W有线 + 15W无线",
                    "camera": "48MP主摄 + 12MP长焦"
                },
                rating=4.8,
                sales=200000,
                stock=3000,
                tags=["苹果", "旗舰", "游戏", "视频"]
            ),
            Product(
                id="p_004",
                name="iQOO 12",
                brand="iQOO",
                price=3999,
                category="手机",
                description="电竞芯片，144Hz屏幕，性能怪兽",
                attributes={
                    "screen": "6.78英寸 1.5K AMOLED 144Hz",
                    "processor": "骁龙8 Gen3",
                    "ram": "12GB",
                    "storage": "256GB",
                    "battery": "5000mAh",
                    "charging": "120W",
                    "camera": "50MP主摄 + OIS"
                },
                rating=4.6,
                sales=75000,
                stock=1500,
                tags=["游戏", "电竞", "性价比", "快充"]
            ),
        ]

        # ========== 耳机 ==========
        earphones = [
            Product(
                id="e_001",
                name="华为FreeBuds Pro 3",
                brand="华为",
                price=1299,
                category="耳机",
                description="智慧动态降噪，CD级音质",
                attributes={
                    "type": "入耳式",
                    "connectivity": "蓝牙5.3",
                    "battery": "7小时(耳机) + 30小时(盒子)",
                    "noise_cancelling": "智慧动态降噪 -48dB",
                    "driver": "11mm动圈 + 微平板单元",
                    "waterproof": "IP54"
                },
                rating=4.7,
                sales=85000,
                stock=2000,
                tags=["降噪", "通勤", "办公", "音质"]
            ),
            Product(
                id="e_002",
                name="AirPods Pro 2",
                brand="苹果",
                price=1899,
                category="耳机",
                description="苹果旗舰降噪耳机，空间音频",
                attributes={
                    "type": "入耳式",
                    "connectivity": "蓝牙5.3",
                    "battery": "6小时(耳机) + 30小时(盒子)",
                    "noise_cancelling": "主动降噪",
                    "chip": "H2芯片",
                    "feature": "空间音频，自适应透明模式"
                },
                rating=4.8,
                sales=180000,
                stock=3000,
                tags=["苹果", "降噪", "运动", "通勤"]
            ),
            Product(
                id="e_003",
                name="索尼WF-1000XM5",
                brand="索尼",
                price=1899,
                category="耳机",
                description="索尼旗舰降噪耳机，业界顶尖音质",
                attributes={
                    "type": "入耳式",
                    "connectivity": "蓝牙5.3",
                    "battery": "8小时(耳机) + 24小时(盒子)",
                    "noise_cancelling": "主动降噪 -",
                    "driver": "8.4mm动圈 x2",
                    "feature": "LDAC编码，360音效"
                },
                rating=4.8,
                sales=65000,
                stock=1200,
                tags=["降噪", "音质", "发烧", "通勤"]
            ),
            Product(
                id="e_004",
                name="小米Buds 4 Pro",
                brand="小米",
                price=699,
                category="耳机",
                description="旗舰降噪，超长续航",
                attributes={
                    "type": "入耳式",
                    "connectivity": "蓝牙5.3",
                    "battery": "9小时(耳机) + 38小时(盒子)",
                    "noise_cancelling": "自适应降噪 -48dB",
                    "driver": "11mm动圈",
                    "feature": "空间音频，双设备连接"
                },
                rating=4.5,
                sales=95000,
                stock=2500,
                tags=["降噪", "性价比", "通勤", "运动"]
            ),
        ]

        # 添加所有商品
        all_products = laptops + phones + earphones
        for product in all_products:
            self.add_product(product)

    def add_product(self, product: Product):
        """添加商品"""
        self._products[product.id] = product

        # 类别索引
        if product.category not in self._category_index:
            self._category_index[product.category] = []
        self._category_index[product.category].append(product.id)

        # 品牌索引
        if product.brand not in self._brand_index:
            self._brand_index[product.brand] = []
        self._brand_index[product.brand].append(product.id)

    def search(
        self,
        category: Optional[str] = None,
        brands: Optional[List[str]] = None,
        price_range: Optional[Dict[str, float]] = None,
        keywords: Optional[List[str]] = None,
        limit: int = 10
    ) -> List[Product]:
        """搜索商品"""
        candidates = list(self._products.values())

        # 类别过滤
        if category:
            candidates = [p for p in candidates if p.category == category]

        # 品牌过滤
        if brands:
            candidates = [p for p in candidates if p.brand in brands]

        # 价格过滤
        if price_range:
            min_price = price_range.get("min", 0)
            max_price = price_range.get("max", float("inf"))
            candidates = [p for p in candidates if min_price <= p.price <= max_price]

        # 关键词过滤
        if keywords:
            candidates = [
                p for p in candidates
                if any(
                    kw in p.name.lower() or kw in p.description.lower() or kw in str(p.attributes).lower()
                    for kw in [k.lower() for k in keywords]
                )
            ]

        # 按评分和销量排序
        candidates.sort(key=lambda p: (p.rating, p.sales), reverse=True)

        return candidates[:limit]

    def get_product(self, product_id: str) -> Optional[Product]:
        """获取单个商品"""
        return self._products.get(product_id)

    def get_products_by_ids(self, product_ids: List[str]) -> List[Product]:
        """根据ID列表获取商品"""
        return [self._products[pid] for pid in product_ids if pid in self._products]

    def get_categories(self) -> List[str]:
        """获取所有类别"""
        return list(self._category_index.keys())

    def get_brands_by_category(self, category: str) -> List[str]:
        """获取指定类别下的品牌"""
        product_ids = self._category_index.get(category, [])
        brands = set()
        for pid in product_ids:
            product = self._products.get(pid)
            if product:
                brands.add(product.brand)
        return list(brands)
