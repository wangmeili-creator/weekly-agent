# weekly-agent · 课程周报智能体

把一周散乱的学习记录整理成结构固定、事实可追溯、缺口显式标注的周报，输出 Markdown 与 docx 两份同源产物。

## 快速开始

```bash
# 1. 安装依赖（仅 docx 渲染需要）
pip install python-docx

# 2. 运行
python weekly_agent/main.py --input sample_notes.txt --out out \
  --format md,docx --week "第11周（11.03-11.09）" --owner "张三"

# 3. 查看产物
# out/weekly_report.md     Markdown 周报
# out/weekly_report.docx   Word 周报
# out/trace.json           规划、ReAct 步骤与工具调用轨迹

# 4. 跑测试
python -m unittest discover -s tests -v
```

## 目录结构

```
weekly-agent/
├── weekly_agent/
│   ├── main.py      CLI 入口
│   ├── agent.py     任务规划 + ReAct 循环 + 七节生成 + 自检修补
│   ├── harness.py   工具注册、执行、观察回填、轨迹日志
│   ├── tools.py     5 个工具与 JSON Schema
│   ├── memory.py    三层记忆（短期/长期/反思）
│   └── render.py    Markdown 与 docx 渲染
├── tests/test_agent.py   4 个端到端与单元测试
├── sample_notes.txt      样例输入
├── memory.json           样例长期记忆
└── out/                  运行产物
```

## 设计对应关系

| 设计方案中的能力 | 代码位置 |
|---|---|
| ReAct：思考—行动—观察 | `agent.py::WeeklyAgent.run` 中的 `_think` / `_act` |
| 工具调用与分发 | `harness.py::Harness.call`，schema 见 `tools.TOOL_SCHEMAS` |
| 记忆分层与召回 | `memory.py::MemoryStore`，`tools.retrieve_memory` |
| 规划与动态回退 | `_make_plan`、`check_report` 失败后的 `_repair` |
| 输出格式固定七节 | `render.py`，`check_report` 中 `REQUIRED_SECTIONS` |
| 效果评估 | `tests/test_agent.py` + 自检结果 `check.ok` |

## 已知局限

1. 规则引擎基于关键词，分类粒度有限；“其他事项”类条目仍可能混入正文。
2. `check_report` 的数字保真校验用子串匹配，“1”这类短数字可能被其他数字包含而漏报，后续应改为 token 级比对。
3. 卡点的“已排查 / 下一步”靠同天优先匹配，素材本身没写时会显示“待补充”，不会编造。
4. 未接入真实 LLM 时，文字表达偏模板化；`agent._compose` 预留了替换点。