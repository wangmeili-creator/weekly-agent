"""课程周报智能体 · 工具层

本模块实现设计方案中的 5 个工具，并为每个工具提供 JSON Schema 声明。
工具只负责“读、抽、查、渲染、校验”，不做任何推断，符合“事实可追溯”的约束。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 第 5 轮修正："周末"也是日期标题，否则其后条目会被并入周五而挤掉配额
DAY_HEADER = re.compile(r"^(周[一二三四五六日天末]|星期[一二三四五六日天])\s*$")
# 第 3 轮修正：上一版负向断言会截断 "17"；改为抽取前把 F1 占位，避免把模型名拆成数值
NUM_RE = re.compile(r"\d+(?:\.\d+)?%?")
# 第 2 轮修正：序数（第4课 / 第3章）不进入量化指标
ORDINAL_RE = re.compile(r"第\s*\d+\s*[课章节天周]")
ISSUE_WORDS = ("KeyError", "TypeError", "ValueError", "报错", "异常", "没做完", "卡", "低", "不够", "缺", "失败")
CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("实验", ("实验课", "baseline", "F1", "重跑", "清洗数据")),
    ("项目", ("小组", "项目", "组会", "分工", "demo", "检索", "助手", "向量库", "前端", "联调", "卡点", "评估", "群")),
    ("论文", ("论文", "ReAct", "MemGPT", "笔记")),
    ("课程", ("第4课", "课", "老师", "助教")),
    # 第 5 轮修正：与协作相关的事项不再归为个人事务，避免与“未纳入正文”说明冲突
    ("事务", ("要还", "借的书", "杂事", "学一下")),
]
# 第 2 轮修正：去掉过宽的 "要"，它会把“要不要上向量库”误判为下周任务
PLAN_WORDS = ("下周", "待办", "准备", "计划", "需要")
# 第 2 轮修正：风险词收紧，避免“平均响应时间”命中“时间”
# 第 5 轮修正：借还书属个人事务，不进风险节
RISK_WORDS = ("时间不够", "时间紧", "来不及", "冲突", "没拉进")
DUE_RE = re.compile(r"(下?周[一二三四五六日天]|周[一二三四五六日天]|月底|本周)")


@dataclass
class Segment:
    """原始记录被切分后的最小条目。"""

    day: str
    index: int
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"day": self.day, "index": self.index, "text": self.text}


@dataclass
class Fact:
    """抽取出的可核查事实。numbers 原样保留，不做换算。"""

    day: str
    index: int
    text: str
    numbers: list[str] = field(default_factory=list)
    category: str = "其他"
    is_issue: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "index": self.index,
            "text": self.text,
            "numbers": self.numbers,
            "category": self.category,
            "is_issue": self.is_issue,
        }


# ---------------------------------------------------------------- 工具 1
def read_notes(path: str | Path) -> dict[str, Any]:
    """读取原始记录，按“日期标题 + 条目”切分。空行与标题行不产生条目。"""

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"找不到记录文件: {p}")

    segments: list[Segment] = []
    current_day = "未标注日期"
    index = 0
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if DAY_HEADER.match(line):
            current_day = line
            continue
        # 第 2 轮修正：Markdown 标题与分隔线不是记录条目
        if line.startswith("#") or set(line) <= {"-", "*", "="} or line in ("其他杂事", "其他", "杂事"):
            continue
        text = re.sub(r"^(?:[-*•]|\d+[.、)])\s*", "", line).strip()
        if len(text) < 4:
            continue
        index += 1
        segments.append(Segment(day=current_day, index=index, text=text))

    days = sorted({s.day for s in segments}, key=lambda d: _day_order(d))
    return {
        "path": str(p),
        "segment_count": len(segments),
        "days": days,
        "segments": [s.to_dict() for s in segments],
    }


def _day_order(day: str) -> int:
    table = {"周一": 1, "周二": 2, "周三": 3, "周四": 4, "周五": 5, "周六": 6, "周日": 7, "周天": 7, "周末": 7}
    for i in range(1, 8):
        table[f"星期{'一二三四五六日'[i - 1]}"] = i
    return table.get(day, 99)


# ---------------------------------------------------------------- 工具 2
def extract_facts(segments: list[dict[str, Any]]) -> dict[str, Any]:
    """抽取含数字、日期、人名、报错线索的条目，并标注归属类别。"""

    facts: list[Fact] = []
    for seg in segments:
        text = seg["text"]
        # 第 4 轮修正：占位符本身不能再含数字，否则 "F1X" 里的 1 又会被抽出
        numbers = NUM_RE.findall(ORDINAL_RE.sub("", text.replace("F1", "F_score")))
        facts.append(
            Fact(
                day=seg["day"],
                index=seg["index"],
                text=text,
                numbers=numbers,
                category=_classify(text),
                is_issue=any(w in text for w in ISSUE_WORDS),
            )
        )
    stats: dict[str, int] = {}
    for f in facts:
        stats[f.category] = stats.get(f.category, 0) + 1
    return {
        "fact_count": len(facts),
        "category_stats": stats,
        "facts": [f.to_dict() for f in facts],
    }


def _classify(text: str) -> str:
    for category, words in CATEGORY_RULES:
        if any(w in text for w in words):
            return category
    return "其他"


# ---------------------------------------------------------------- 工具 3
def retrieve_memory(memory: dict[str, Any], query: str = "", top_k: int = 5) -> dict[str, Any]:
    """按关键词从长期记忆召回组员、术语与未完成事项；空查询返回全部。"""

    pool: list[dict[str, Any]] = []
    for key in ("members", "terms", "unfinished", "reflections"):
        for item in memory.get(key, []):
            text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
            pool.append({"bucket": key, "text": text})

    if not query:
        return {"hits": pool[:top_k], "total": len(pool)}

    scored = []
    for item in pool:
        score = sum(1 for ch in set(query) if ch in item["text"])
        if score:
            scored.append((score, item))
    scored.sort(key=lambda x: (-x[0], len(x[1]["text"])))
    hits = [item for _, item in scored[:top_k]]
    return {"hits": hits, "total": len(hits)}


# ---------------------------------------------------------------- 工具 4
def render_report(sections: dict[str, Any], fmt: str = "md", out_dir: str = ".") -> dict[str, Any]:
    """按固定七节模板渲染 Markdown / docx，同源生成。"""

    from .render import render_docx, render_markdown

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    title = sections.get("title", "课程周报")
    written: list[str] = []
    if "md" in fmt:
        path = out / "weekly_report.md"
        path.write_text(render_markdown(sections), encoding="utf-8")
        written.append(str(path))
    if "docx" in fmt:
        path = out / "weekly_report.docx"
        render_docx(sections, path, title=title)
        written.append(str(path))
    return {"written": written}


# ---------------------------------------------------------------- 工具 5
REQUIRED_SECTIONS = ("overview", "progress", "issues", "metrics", "plan", "risks", "gaps")


def check_report(report: dict[str, Any], facts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """校验七节齐全、数字保真、缺口清单非空。返回问题列表而不是抛异常。"""

    problems: list[dict[str, str]] = []
    for key in REQUIRED_SECTIONS:
        value = report.get(key)
        if value is None or value == [] or value == "":
            problems.append({"type": "missing_section", "detail": f"缺少章节: {key}"})

    if facts:
        source_numbers = {n for f in facts for n in f.get("numbers", [])}
        rendered = json.dumps(report, ensure_ascii=False)
        for num in source_numbers:
            if num not in rendered:
                problems.append({"type": "number_lost", "detail": f"数字丢失: {num}"})

    gaps = report.get("gaps") or []
    if not gaps:
        problems.append({"type": "empty_gaps", "detail": "待补充信息为空，可能掩盖了缺失事实"})

    return {"ok": not problems, "problem_count": len(problems), "problems": problems}


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {"name": "read_notes", "description": "读取原始记录并按天切分", "parameters": {"path": "string"}},
    {"name": "extract_facts", "description": "抽取可核查事实并标类别", "parameters": {"segments": "array"}},
    {"name": "retrieve_memory", "description": "召回长期记忆", "parameters": {"query": "string", "top_k": "integer"}},
    {"name": "render_report", "description": "按模板渲染 md/docx", "parameters": {"sections": "object", "format": "string"}},
    {"name": "check_report", "description": "校验结构与数字保真", "parameters": {"report": "object", "facts": "array"}},
]