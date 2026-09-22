# UserEcho — 给 AI 编码助手的项目说明

Codex 读取本文件；Claude Code 通过 CLAUDE.md 引用本文件。分工：Codex 负责开发，Claude Code 只做审查、不直接修改代码。

## 项目
用户反馈洞察 Agent。完整需求见 `docs/PRD.md`，**以 PRD 为准**；遇到 PRD 没写清楚的地方，先停下来问，不要自己发挥。

## 硬规则
1. **一次只做一个步骤。**每次只实现当前任务要求的内容，不顺手加功能、不提前搭框架。
2. **开发步骤 1–7 期间，不许读取、打印、修改 `data/eval/` 下的任何文件。**到第 8 步时，只允许评测脚本读取这些文件；编码助手默认只看汇总指标，不许根据 eval 原文修改 prompt。
3. 统计、打分、证据筛选、校验一律用确定性 Python 代码实现；v1 只有 classify 和 suggest 两处调用 LLM。
4. LLM 输出必须是 JSON，并用 pydantic 校验；校验失败要显式处理，不能静默吞掉。
5. API key 只从 `.env` 读取；不许硬编码，不许提交到 git。
6. 每个工具函数都要有 pytest 测试（`tests/`），测试不许调用真实的 LLM（用 mock）。
7. 代码和注释用英文；面向用户的界面文字和报告用中文。
8. 完成后要说明：改了哪些文件、怎么运行、怎么测试、有哪些已知限制。
9. **不做 PRD 第 13 节「后续清单」里的任何功能**，除非用户明确要求。

## 目录约定
```
app.py                 Streamlit 入口
userecho/
  steps/               data_check.py, mask_pii.py, classify.py, analyze.py, evidence.py, suggest.py, report_check.py
  pipeline.py          工作流编排
  llm.py               LLM 客户端封装（OpenAI 兼容）
config/                taxonomy.yaml, impact.yaml
data/dev/              开发数据
data/eval/             评测集（步骤1–7禁止访问；步骤8仅允许评测脚本读取）
data/edge/             异常测试数据
data/raw/              未脱敏原始数据（已在 .gitignore 中，禁止提交）
tests/
docs/                  PRD, decision_log, bad_case_log
```

## 运行
```
source .venv/bin/activate
streamlit run app.py
pytest
```
