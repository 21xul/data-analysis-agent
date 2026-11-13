"""口径知识库：启动时灌入种子文档（幂等）。

注意：这里存的是「指标定义 / 字段语义 / 分析规范」，不是把 CSV 数据行向量化。
"""
from __future__ import annotations

import sqlite3

from app.infra import vector_store
from app.rag.embedder import embed

SEED_DOCS = [
    ("metric", "销售额", "销售额指已支付订单的实收金额，不含退款与运费；统计时按订单日期归属期，金额单位统一为元。"),
    ("metric", "GMV", "GMV 为下单总金额，包含未支付与后续退款订单，通常大于等于销售额；同比/环比时须注明口径。"),
    ("metric", "环比与同比", "环比 = (本期 - 上期) / |上期|；同比 = (本期 - 去年同期) / |去年同期|。基期为零或缺失时不计算增长率。"),
    ("metric", "退款率", "退款率 = 退款订单数 / 总订单数 × 100%，按自然月聚合；与退款金额口径不可混用。"),
    ("semantic", "字段语义映射", "用户说「营收」「流水」「金额」通常指销售额列；说「单量」「订单」指订单数列；说「渠道」「来源」指类目维度列。"),
    ("semantic", "时间字段", "日期列用于趋势聚合时，默认按月(M)分组；数据不足 3 期时不做趋势外推，只描述已知区间。"),
    ("policy", "异常判定", "异常识别默认使用 IQR 3 倍围栏与 |Z| ≥ 2.5 双重规则；异常占比超过 5% 时应提示检查数据质量而非直接下业务结论。"),
    ("policy", "结论写作规范", "结论必须引用工具返回的具体数字，不得编造字段、趋势或因果关系；事实不足时明确说明不下结论。"),
]


def ensure_index(conn: sqlite3.Connection) -> int:
    for kind, title, content in SEED_DOCS:
        vector_store.upsert(
            conn, kind=kind, title=title, content=content,
            vector=embed(f"{title} {content}"),
        )
    return vector_store.count(conn)
