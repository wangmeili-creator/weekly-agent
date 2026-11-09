"""端到端测试：只依赖标准库 unittest。

运行：python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from weekly_agent.agent import WeeklyAgent
from weekly_agent.harness import Harness
from weekly_agent.memory import MemoryStore
from weekly_agent.tools import check_report, extract_facts, read_notes


SAMPLE = """周一
- 上午第4课，讲智能体原理，记了 ReAct 循环
- 下午改前端页面
周二
- 小组项目讨论，我负责检索部分
- 卡点：不知道评估怎么做
周三
- 实验课跑 baseline，报 KeyError: 'content'，查了一个多小时
- 跑通之后 F1 只有 0.41
下周
- 准备周一 demo，要留一天联调
"""


class ToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.notes_path = Path(self.tmp.name) / "notes.txt"
        self.notes_path.write_text(SAMPLE, encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_read_notes_splits_by_day(self) -> None:
        res = read_notes(self.notes_path)
        # 第 2 轮修正：原断言把 "下周" 误当日期标题；"下周" 是条目，不是 day header
        self.assertEqual(res["days"], ["周一", "周二", "周三"])
        self.assertEqual(res["segment_count"], 7)

    def test_extract_facts_keeps_numbers_verbatim(self) -> None:
        notes = read_notes(self.notes_path)
        facts = extract_facts(notes["segments"])
        numbers = {n for f in facts["facts"] for n in f["numbers"]}
        self.assertIn("0.41", numbers)
        # 第 3 轮修正："第4课" 属序数、"F1" 属指标名，都不应作为量化数值
        self.assertNotIn("4", numbers)
        self.assertNotIn("F1", numbers)

    def test_check_report_flags_missing_section(self) -> None:
        report = {"overview": "x", "progress": [], "issues": [], "metrics": [], "plan": [], "risks": []}
        res = check_report(report, facts=[])
        self.assertFalse(res["ok"])
        keys = [p["detail"] for p in res["problems"]]
        self.assertTrue(any("gaps" in k for k in keys))

    def test_agent_end_to_end(self) -> None:
        out = Path(self.tmp.name) / "out"
        agent = WeeklyAgent(Harness(), MemoryStore(Path(self.tmp.name) / "memory.json"))
        result = agent.run(str(self.notes_path), str(out), fmt=("md", "docx"), week="第1周", owner="测试")
        self.assertTrue(result["check"]["ok"], result["check"])
        self.assertTrue((out / "weekly_report.md").exists())
        self.assertTrue((out / "weekly_report.docx").exists())
        md = (out / "weekly_report.md").read_text(encoding="utf-8")
        self.assertIn("0.41", md)
        self.assertIn("待补充信息", md)


if __name__ == "__main__":
    unittest.main()