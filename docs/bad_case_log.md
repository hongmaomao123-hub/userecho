# Bad Case 日志

Claude Code 后续只负责审查和提出发现，不直接修改日志；由 Codex 按已确认的产品决策更新问题及验证结果。

| # | 日期 | 输入 | 期望 | 实际 | 根因 | 修复方式 | 修复后是否复现 |
|---|---|---|---|---|---|---|---|
| 1 | 2026-09-22 | 251 条合法反馈的 CSV（feedback_id 1–251，文本均非空） | 全量清洗后仅返回前 200 条；中文警告说明有效总数、实际处理数、未处理数与原始排序影响；有效样本量与返回数据一致 | 修复前全部 251 条被保留并计入 valid_sample_size，无截断、无提示；原测试断言不截断 | 此前全量处理决定与本次确认的 200 条上限不一致，需同步修正实现和测试 | 全量清洗后截取前 200 条；valid_sample_size 及文本、评分统计基于最终返回数据；补充完整中文警告及页面验证 | 未复现：`test_valid_dataset_limit_and_warning`（200/201/251 条）、`test_limit_applies_after_full_cleaning_and_before_statistics`、`test_uploaded_csv_results_and_preview` 全部通过；201/251 条返回 200 条，中文警告与页面样本量正确 |
| 2 | 2026-09-22 | 任意合法 CSV，以及 PRD 第 5 节与实现的字段对照 | PRD 与实现遵循项目负责人批准的统一字段契约 | PRD 旧字段与实现新字段发生契约漂移 | 文档与实现的字段及枚举定义未保持同步 | 经项目负责人于 2026-09-22 明确确认，正式保留 `raw_sample_size`、`valid_sample_size`、`analysis_mode`（blocked / summary_only / exploratory / standard）；已同步 PRD 和决策日志，更新后的 PRD 为唯一有效版本 | 未复现：`test_report_uses_new_contract_only`、`test_analysis_modes`、`test_uploaded_csv_results_and_preview` 验证通过；PRD 全文旧字段、旧模式枚举及旧编码检查通过 |
