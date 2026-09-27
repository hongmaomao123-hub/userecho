# UserEcho

用户反馈洞察与行动 Agent。需求见 docs/PRD.md。

## 分类来源与已知限制

分类候选携带原文 `source_span` 与 `mention_type`，先精确校验、去重和过滤，再裁剪到三个主题。证据不匹配或全为不确定提及的反馈进入人工复核，不自动重试。默认日志不输出反馈原文或证据片段；仅显式设置 `USERECHO_DEBUG_PROMPT=1` 才输出完整请求 Prompt。

候选主题和 mention_type 仍由 LLM 产生；确定性后处理降低但不能彻底消除批次上下文影响。精确子串存在也不能保证语义归因正确。temperature=0 提高可复现性，但不保证结果正确。旧输出缺少来源字段时不再符合新 Schema，历史实验记录保留原样。

离线验证：在项目虚拟环境运行 `python -m pytest -q`。分类 API 测试使用 Mock，不调用外部服务。
