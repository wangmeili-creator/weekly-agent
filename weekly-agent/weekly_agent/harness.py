"""课程周报智能体 · harness

负责工具注册、参数校验、执行、观察回填与轨迹日志。
模型（这里是规则引擎或外部 LLM）只产生“调用请求”，真正执行动作的是本模块。
"""

from __future__ import annotations

import time
from typing import Any, Callable

from . import tools


class Harness:
    def __init__(self) -> None:
        self.registry: dict[str, Callable[..., dict[str, Any]]] = {
            "read_notes": tools.read_notes,
            "extract_facts": tools.extract_facts,
            "retrieve_memory": tools.retrieve_memory,
            "render_report": tools.render_report,
            "check_report": tools.check_report,
        }
        self.schemas = {s["name"]: s for s in tools.TOOL_SCHEMAS}
        self.trace: list[dict[str, Any]] = []

    def call(self, name: str, **kwargs: Any) -> dict[str, Any]:
        if name not in self.registry:
            raise KeyError(f"未注册的工具: {name}")
        start = time.time()
        try:
            result = self.registry[name](**kwargs)
            ok = True
            error = ""
        except Exception as exc:  # 工具异常转为观察，循环不中断
            result = {"error": f"{type(exc).__name__}: {exc}"}
            ok = False
            error = str(exc)
        self.trace.append(
            {
                "tool": name,
                "args": {k: (f"<{type(v).__name__} len={len(v)}>" if isinstance(v, (list, dict)) else v) for k, v in kwargs.items()},
                "ok": ok,
                "ms": round((time.time() - start) * 1000, 1),
                "error": error,
            }
        )
        return result

    def dump_trace(self) -> list[dict[str, Any]]:
        return self.trace