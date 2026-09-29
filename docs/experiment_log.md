# 分类实验日志

## 2026-09-25：首次 10 条冒烟历史记录

数据来源：项目负责人在本轮提供的历史指标，并非本轮重新执行；历史模型版本、Prompt 指纹和逐条原始预测未提供，无法独立复核其余 9 条匹配结果。sample_size 是实验样本数，不变更 data_check 字段契约。

| 指标 | 值 |
|---|---|
| sample_size | 10 |
| schema_valid | 10 |
| feedback_exact_match | 9 |
| call_count | 1 |
| prompt_tokens | 2885 |
| completion_tokens | 745 |
| total_tokens | 3630 |
| elapsed_seconds | 约 2.9 |

SYN-BR1-08 的负责人裁决及额外偏好主题问题见 decision_log 和 Bad Case #4。此记录只描述合成开发样本，不支持对真实数据效果的推广。

## 2026-09-25：Round 2 合成边界案例校准基线

输入：data/dev/synthetic_calibration_round2.csv（路径于 2026-09-27 同步为合成校准命名；用途为 synthetic calibration/dev）。使用现有 classify 和当前 Prompt，未改动 Prompt、配置或代码；case_id 仅在内存中映射为 feedback_id。完整 Prompt 日志关闭。模型为 deepseek-chat，使用现有调用默认参数。

运行时间：2026-09-25T01:17:17.926757+08:00。

系统 Prompt SHA-256：`c34b6976fd76cd2267953c88dec1f2d829d371a3f34d1bf1490b204df80795cf`（运行前后相同）。

输入 SHA-256：`95335f5728dab92f87d68b1dc3ac727fa8330387caabcd1945296243173efacb`。

| 指标 | 值 |
|---|---|
| sample_size | 10 |
| schema_valid | 10 |
| call_count | 1 |
| prompt_tokens | 2900 |
| completion_tokens | 715 |
| total_tokens | 3615 |
| elapsed_seconds（完整流程） | 2.719 |
| elapsed_seconds（API 调用及校验） | 2.681 |
| 人工复核 / 未处理 | 0 / 0 |
| 有负责人完整裁决的条目 | 2（04、05） |
| 已裁决条目的 exact match | 2 / 2 |
| 全集 feedback_exact_match | 不计算：其余 8 条缺少人工裁决 |

结构校验通过不等于语义正确。按 topic code 对齐后比较 sentiment、severity 及整条 repurchase_signal，不按主题位置匹配。以下待确认项是基线检查观察，不是补写的人工答案。

| case_id | 模型预测：code / sentiment / severity | repurchase_signal | 与人工裁决差异或检查状态 |
|---|---|---|---|
| SYN-BR2-01 | other / neutral / null | none | 待人工裁决；短文本预测为 other。 |
| SYN-BR2-02 | scent_preference / positive / null | positive | 待人工裁决；明确再买的预测为 positive。 |
| SYN-BR2-03 | service / mixed / 2 | none | 待人工裁决；service mixed 的 severity=2 是否达到阻碍程度待确认。 |
| SYN-BR2-04 | safety_discomfort / neutral / null | none | 与负责人裁决完全一致；中性安全咨询为 neutral/null，按规则不触发风险。 |
| SYN-BR2-05 | appearance_usage / positive / null；packaging_leak / negative / 2 | none | 与负责人裁决完全一致；两个主题均保留，无增减。 |
| SYN-BR2-06 | longevity_diffusion / negative / 2 | conditional | 待人工裁决；预测识别条件复购，severity=2 待确认。 |
| SYN-BR2-07 | safety_discomfort / negative / 3 | none | 待人工裁决；灭掉蜡烛未被推断为不再购买，预测 none。 |
| SYN-BR2-08 | scent_preference / negative / 2；scent_mismatch / negative / 2 | none | 待人工裁决；额外 scent_mismatch 明确违反无官方对照的既有规则；scent_preference 属载体差异规则适用范围，不宜直接判为过度添加，但 negative/2 的依据尤其 1/2 分界需人工确认。 |
| SYN-BR2-09 | logistics / negative / 2 | negative | 待人工裁决；明确下回不买预测为 negative，物流 severity=2 待确认。 |
| SYN-BR2-10 | price_value / positive / null | none | 待人工裁决；价格正向无购买意图预测 none。 |

重点观察：04 安全咨询保持 neutral/null；07 停止使用没有被推断为 negative repurchase；05 保留两主题。08 增加无依据的 scent_mismatch，记录为 Bad Case #5。03、06、08、09 的 severity=2 缺少负责人最终裁决，尤其 08 是否只是轻微主观不悦需核对；本轮没有负向 severity=1 的输出，无法据此宣称 1/2 一致。其余未裁决条目无法最终判断漏标或增标。

逐条预测、调用元数据、输入指纹保存在 data/dev/baseline_round2_20260925.json。

## Round 3：源文件不存在，本轮未运行

现有 data/dev 没有第三轮源文件，历史记录也明确缺失且不重建。仅有 SYN-BR3-06 和 SYN-BR3-08 的裁决，不能据此反向编造反馈或运行预测。负责人已确认本轮只运行现有 Round 2，不推测、生成或重建缺失裁决；其余 8 条待人工裁决，不计算整体 exact-match、准确率或 F1。未读取 data/eval，未执行任何 Git 操作。

## 2026-09-25：受控 Prompt 修订 R1

本轮由项目负责人批准一次修订：不把猜测、疑问及每个备选原因直接变成主题；scent_mismatch 必须有官方或商家描述等明确对照，载体、环境、人与人感知差异不能代替该对照；儿童、孕妇、宠物中性安全咨询为疑问规则的明确例外，保持 safety_discomfort / neutral / null。未增加案例答案或 severity 特例，未修改 taxonomy、主题 code、风险规则或分类代码。

新增三个测试验证最终 system prompt 包含上述规则；这些文本检查不代替真实模型行为验证。两轮均用现有 classify 默认批大小和调用参数，模型 deepseek-chat，各运行一次，不挑选多次运行中的有利结果。完整 Prompt 日志关闭。

修订前系统 Prompt SHA-256：`c34b6976fd76cd2267953c88dec1f2d829d371a3f34d1bf1490b204df80795cf`；修订后：`42f61aee3a63399bc63c17e08347a3477d96b1700dc55594a7a648ff4609b85f`。运行时间：2026-09-25T01:24:29.579456+08:00。输入指纹及全部预测见 `data/dev/prompt_revision_20260925.json`。

| 指标 | Round 1 前 | Round 1 后 | Round 2 前 | Round 2 后 |
|---|---|---|---|---|
| 样本数 | 10 | 10 | 10 | 10 |
| schema 有效 | 10/10 | 10/10 | 10/10 | 10/10 |
| 全集 feedback exact match | 9/10（负责人提供历史指标） | 不计算：完整裁决缺失 | 不计算：完整裁决缺失 | 不计算：完整裁决缺失 |
| 可正式对照子集 exact match | BR1-08 不匹配（负责人报告） | BR1-08 匹配 | BR2-04/05/08：2/3 | 同子集：3/3 |
| 多余主题数（上述子集） | BR1-08：1（报告的偏好主题） | BR1-08：0 | 1 | 0 |
| 遗漏主题数（上述子集） | 无原始预测，不能独立核验 | BR1-08：0 | 0 | 0 |
| 调用次数 | 1 | 1 | 1 | 1 |
| prompt_tokens | 2885 | 2992 | 2900 | 3007 |
| completion_tokens | 745 | 715 | 715 | 422 |
| total_tokens | 3630 | 3707 | 3615 | 3429 |
| 总耗时（秒） | 约 2.9 | 2.643 | 2.719 | 2.290 |

前后子集用同一套本轮已确认参考核对，主题按 code 对齐后比较 sentiment/severity 和 repurchase_signal。Round 2 本轮新增确认 08 的单主题及 severity=1，复购 none 遵循明确意图规则；不能把子集 3/3 写成全部 10 条匹配。其他 7 条仍待人工裁决。Round 1 历史结果来源及逐条预测缺失限制保持不变，不能用教学讨论值冒充完整负责人裁决，全集多余/遗漏主题数亦不补算。

重点验证：BR1-08 为 longevity_diffusion / negative / 2、none；BR2-08 为 scent_preference / negative / 1、none；BR1-10 与 BR2-04 都为 safety_discomfort / neutral / null、none。本次均符合明确预期。

Round 2 只有 08 改变（删除 scent_mismatch，偏好 severity 2→1），其余 9 条各字段不变；04、05 已确认正确的案例未发生回归。其余未裁决样本保持不变不代表已经正确。Round 1 缺少逐条旧预测，不能保证其余案例无回归；04 的 mixed severity 本次为 2，与 annotation guide 教学讨论值 1 不同，待负责人裁决。02、05 的 severity 也仍待确认。此单次合成开发集观察不证明真实数据效果或严重度边界全面稳定。

### 修订后逐条预测

| case_id | code / sentiment / severity | repurchase_signal |
|---|---|---|
| SYN-BR1-01 | appearance_usage / positive / null | none |
| SYN-BR1-02 | scent_mismatch / negative / 2 | none |
| SYN-BR1-03 | logistics / positive / null；packaging_leak / negative / 2；service / positive / null | none |
| SYN-BR1-04 | longevity_diffusion / mixed / 2 | none |
| SYN-BR1-05 | price_value / negative / 2 | conditional |
| SYN-BR1-06 | safety_discomfort / negative / 3 | negative |
| SYN-BR1-07 | scent_preference / negative / 1 | none |
| SYN-BR1-08 | longevity_diffusion / negative / 2 | none |
| SYN-BR1-09 | other / neutral / null | none |
| SYN-BR1-10 | safety_discomfort / neutral / null | none |
| SYN-BR2-01 | other / neutral / null | none |
| SYN-BR2-02 | scent_preference / positive / null | positive |
| SYN-BR2-03 | service / mixed / 2 | none |
| SYN-BR2-04 | safety_discomfort / neutral / null | none |
| SYN-BR2-05 | appearance_usage / positive / null；packaging_leak / negative / 2 | none |
| SYN-BR2-06 | longevity_diffusion / negative / 2 | conditional |
| SYN-BR2-07 | safety_discomfort / negative / 3 | none |
| SYN-BR2-08 | scent_preference / negative / 1 | none |
| SYN-BR2-09 | logistics / negative / 2 | negative |
| SYN-BR2-10 | price_value / positive / null | none |

验证：完整 pytest -q 为 135 passed；新增 3 项 Prompt 回归测试。未读取 data/eval，未执行 git add、commit 或 push。

## 2026-09-25：temperature=0 五条边界案例连续三轮

分类请求此前未显式设置 temperature，本轮只增加 temperature=0；未新增其他采样参数、未修改业务 Prompt。BR1-04 最终裁决为 longevity_diffusion / mixed / 1、repurchase_signal=none，原因见 decision_log。五条参考均来自负责人裁决，复购均为 none。

使用同一 deepseek-chat 客户端及模型，五条按负责人给定顺序组成同一批，连续运行三轮；每轮完整 system prompt 指纹相同，反馈批次也相同。此处为合成开发案例稳定性检查，不称正式准确率或 F1。与此前十条一批的运行相比，批次上下文和 temperature 都发生变化，不能把结果变化单独归因于 temperature。

系统 Prompt SHA-256：`42f61aee3a63399bc63c17e08347a3477d96b1700dc55594a7a648ff4609b85f`。完整输入、参考、逐条预测、差异、每次调用 token 和耗时保存在 `data/dev/stability_temperature0_20260925.json`。

| run_id | 调用次数 | prompt_tokens | completion_tokens | total_tokens | 总耗时（秒） | 判定 |
|---|---|---|---|---|---|---|
| stability-t0-20260925-01 | 1 | 2809 | 371 | 3180 | 2.165 | 未通过：BR1-08 多余偏好主题 |
| stability-t0-20260925-02 | 1 | 2809 | 371 | 3180 | 1.704 | 未通过：BR1-08 多余偏好主题 |
| stability-t0-20260925-03 | 1 | 2809 | 371 | 3180 | 1.679 | 未通过：BR1-08 多余偏好主题 |

三轮逐条结果完全相同：

| case_id | 三轮实际预测：code / sentiment / severity | repurchase_signal | 与裁决对照 |
|---|---|---|---|
| SYN-BR1-04 | longevity_diffusion / mixed / 1 | none | 三轮均一致 |
| SYN-BR1-08 | longevity_diffusion / negative / 2；scent_preference / negative / 2 | none | 三轮均额外添加 scent_preference / negative / 2 |
| SYN-BR1-10 | safety_discomfort / neutral / null | none | 三轮均一致 |
| SYN-BR2-04 | safety_discomfort / neutral / null | none | 三轮均一致 |
| SYN-BR2-08 | scent_preference / negative / 1 | none | 三轮均一致 |

结论：未达到“五条案例连续三轮均与裁决一致”的通过标准。本次没有轮间波动，但存在重复出现的错误；temperature=0 不等于保证正确。三轮共调用 3 次、9540 tokens，均通过 schema 校验且无重试、无未处理项。BR1-08 的额外偏好主题再次出现，故此前一次未复现不代表问题消除；本轮只报告，不进一步调 Prompt。

离线验证：新增 test_temperature_zero_is_sent_for_every_batch_and_retry，Mock API 检查每批及重试均传 temperature=0、没有其他采样参数。完整 pytest -q：136 passed。未读取 data/eval，未执行 git add、commit 或 push。

## 2026-09-27：真实开发集端到端回归记录

来源：项目负责人本轮提供的已运行结果；本轮仅登记，不重新调用 API，不读取原始反馈或 eval 数据。

| 项目 | 记录值 |
|---|---|
| 数据 | data/dev/real_dev_20260927.csv |
| 样本量 | 11 |
| analysis goal | complaints |
| classifications | 11 |
| review_items | 0 |
| unprocessed | 0 |
| API calls | 1 |
| total_tokens | 4181 |
| elapsed_seconds | 4.42 |
| 风险警报 | 0 |

已知问题：R003_P1 的“不错”输出 other/positive，本轮负责人确认预期为 other/neutral；主题标签不受影响，详见 Bad Case #6。本轮只记录，不修改分类 Prompt、taxonomy、schema 或业务逻辑。

结论：小样本真实数据工作流回归通过。

## 2026-09-29：真实小样本参考标签一致性检查

类型：真实小样本参考标签一致性检查。项目负责人确认这是唯一一次正式参考标签一致性检查；本节仅登记既有结果，不重新执行评测或调用 API。

标签口径：AI辅助生成并审核，由项目负责人完成边界裁决；不是严格独立盲标。数值来源为 `outputs/reference_consistency_20260929.json` 与负责人提供的记录；Micro Precision = TP / (TP + FP)，Micro Recall = TP / (TP + FN)。

| 指标 | 值 |
|---|---|
| eval_sample_size | 13 |
| classifications | 13 |
| review_items | 0 |
| unprocessed | 0 |
| Topic micro-F1 | 0.9019607843 |
| Micro Precision | 0.8846153846 |
| Micro Recall | 0.92 |
| TP | 23 |
| FP | 3 |
| FN | 2 |
| system_high_risk_count | 1 |
| High-risk Recall | N/A：参考标签无高风险正样本，分母为 0 |
| Evidence Support Rate | N/A：结论级 evidence.py 未实现 |
| API calls | 3 |
| total_tokens | 5297 |
| elapsed_seconds | 12.8293 |

主题指标按 feedback_id 对齐，以主题无序集合累计；review_items 和 unprocessed 按空预测计入，不能排除失败条目。13 + 0 + 0 = 13，结果桶数量守恒。不计算 sentiment、severity 或 repurchase 的 F1。

系统识别的高风险数量按反馈粒度计数，不代替 High-risk Recall；没有参考高风险正样本时无法据此判断召回能力。现有 source_span 是进入最终分类前的硬校验，不等同于报告结论的 Evidence Support Rate。人工处理时间未记录，不做耗时优劣对照。

主题差异仅以 ID 和主题代码记入 Bad Case #7–#9。评测完成后不再根据这些案例调整 Prompt；只作为系统限制和后续优化方向。此次文档登记未读取任何评测 CSV，未变更标签、checksum 或结果文件。

固定限制：n=13，仅用于小样本工作流可行性及参考标签一致性检查，不代表生产环境表现。
