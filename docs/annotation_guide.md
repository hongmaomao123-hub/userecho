# UserEcho v1.3 主题与标注指南

## 适用范围

唯一有效需求是 `docs/PRD.md` v1.3。主题说明位于 `config/taxonomy.yaml`，本指南解释现有规则，不另立 PRD。尚未明确的边界列在末尾，需项目负责人确认后才能成为规则。本阶段不调用 LLM、不配置影响分、不实现分类或后续流程。

主题表以 PRD 的十个 code 为键；`name` 为中文名称，`definition` 为定义，`include` / `exclude` 为纳入与排除边界，`adjacent_topics` 为易混淆的相邻主题。排除项用于区分单一证据的归属，不禁止有独立证据的多标签反馈。

## 标注字段

一条反馈最多 3 个主题，同一主题只出现一次。每个主题分别标注 `sentiment` 和 `severity`，整条反馈只标注一个 `repurchase_signal`。不因整条反馈有正面或负面词，就把所有主题都标成相同情绪。

| sentiment | 使用条件 | severity |
|---|---|---|
| positive | 对该主题明确肯定或满意 | null |
| negative | 对该主题明确否定或不满 | 1、2 或 3 |
| neutral | 提及该主题但没有明确正负评价，或无足够评价信息 | null |
| mixed | 同一主题内部同时有明确正向和负向评价 | 1、2 或 3 |

`mixed` 不能用于表达语气复杂、犹豫或不同主题一好一坏。例如物流差而客服好，应分别标注物流 negative、客服 positive。PRD 的「前调好闻，后调刺鼻」说明同一主题可有正负两面，但「刺鼻」是否已经表达身体刺激，仍需结合上下文；无上下文的边界见待确认项。

| severity | PRD 定义 |
|---|---|
| null | sentiment 为 positive 或 neutral；不是 0，也不是字符串 "null" |
| 1 | 轻微不满 |
| 2 | 体验明显受损 |
| 3 | 无法使用，或涉及安全、健康、财产损失 |

negative 和 mixed 必须有 1–3 的严重度；不能因主题属于 other 就省略负向严重度。severity 根据文本中的影响程度标注，不用反馈数量、星级或优先级代替。一个主题有多个负向影响时如何选单一严重度，尚待确认。

| repurchase_signal | 使用条件 |
|---|---|
| positive | 明确表示会回购或推荐 |
| negative | 明确表示不会回购 |
| conditional | 明确有条件回购，如便宜点会回购 |
| none | 没有提及复购或推荐 |

复购信号与主题情绪独立：有不满仍可能有条件回购；正向评价也不自动意味着会回购。以下示例只依据示例文本标注。问卷 Q5 是否可以作为额外标注依据尚待确认。

## 重点主题边界

- `scent_mismatch` 与 `scent_preference`：前者需要实际气味与商品描述或宣传的明确对照；仅说不是自己喜欢的味道，不等于宣传不符。「与预期不同」而未说明预期来自何处，不能直接作为宣传不符的确定示例。
- `scent_preference` 与 `safety_discomfort`：仅表达个人不喜欢气味属于偏好；明确头晕、过敏、身体刺激或儿童/宠物安全顾虑属于安全。不要从个人厌恶推断生理伤害，也不要忽略明确的不适陈述。模糊的「刺鼻」「闻着难受」见待确认项。
- `longevity_diffusion`：过浓、过淡、留香和扩香效果按 PRD 归入此类；同时明确身体不适时可分别标注有证据的主题。
- `packaging_leak` 与 `logistics`：破损或漏液本身不能证明物流责任；明确提及配送慢等内容，才另有物流主题证据。
- `other`：去空格后少于 4 个字的反馈按 PRD 一律归入 other；其余无足够信息或不属于现有主题的内容也归入 other。other 不等于 neutral，例如「好」仍是 positive。空文本已由数据检查排除，不应作为一条反馈补标 other。

只标原文支持的体验，不作医疗诊断或因果确认。`risk_alert` 是后续确定性规则产生的独立风险标志，不是主题、sentiment、severity 或 P0–P3 的替代字段；本阶段不生成风险或优先级结果。

## 10 条 synthetic 教学示例

**以下每条均为人工编写的 synthetic 示例，仅解释标注规则，不是真实用户反馈，不计入真实评测集，也不得用于宣称模型效果。** 表内 `code / sentiment / severity` 是说明记法，不新增输出接口。

| ID | 来源 | 示例文本 | 主题标注（code / sentiment / severity） | repurchase_signal | 规则说明 |
|---|---|---|---|---|---|
| SYN-01 | synthetic | 这个木质香我很喜欢，下次还会买，也会推荐给朋友。 | scent_preference / positive / null | positive | 香味肯定与明确复购、推荐。 |
| SYN-02 | synthetic | 商品写的是柑橘香，实际闻起来却是玫瑰香，略有失望。 | scent_mismatch / negative / 1 | none | 明确商品描述对照；轻微不满。 |
| SYN-03 | synthetic | 点燃后香味很快就散了，整个使用体验明显受影响，我不会再买。 | longevity_diffusion / negative / 2 | negative | 留香影响体验；明确不回购。 |
| SYN-04 | synthetic | 收到时瓶身已经破裂，液体漏光了，完全无法使用。 | packaging_leak / negative / 3 | none | 明确无法使用，不推断运输责任。 |
| SYN-05 | synthetic | 使用时出现明显头晕和眼睛刺痛，我已经停止使用。 | safety_discomfort / negative / 3 | none | 明确身体不适；只记录陈述，不确认医学因果。 |
| SYN-06 | synthetic | 价格稍贵，有点小遗憾，如果便宜一点我会再买。 | price_value / negative / 1 | conditional | 轻微价格不满与条件复购独立标注。 |
| SYN-07 | synthetic | 瓶身设计很好看；配送延误，明显影响使用体验；客服回复及时，我很满意。 | appearance_usage / positive / null；logistics / negative / 2；service / positive / null | none | 三个主题分别标情绪；不标整条 mixed。 |
| SYN-08 | synthetic | 前调我很喜欢，后调不太合口味，有一点小失望。 | scent_preference / mixed / 1 | none | 同一偏好主题内正负并存；未表达身体不适。 |
| SYN-09 | synthetic | 好 | other / positive / null | none | 少于 4 个字，一律 other；仍可判断正向。 |
| SYN-10 | synthetic | 暂时没有更多可以补充的信息。 | other / neutral / null | none | 字数足够但缺少具体主题信息。 |

## 问卷草稿匹配检查（未发布、未修改）

检查对象为 `docs/survey_draft.md`，仅检查题目文字与规则，不读取任何评测数据。

| 问卷内容 | 与主题表的关系 | 检查结果 |
|---|---|---|
| Q3 气味与预期 | scent_mismatch、scent_preference | 基本相关，但个人预期不必来自商品描述；建议负责人确认是否区分「商品描述是否一致」与「个人是否喜欢」。 |
| Q3 留香效果 | longevity_diffusion | 匹配；扩香、浓淡没有单独提示，开放回答仍可覆盖。 |
| Q3 包装和物流 | packaging_leak、logistics | 匹配；标注时需要区分破损事实与物流过程，不推断责任。 |
| Q3 价格、使用便利、客服 | price_value、appearance_usage、service | 匹配；外观美观没有单独提示，但仍可归入现有主题。 |
| Q3 使用时不舒服 | safety_discomfort | 匹配明确身体不适；儿童/宠物安全顾虑未被直接提示。 |
| Q3 必填且不少于 15 字 | other | 无法覆盖短文本边界，other 仍适用于内容不足或主题之外；短文本示例仅作教学，不改变问卷约束。 |
| Q4 评分 | rating | 是输入辅助字段，不替代逐主题 sentiment 或 severity。 |
| Q5 复购问题 | repurchase_signal | 题目相关，但「看情况」不说明条件，「没想过」也不是文本未提及的同义标注；不能机械映射四个选项。 |
| Q1/Q2/Q6/Q7 | 产品筛选、类型、渠道、重复题组 | 不直接映射主题；不按购买渠道推断物流或客服评价。 |

主要待确认问题：草稿规定 Q5 不写入 CSV，却供人工标注参考。如果文本没提复购而 Q5 选择「会」，人工标签可能成为系统输入中不可见的信息。建议项目负责人明确标注证据范围后再正式使用；本次不修改该规则、不发布问卷。另有 Q1 写明选「否」结束，但列出的选项只有产品类别，没有「否」选项，建议问卷制作前核对。

## 待项目负责人确认的边界

以下不是已生效规则。遇到这些情况时暂停对应样本的最终裁定，记录争议并请求确认，不扩展 PRD。

1. 一条反馈超过 3 个明确主题时，按什么依据选取 3 个；是否必须保留安全主题？
2. 少于 4 字却明确涉及安全的「头晕」「过敏」：PRD 当前要求归 other，与安全识别目标存在张力；是否需要特例，以及严重度如何标注？当前主题规则不擅自加特例。
3. 缺乏上下文的「刺鼻」「闻着难受」如何区分气味偏好、浓淡与身体刺激？商品描述不符和个人厌恶描述同一气味时，何时算两个独立主题证据？
4. 同一主题有多个不同程度的负向影响，含 mixed 的情况，severity 取最高影响还是其他口径？只有安全顾虑、尚未发生伤害时，情绪和严重度如何统一？
5. 同条反馈同时出现回购、不会回购或条件回购的矛盾表达如何选值？Q5 能否影响仅凭 Q3 文本的 repurchase_signal 标注？
6. 已有具体主题，同时含无法归类的其他内容时，other 能否与具体主题并存？

完成这些确认前，指南可用于明确案例的讲解，不视为所有边界均已定稿。
