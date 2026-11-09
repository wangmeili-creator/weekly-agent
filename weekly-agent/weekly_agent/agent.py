"""课程周报智能体 · 决策核心

结构：任务规划（清点记录 → 生成步骤）→ ReAct 循环（思考 / 行动 / 观察）→ 自检与修补。
无外部模型密钥时走确定性规则引擎；有 LLM 客户端时可替换 _compose 的生成部分，
工具调用、校验、记忆三层的接口保持不变。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .harness import Harness
from .memory import MemoryStore
from .tools import DUE_RE, PLAN_WORDS, RISK_WORDS

CATEGORY_LABELS = {
    "课程": "课程学习",
    "项目": "小组项目",
    "实验": "实验与指标",
    "论文": "论文阅读",
    "事务": "个人事务",
    "其他": "其他事项",
}


class WeeklyAgent:
    def __init__(self, harness: Harness, memory: MemoryStore, max_rounds: int = 6) -> None:
        self.harness = harness
        self.memory = memory
        self.max_rounds = max_rounds
        self.steps: list[dict[str, Any]] = []

    # ------------------------------------------------------------ 对外入口
    def run(
        self,
        input_path: str,
        out_dir: str,
        fmt: tuple[str, ...] = ("md", "docx"),
        title: str = "课程周报",
        week: str = "",
        owner: str = "",
    ) -> dict[str, Any]:
        notes = self._act("read_notes", path=input_path)
        if "error" in notes:
            raise RuntimeError(notes["error"])

        self._think(f"记录覆盖 {len(notes['days'])} 个时间分组、{notes['segment_count']} 条，先做任务规划")
        plan = self._make_plan(notes)

        query = " ".join(notes["days"][:3]) + " 组员 指标 待办"
        hits = self._act("retrieve_memory", memory=self.memory.data, query=query, top_k=5)

        sections: dict[str, Any] = {}
        check: dict[str, Any] = {}
        rounds = 0
        for rounds in range(1, self.max_rounds + 1):
            facts = self._act("extract_facts", segments=notes["segments"])
            self._think(f"第 {rounds} 轮：抽取到 {facts['fact_count']} 条事实，按七节骨架生成")
            sections = self._compose(notes, facts, hits, title=title, week=week, owner=owner)
            check = self._act("check_report", report=sections, facts=facts["facts"])
            self._think(f"自检结果：{'通过' if check['ok'] else str(check['problem_count']) + ' 个问题'}")
            if check["ok"]:
                break
            self._repair(sections, facts, check["problems"])

        paths = self._act("render_report", sections=sections, fmt=",".join(fmt), out_dir=out_dir)
        self.memory.archive(week or "未标注周次", sections.get("overview", "")[:120])
        self.memory.save()

        trace_path = Path(out_dir) / "trace.json"
        trace_path.write_text(
            json.dumps({"plan": plan, "steps": self.steps, "tool_calls": self.harness.dump_trace()}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return {
            "sections": sections,
            "check": check,
            "rounds": rounds,
            "plan": plan,
            "paths": paths["written"],
            "trace": str(trace_path),
            "tool_calls": len(self.harness.dump_trace()),
        }

    # ------------------------------------------------------------ ReAct 记录
    def _think(self, thought: str) -> None:
        self.steps.append({"type": "thought", "content": thought})

    def _act(self, tool: str, **kwargs: Any) -> dict[str, Any]:
        result = self.harness.call(tool, **kwargs)
        brief = {k: v for k, v in result.items() if k not in ("facts", "segments", "hits", "sections", "report")}
        self.steps.append({"type": "action", "tool": tool, "args": list(kwargs.keys())})
        self.steps.append({"type": "observation", "tool": tool, "brief": brief, "error": result.get("error", "")})
        return result

    def _make_plan(self, notes: dict[str, Any]) -> list[str]:
        has_dates = "未标注日期" not in notes["days"]
        plan = ["切分记录", "抽取可核查事实"]
        if not has_dates:
            plan.append("补齐缺失日期")
        plan += ["召回组员与术语记忆", "按七节骨架归并", "结构化自检", "渲染 md/docx"]
        return plan

    # ------------------------------------------------------------ 生成
    def _compose(
        self,
        notes: dict[str, Any],
        facts: dict[str, Any],
        hits: dict[str, Any],
        title: str,
        week: str,
        owner: str,
    ) -> dict[str, Any]:
        items = facts["facts"]
        groups: dict[str, list[dict[str, Any]]] = {}
        for f in items:
            groups.setdefault(f["category"], []).append(f)

        # 第 5 轮修正：按天配额取代表事项，保证关键进展覆盖整周而不是只截取前几条
        progress: list[dict[str, Any]] = []
        per_day: dict[str, int] = {}
        for f in items:
            if f["category"] == "事务":
                continue
            if per_day.get(f["day"], 0) >= 2:
                continue
            progress.append(
                {
                    "item": CATEGORY_LABELS.get(f["category"], f["category"]),
                    "detail": f["text"],
                    "evidence": "原始记录数字：" + "、".join(f["numbers"]) if f["numbers"] else f"来自{f['day']}记录",
                    "status": self._status(f["text"]),
                }
            )
            per_day[f["day"]] = per_day.get(f["day"], 0) + 1
            if len(progress) >= 12:
                break

        issues = []
        used: set[str] = set()
        for f in [x for x in items if x["is_issue"]][:6]:
            checked = self._find(
                items,
                # 第 3 轮修正："问" 会误命中 "课程问答助手"，改为精确动词
                ("查了", "排查", "问了", "助教", "修复", "字段名写错", "看过"),
                exclude=f["text"],
                day=f["day"],
                used=used,
            )
            nxt = self._find(
                items, ("待办", "下一步", "重跑", "清洗", "补", "需要", "准备"), exclude=f["text"], day=f["day"], used=used
            )
            # 第 6 轮修正：去掉素材自带的“卡点/待办/下周计划”前缀，避免“下一步：下周计划”这类标签叠加
            issues.append(
                {
                    "phenomenon": self._clean_label(f["text"]),
                    "checked": self._clean_label(checked),
                    "next": self._clean_label(nxt),
                }
            )
            used.update({f["text"], checked, nxt})

        # 第 5 轮修正：只有带单位或比值含义的数值才算指标，"17 个节点""3 个指标建议"不进指标表
        metrics = []
        for f in [x for x in items if x["numbers"]]:
            text = f["text"]
            if any(w in text for w in ("建议", "节点", "作业")):
                continue
            if not any(w in text for w in ("F1", "小时", "页", "人", "%", "分")):
                continue
            metrics.append({"name": self._metric_name(f), "value": "、".join(f["numbers"]), "scope": text})

        plan_rows = []
        for f in items:
            if f["category"] == "事务":
                continue
            # 第 2 轮修正：已发生的汇报不进下周日计划
            if "组会汇报" in f["text"] or "被指出" in f["text"]:
                continue
            if not any(w in f["text"] for w in PLAN_WORDS) and "下周" not in f["text"]:
                continue
            due_match = DUE_RE.search(f["text"])
            plan_rows.append(
                {
                    "task": f["text"],
                    "priority": self._priority(f["text"]),
                    "due": due_match.group(1) if due_match else "未定",
                    "dependency": self._dependency(f["text"]),
                }
            )
        plan_rows = plan_rows[:8]

        risks = [f["text"] for f in items if any(w in f["text"] for w in RISK_WORDS)][:5]
        # 第 4 轮修正：风险为空时也要给出明确结论，避免自检报“缺少章节”
        if not risks:
            risks = ["本周记录中未发现明确风险事项；如与实际情况不符，请补充素材"]
        gaps = self._detect_gaps(notes, items, hits, plan_rows)

        overview = (
            f"本周记录覆盖 {len([d for d in notes['days'] if d != '未标注日期'])} 个时间分组、{len(items)} 条事项，"
            f"主要投入在{'、'.join(CATEGORY_LABELS.get(k, k) for k in list(groups)[:3])}几条线。"
            f"可核查的量化记录 {len(metrics)} 条，其中受阻或异常 {len(issues)} 条。"
            f"下周计划 {len(plan_rows)} 项，P0 任务 {sum(1 for r in plan_rows if r['priority'] == 'P0')} 项。"
        )

        return {
            "title": title,
            # 第 6 轮修正：未提供的字段不写进页眉，避免“待填”式占位符
            "meta": " · ".join(x for x in (week, f"汇报人：{owner}" if owner else "") if x),
            "overview": overview,
            "progress": progress,
            "issues": issues,
            "metrics": metrics,
            "plan": plan_rows,
            "risks": risks,
            "gaps": gaps,
            "footer": "由课程周报智能体生成，事实以原始记录为准；数字未做换算",
        }

    # ------------------------------------------------------------ 局部工具
    @staticmethod
    def _status(text: str) -> str:
        # 第 5 轮修正：计划类条目不能因为含“完成”字样被判为已完成
        if any(w in text for w in ("下周", "待办", "计划", "准备")):
            return "未开始"
        if any(w in text for w in ("没做完", "未完成", "卡", "报错", "失败", "不够")):
            return "受阻"
        if any(w in text for w in ("完成", "跑通", "读完", "通过")):
            return "完成"
        return "进行中"

    @staticmethod
    def _clean_label(text: str) -> str:
        """去掉素材行首的自带标签，避免与周报字段名重复。"""
        return re.sub(r"^(卡点|待办|下周计划|没做完的|其他杂事)\s*[:：]\s*", "", text.strip())

    @staticmethod
    def _find(
        items: list[dict[str, Any]],
        words: tuple[str, ...],
        exclude: str = "",
        day: str = "",
        used: set[str] | None = None,
    ) -> str:
        """第 2 轮修正：同一句不得复用于多条卡点，且优先取同一天的句子。"""
        used = used or set()
        candidates = [f for f in items if f["text"] not in used and f["text"] != exclude]
        ordered = [f for f in candidates if day and f["day"] == day] + [f for f in candidates if not (day and f["day"] == day)]
        for f in ordered:
            if any(w in f["text"] for w in words):
                return f["text"]
        # 第 6 轮修正：措辞明确为“素材未写明”，并在第七节统一提请人工确认
        return "素材未写明，需人工确认"

    @staticmethod
    def _metric_name(fact: dict[str, Any]) -> str:
        text = fact["text"]
        if "F1" in text:
            return "F1 分数"
        if "小时" in text:
            return "投入时长"
        if "页" in text:
            return "笔记页数"
        if "人" in text:
            return "参与人数"
        return f"{CATEGORY_LABELS.get(fact['category'], fact['category'])}相关数值"

    @staticmethod
    def _priority(text: str) -> str:
        if any(w in text for w in ("demo", "周一", "截止", "提交")):
            return "P0"
        if any(w in text for w in ("想", "学一下", "看看", "有空")):
            return "P2"
        return "P1"

    @staticmethod
    def _dependency(text: str) -> str:
        if "检索" in text:
            return "关键词检索跑通"
        if "指标" in text:
            return "指标口径统一"
        if "demo" in text:
            return "前序任务完成"
        return "未标注"

    def _detect_gaps(
        self,
        notes: dict[str, Any],
        items: list[dict[str, Any]],
        hits: dict[str, Any],
        plan_rows: list[dict[str, Any]],
    ) -> list[str]:
        gaps: list[str] = []
        if "未标注日期" in notes["days"]:
            gaps.append("部分记录未标注日期，无法判断事项发生在哪一天")

        # 同一数字出现在不同类别：归属无法确定
        numbers: dict[str, set[str]] = {}
        for f in items:
            for n in f["numbers"]:
                numbers.setdefault(n, set()).add(f["category"])
        for n, cats in numbers.items():
            real = {c for c in cats if c != "其他"}
            if len(real) > 1:
                gaps.append(f"数字 {n} 同时出现在{'、'.join(sorted(real))}记录中，归属需人工确认，未强行合并")

        undated = [r["task"] for r in plan_rows if r["due"] == "未定"]
        if undated:
            gaps.append(f"下周计划中 {len(undated)} 项无明确截止时间，建议补充日期")

        private = [f["text"] for f in items if f["category"] == "事务"]
        if private:
            gaps.append("与项目无关的个人事务未纳入正文：" + "；".join(private[:3]))

        if not hits.get("hits"):
            gaps.append("长期记忆未命中组员与术语，分工信息需人工确认")
        return gaps

    # ------------------------------------------------------------ 修补
    def _repair(self, sections: dict[str, Any], facts: dict[str, Any], problems: list[dict[str, str]]) -> None:
        for p in problems:
            if p["type"] == "missing_section":
                key = p["detail"].split(": ")[-1]
                sections[key] = ["待补充：该节未从记录中抽取到内容，请人工复核"]
            elif p["type"] == "number_lost":
                num = p["detail"].split(": ")[-1]
                hit = next((f for f in facts["facts"] if num in f["numbers"]), None)
                if hit:
                    sections.setdefault("metrics", []).append(
                        {"name": "补充数值", "value": num, "scope": hit["text"]}
                    )
            elif p["type"] == "empty_gaps":
                sections["gaps"] = ["自动校验未发现缺失项，请人工复核日期、责任人与数字归属"]