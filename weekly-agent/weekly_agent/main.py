"""CLI 入口。

用法：
    python weekly_agent/main.py --input sample_notes.txt --out out --format md,docx
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from weekly_agent.agent import WeeklyAgent
    from weekly_agent.harness import Harness
    from weekly_agent.memory import MemoryStore
else:
    from .agent import WeeklyAgent
    from .harness import Harness
    from .memory import MemoryStore


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="课程周报智能体")
    parser.add_argument("--input", required=True, help="原始周记录文件")
    parser.add_argument("--out", default="out", help="产物目录")
    parser.add_argument("--format", default="md,docx", help="输出格式，逗号分隔")
    parser.add_argument("--memory", default="memory.json", help="长期记忆文件")
    parser.add_argument("--max-rounds", type=int, default=6)
    parser.add_argument("--week", default="", help="周次，如 第11周（11.03-11.09）")
    parser.add_argument("--owner", default="", help="汇报人")
    parser.add_argument("--title", default="课程周报")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    fmt = tuple(x.strip() for x in args.format.split(",") if x.strip())
    agent = WeeklyAgent(Harness(), MemoryStore(args.memory), max_rounds=args.max_rounds)
    result = agent.run(
        input_path=args.input,
        out_dir=args.out,
        fmt=fmt,
        title=args.title,
        week=args.week,
        owner=args.owner,
    )

    md_path = next((p for p in result["paths"] if p.endswith(".md")), None)
    print("== 运行结果 ==")
    print(f"规划步骤：{' → '.join(result['plan'])}")
    print(f"循环轮次：{result['rounds']}；工具调用：{result['tool_calls']} 次；自检：{'通过' if result['check']['ok'] else '未通过'}")
    for p in result["paths"]:
        print(f"产物：{p}")
    print(f"轨迹：{result['trace']}")
    if md_path:
        print("\n== 周报预览 ==\n")
        print(Path(md_path).read_text(encoding="utf-8"))
    return 0 if result["check"]["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())