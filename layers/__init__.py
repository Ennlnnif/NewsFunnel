# AI Daily News — 四层处理模块
# Layer 1: collector (收集)   ✅ 已实现（6 种 Fetcher：RSS/GitHub/Exa/Twitter/WeChat/Manual）
# Layer 2: filter (筛选)      ✅ 已实现（两道漏斗：相关性硬筛 + 五维度热度评分）
# Layer 3: editor (编辑)      ✅ 已实现（按板块 LLM 摘要 + Markdown 日报生成）
# Layer 4: archiver (归档)    ✅ 已实现（手动触发产品深度分析报告）

from .collector import RawArticle, run_collector
from .filter import run_filter
from .editor import run_editor
from .archiver import run_archiver

__all__ = ["RawArticle", "run_collector", "run_filter", "run_editor", "run_archiver"]
