# Bad Case 日志

Claude Code 后续只负责审查和提出发现，不直接修改日志；由 Codex 按已确认的产品决策更新问题及验证结果。

| # | 日期 | 输入 | 期望 | 实际 | 根因 | 修复方式 | 修复后是否复现 |
|---|---|---|---|---|---|---|---|
| 1 | 2026-09-22 | 251 条合法反馈的 CSV（feedback_id 1–251，文本均非空） | 全量清洗后仅返回前 200 条；中文警告说明有效总数、实际处理数、未处理数与原始排序影响；有效样本量与返回数据一致 | 修复前全部 251 条被保留并计入 valid_sample_size，无截断、无提示；原测试断言不截断 | 此前全量处理决定与本次确认的 200 条上限不一致，需同步修正实现和测试 | 全量清洗后截取前 200 条；valid_sample_size 及文本、评分统计基于最终返回数据；补充完整中文警告及页面验证 | 未复现：`test_valid_dataset_limit_and_warning`（200/201/251 条）、`test_limit_applies_after_full_cleaning_and_before_statistics`、`test_uploaded_csv_results_and_preview` 全部通过；201/251 条返回 200 条，中文警告与页面样本量正确 |
| 2 | 2026-09-22 | 任意合法 CSV，以及 PRD 第 5 节与实现的字段对照 | PRD 与实现遵循项目负责人批准的统一字段契约 | PRD 旧字段与实现新字段发生契约漂移 | 文档与实现的字段及枚举定义未保持同步 | 经项目负责人于 2026-09-22 明确确认，正式保留 `raw_sample_size`、`valid_sample_size`、`analysis_mode`（blocked / summary_only / exploratory / standard）；已同步 PRD 和决策日志，更新后的 PRD 为唯一有效版本 | 未复现：`test_report_uses_new_contract_only`、`test_analysis_modes`、`test_uploaded_csv_results_and_preview` 验证通过；PRD 全文旧字段、旧模式枚举及旧编码检查通过 |
| 3 | 2026-09-22 | 第二阶段主题表与标注规范任务明确要求暂时不要 git commit，仍需人工验收 | 完成修改和测试后保持未提交状态，等待项目负责人当前任务中的明确授权 | 项目负责人反馈发生“未经人工验收即 commit 并 push”的流程偏差 | 人工验收、任务完成与提交发布授权之间的边界未被有效执行 | 在 AGENTS 增加明确硬规则：未获当前任务明确要求，不得 commit、push、创建标签、修改远程仓库或部署；测试通过不代表发布获批 | 本次验收修复未执行提交、推送、标签、远程修改或部署；规则已补充，后续执行仍需持续遵守，不能仅以 pytest 证明流程问题永久消除 |
| 4 | 2026-09-25 | SYN-BR1-08（首次 10 条冒烟；实际输出由项目负责人提供） | 仅 longevity_diffusion / negative / 2；repurchase_signal=none | 模型额外生成 scent_preference / negative / 2 | 根因候选：模型过度推断；annotation guide 规则未完整传递到运行时 Prompt。尚未通过对照实验确认 | 暂不修改 Prompt，等待完整开发集基线结果；负责人裁决已记录于 decision_log | 未修复、未重跑该条；不得记为修复验证通过 |
| 5 | 2026-09-25 | SYN-BR2-08：试香纸与衣物上的气味差异，无官方宣传对照 | 按已确认边界，不应标 scent_mismatch；该条完整人工裁决及 severity 尚缺 | 本轮输出 scent_preference / negative / 2 和 scent_mismatch / negative / 2；repurchase_signal=none | 候选：将载体气味差异过度解释为宣传不符；当前 Prompt 已包含官方宣传对照要求，不能仅归因为规则未传递 | 本轮仅保留基线结果，不修改 Prompt；等待完整人工裁决及开发集结果 | 本轮基线观察到；未实施修复，尚无修复后验证 |

## 2026-09-25：Bad Case #4 / #5 受控修订验证

上表保留修订前的观察与候选根因。本轮负责人已授权修改 Prompt，并明确 SYN-BR2-08 预期为仅 scent_preference / negative / 1。新增不确定备选原因约束、官方宣传对照条件与中性安全咨询例外；根因仍为候选解释，单次前后结果不能独立确定因果。

| 原问题 | 本次验证结果 | 限制 |
|---|---|---|
| #4 SYN-BR1-08 多余 scent_preference | 本次未复现；仅 longevity_diffusion / negative / 2，repurchase_signal=none | 仅一次合成开发样本运行，非永久消除证明 |
| #5 SYN-BR2-08 多余 scent_mismatch，偏好 severity=2 | 本次未复现；仅 scent_preference / negative / 1，repurchase_signal=none，符合本轮负责人预期 | Round 2 其余 9 条预测不变；仅 04、05 有此前完整裁决 |
| 安全咨询回归检查 | SYN-BR1-10、SYN-BR2-04 均保持 safety_discomfort / neutral / null，none | 未扩展风险规则 |
| severity 待确认观察 | SYN-BR1-04 本次为 longevity_diffusion / mixed / 2，与教学讨论值 1 不同 | 无逐条旧输出，不认定为已证实回归；等待负责人裁决，不继续调 Prompt |

具体预测、token、耗时和可比较子集指标见 experiment_log；完整 pytest 为 135 passed，其中本轮新增 3 项 Prompt 规则测试。

## 2026-09-27：Bad Case #6 真实开发集短文本情绪偏差

- 来源：项目负责人本轮提供的真实开发集回归观察，本轮未重新调用 API。
- 输入：data/dev/real_dev_20260927.csv 中 R003_P1，文本“不错”。
- 实际：other / positive。
- 期望：按本轮负责人确认的当前信息不足规则，other / neutral。
- 影响：主题标签 other 一致，偏差发生在 sentiment，不影响主题标签。
- 根因：尚未验证；不将本次记录扩展为其他短文本的规则变更。
- 处理：本轮只记录，不修改 Prompt、taxonomy、schema 或业务逻辑。
- 修复后是否复现：尚未修复，未进行修复后验证。

## 2026-09-29：参考标签一致性检查差异（#7–#9）

本节只记录 feedback_id 与主题差异，不包含反馈原文；gold 指经 AI 辅助生成、审核及项目负责人边界裁决的参考标签。

| # | feedback_id | gold_topics | predicted_topics | 类型 |
|---|---|---|---|---|
| 7 | R004_P1 | longevity_diffusion、price_value、scent_preference | longevity_diffusion、scent_mismatch、scent_preference | 邻近主题混淆及遗漏 |
| 8 | R008_P1 | other | scent_preference | 信息不足反馈被过度具体分类 |
| 9 | R023_P1 | longevity_diffusion | longevity_diffusion、safety_discomfort | 额外安全主题及潜在风险误报候选 |

评测完成后不再根据这些案例调整 Prompt；Bad Case 仅作为系统限制和后续优化方向。上述类型描述预测与参考标签的差异，不作已验证的根因判断；潜在风险误报候选不等于已完成安全事实核实。本轮不修复、不重跑、不修改分类或分析规则。
