"""课程周报智能体 · 渲染层

同一份 sections 数据渲染两种产物：Markdown（贴群、快速修改）与 docx（提交）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt

HEADERS = {
    "progress": ("事项", "具体进展", "可核查证据", "状态"),
    "metrics": ("指标", "数值", "口径说明"),
    "plan": ("任务", "优先级", "截止时间", "依赖"),
}
ROW_KEYS = {
    "progress": ("item", "detail", "evidence", "status"),
    "metrics": ("name", "value", "scope"),
    "plan": ("task", "priority", "due", "dependency"),
}


def _md_table(headers: tuple[str, ...], rows: list[dict[str, Any]], keys: tuple[str, ...]) -> str:
    def cell(v: Any) -> str:
        return str(v).replace("|", "\\|").replace("\n", " ")

    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for row in rows:
        lines.append("| " + " | ".join(cell(row.get(k, "")) for k in keys) + " |")
    return "\n".join(lines)


def render_markdown(sections: dict[str, Any]) -> str:
    title = sections.get("title", "课程周报")
    meta = sections.get("meta", "")
    parts = [f"# {title}", ""]
    if meta:
        parts += [meta, ""]

    parts += ["## 一、本周概览", "", sections.get("overview", ""), ""]
    parts += [
        "## 二、关键进展",
        "",
        "以下按记录的时间顺序列出本周主要进展，证据列只写素材中可核查的出处。",
        "",
        _md_table(HEADERS["progress"], sections.get("progress", []), ROW_KEYS["progress"]),
        "",
    ]

    parts += ["## 三、问题与卡点", ""]
    for item in sections.get("issues", []):
        parts.append(f"- **现象**：{item.get('phenomenon', '')}")
        parts.append(f"  - 已排查：{item.get('checked', '')}")
        parts.append(f"  - 下一步：{item.get('next', '')}")
    parts.append("")

    parts += [
        "## 四、量化指标",
        "",
        "下表只列带单位或比值的可核查数值，未采集的指标不列入。",
        "",
        _md_table(HEADERS["metrics"], sections.get("metrics", []), ROW_KEYS["metrics"]),
        "",
    ]
    parts += [
        "## 五、下周计划",
        "",
        "下周任务按下表推进，优先级、截止时间与依赖一并列出。",
        "",
        _md_table(HEADERS["plan"], sections.get("plan", []), ROW_KEYS["plan"]),
        "",
    ]

    parts += ["## 六、风险与需要协调的事项", ""]
    parts += [f"- {r}" for r in sections.get("risks", [])] or ["- 无"]
    parts.append("")

    parts += ["## 七、待补充信息", ""]
    parts += [f"- {g}" for g in sections.get("gaps", [])] or ["- 无"]
    parts.append("")
    return "\n".join(parts)


def _set_cn_font(run, name: str = "宋体", size: int = 10, bold: bool = False) -> None:
    run.font.name = name
    run.font.size = Pt(size)
    run.bold = bold
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def _add_table(doc: Document, headers: tuple[str, ...], rows: list[dict[str, Any]], keys: tuple[str, ...]) -> None:
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = ""
        _set_cn_font(cell.paragraphs[0].add_run(h), name="微软雅黑", size=9, bold=True)
    for row in rows:
        cells = table.add_row().cells
        for i, k in enumerate(keys):
            cells[i].text = ""
            _set_cn_font(cells[i].paragraphs[0].add_run(str(row.get(k, ""))), size=9)


def render_docx(sections: dict[str, Any], out_path: Path, title: str = "课程周报") -> Path:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "宋体"
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_cn_font(p.add_run(title), name="微软雅黑", size=18, bold=True)

    meta = sections.get("meta", "")
    if meta:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set_cn_font(p.add_run(meta), size=9)

    def heading(text: str) -> None:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(10)
        _set_cn_font(p.add_run(text), name="微软雅黑", size=12, bold=True)

    heading("一、本周概览")
    doc.add_paragraph(sections.get("overview", ""))

    heading("二、关键进展")
    doc.add_paragraph("以下按记录的时间顺序列出本周主要进展，证据列只写素材中可核查的出处。")
    _add_table(doc, HEADERS["progress"], sections.get("progress", []), ROW_KEYS["progress"])

    heading("三、问题与卡点")
    for item in sections.get("issues", []):
        doc.add_paragraph(f"现象：{item.get('phenomenon', '')}", style="List Bullet")
        doc.add_paragraph(f"已排查：{item.get('checked', '')}", style="List Bullet 2")
        doc.add_paragraph(f"下一步：{item.get('next', '')}", style="List Bullet 2")

    heading("四、量化指标")
    doc.add_paragraph("下表只列带单位或比值的可核查数值，未采集的指标不列入。")
    _add_table(doc, HEADERS["metrics"], sections.get("metrics", []), ROW_KEYS["metrics"])

    heading("五、下周计划")
    doc.add_paragraph("下周任务按下表推进，优先级、截止时间与依赖一并列出。")
    _add_table(doc, HEADERS["plan"], sections.get("plan", []), ROW_KEYS["plan"])

    heading("六、风险与需要协调的事项")
    for r in sections.get("risks", []) or ["无"]:
        doc.add_paragraph(r, style="List Bullet")

    heading("七、待补充信息")
    for g in sections.get("gaps", []) or ["无"]:
        doc.add_paragraph(g, style="List Bullet")

    footer = doc.add_paragraph()
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _set_cn_font(footer.add_run(sections.get("footer", "由课程周报智能体生成，事实以原始记录为准")), size=8)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return out_path