# UserEcho v1.3 主题与标注指南

## 适用范围

唯一有效需求是 `docs/PRD.md` v1.3。主题说明位于 `config/taxonomy.yaml`，本指南解释现有规则，不另立 PRD。尚未明确的边界列在末尾，需项目负责人确认后才能成为规则。本阶段不调用 LLM、不配置影响分、不实现分类或后续流程。

主题表字段经项目负责人确认，固定为 `name_zh`、`definition`、`include`、`exclude`、`confused_with`。前两项为字符串，后三项为字符串列表；`confused_with` 只能引用现有主题 code，且不得引用自身。主题表以 PRD 的十个 code 为键；`name_zh` 为中文名称，`definition` 为定义，`include` / `exclude` 为纳入与排除边界，`confused_with` 为易混淆的相邻主题。排除项用于区分单一证据的归属，不禁止有独立证据的多标签反馈。

## 主题提及来源（运行时契约）

每个候选及最终主题都携带 `source_span` 和 `mention_type`：

| mention_type | 定义 |
|---|---|
| asserted | 明确陈述的体验、事实或评价 |
| uncertain | 猜测、可能性、备选原因或无法确认的判断；不能把 A 还是 B 都当作事实 |
| consultation | 尚未发生体验的售前或使用前咨询；儿童、孕妇、宠物安全咨询属于这一类 |

`source_span` 必须逐字复制原文中的连续片段，包括标点符号和空格；不能改写、补充省略号或修正错别字。代码仅去掉首尾空白，再做非空、精确原文子串校验；标点或内部空格偏差也会使整条进入人工复核，不调用模型修补。

模型提取所有候选，不自行删 uncertain。同主题 asserted 优先于 uncertain；过滤后只保留可信提及，再执行三主题裁剪。全 uncertain 进入人工复核；安全 consultation 强制 neutral/null 且不触发风险；非安全 consultation 有其他可信主题时删除，无剩余主题时转换为 other/neutral/null，保留原文证据及 consultation 类型。完整处理顺序与原因码见 PRD 第 3.3 节。

本次不回填历史教学 CSV 的证据字段，不将模型提取当成人工裁决。已有人工 CSV 格式不因此静默重写；本节新增字段首先约束分类运行时输出。

## 标注字段

最终一条反馈最多 3 个主题，同一主题只出现一次；模型原始候选可重复，须经代码去重。每个主题分别标注 `sentiment` 和 `severity`，整条反馈只标注一个 `repurchase_signal`。不因整条反馈有正面或负面词，就把所有主题都标成相同情绪。系统支持最多 3 个主题，不存在通用的“缺陷优先单主标签”规则；跨主题内容须保留各自有依据的主题并分别标注 sentiment 和 severity，不新增 `main_topic` 或 defect-first 规则。

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
| 1 | 轻微主观不悦，如口味不喜欢 |
| 2 | 阻碍使用或购买，如漏液、明显贵但买了 |
| 3 | 仅用于明确身体不适或安全风险；仅无法使用或财产损失不再单独作为 3 的依据 |

negative 和 mixed 必须有 1–3 的严重度；不能因主题属于 other 就省略负向严重度。severity 根据文本中的影响程度标注，不用反馈数量、星级或优先级代替。条件已经阻止当前购买或复购时，价格问题通常为 `severity=2`；不能仅看到“贵”或条件表达就机械定级，需有阻止当前购买或复购的文本依据。一个主题有多个负向影响时如何选单一严重度，尚待确认。

| repurchase_signal | 使用条件 |
|---|---|
| positive | 明确会回购或再次购买 |
| negative | 明确不会再买 |
| conditional | 明确在某个条件满足后才考虑再次购买 |
| none | 未明确表达再次购买意图 |

**复购信号硬规则**：`repurchase_signal` 只能依据用户明确表达的再次购买意图判断，不得从满意、不满、评分、换货结果、情绪或 severity 推测。只有推荐他人、没有表达自己再次购买意图时，标为 `none`。复购信号与主题情绪独立：有不满仍可能有条件回购。“不敢再用、不敢再点、停止使用”是使用行为，不自动推导为 `repurchase_signal=negative`；只有明确提到不买、不回购、不下单等购买意愿，才能标 negative。没有明确购买意图时标 none。以下示例只依据示例文本标注。问卷 Q5 是否可以作为额外标注依据尚待确认。

## 重点主题边界

- `scent_mismatch` 与 `scent_preference`：只有涉及官方页面、商家描述或明确宣传承诺与实际气味不符，才标 `scent_mismatch`；试香纸、皮肤、衣物等不同载体上的主观气味差异，在没有官方宣传对照时暂归 `scent_preference`。仅说不是自己喜欢的味道，不等于宣传不符。「与预期不同」而未说明预期来自何处，不能直接作为宣传不符的确定示例。
- `scent_preference` 与 `safety_discomfort`：仅表达个人不喜欢气味属于偏好；明确头晕、过敏、身体刺激或儿童/宠物安全顾虑属于安全。不要从个人厌恶推断生理伤害，也不要忽略明确的不适陈述。模糊的「刺鼻」「闻着难受」见待确认项。
- `longevity_diffusion`：太淡、太浓、扩散范围及留香效果归入此类；仅表达不喜欢气味归入 `scent_preference`。同一反馈可以同时包含这两个主题，但每个主题需有各自的文本依据；不能把浓淡问题只标成个人偏好。同时明确身体不适时可另标有证据的安全主题。
- `safety_discomfort`：包含已经发生的身体症状，以及明确的儿童或宠物安全顾虑。售前或使用前的儿童、宠物安全咨询归入 `safety_discomfort / neutral / severity=null`；这一提及不触发 `risk_alert`。若同条反馈有其他独立的高风险提及，仍按 PRD 风险规则处理，不能由中性咨询覆盖。
- `packaging_leak` 与 `logistics`：破损或漏液本身不能证明物流责任；明确提及配送慢等内容，才另有物流主题证据。
- `other`：去空格后少于 4 个字的反馈按 PRD 一律归入 other；其余无足够信息或不属于现有主题的内容也归入 other。other 不等于 neutral，例如「好」仍是 positive。空文本已由数据检查排除，不应作为一条反馈补标 other。

只标原文支持的体验，不作医疗诊断或因果确认。`risk_alert` 由后续代码根据主题、sentiment 和 severity 派生，不作为人工标注字段，也不是 P0–P3 优先级。negative/mixed 的 safety_discomfort 或任意 severity=3 的提及触发风险；neutral 安全咨询不触发。下文“风险说明”仅解释派生规则，不要求标注员填写 risk_alert，本阶段不实现风险计算。

## 10 条 guided examples（synthetic）

**这十条为 synthetic guided examples，仅用于解释和讨论标注规则，不用于盲标或作为金标准（gold standard），不计入真实评测集，不用于效果声明。** 原 case_id 和用户文本保持不变，原文保存在 `data/dev/guided_examples_round1.csv`。本表替换此前独立编写的教学示例，避免混用两个编号体系。

表内 `code / sentiment / severity` 为教学说明，不是分类接口输出。`待负责人确认`、`待讨论` 是未定标记，不是新增 severity 枚举，也不可以 null 替代尚未确定的负向严重度；正式标注仍须在 1–3 中经确认取值。除本次明确确认的规则外，教学讨论值不代表项目负责人已批准的唯一答案。risk_alert 仅作规则说明，本阶段不实现风险计算。

| case_id | 来源与用途 | feedback_text | 主题标注或讨论方向 | repurchase_signal | 说明 |
|---|---|---|---|---|---|
| SYN-BR1-01 | synthetic / guided examples | 这款喷头每次按下去都很顺手，单手也能操作，我挺满意的。 | appearance_usage / positive / null | none | 操作满意不代表会再次购买。 |
| SYN-BR1-02 | synthetic / guided examples | 页面说是清新的绿茶味，打开却是一股奶糖味，和介绍差得有点远。 | scent_mismatch / negative / 待负责人确认 | none | 明确与页面描述不符；severity 的 1/2 分界需项目负责人确认，当前不提供唯一答案。 |
| SYN-BR1-03 | synthetic / guided examples | 送得比预计早一天，不过拆开时瓶口周围都是液体，找客服当天就安排了换货，这点挺省心。 | logistics / positive / null；packaging_leak / negative / 2；service / positive / null | none | 教学讨论值：漏液的 severity 暂示为 2，不因换货顺利推断复购；严重度未作为标准答案。 |
| SYN-BR1-04 | synthetic / guided examples | 放在卧室里香味能留到第二天，这点很好，但走到门口就几乎闻不到了，扩散范围让我有些失望。 | longevity_diffusion / mixed / 1 | none | 同一主题中留香满意、扩散范围不满意；severity 为教学讨论值。 |
| SYN-BR1-05 | synthetic / guided examples | 这一小瓶卖这个价我觉得不太值，等下次有折扣再考虑回购。 | price_value / negative / 待负责人确认 | conditional | 折扣是明确的再次购买条件；severity 的 1/2 分界需项目负责人确认，当前不提供唯一答案。 |
| SYN-BR1-06 | synthetic / guided examples | 喷在手腕上没多久就开始发痒，还起了一片红点，我洗掉后没敢再用，以后也不会买了。 | safety_discomfort / negative / 3 | negative | 已发生皮肤症状，并明确以后不会买；按现有规则触发风险标志。 |
| SYN-BR1-07 | synthetic / guided examples | 朋友说这款很清爽，我原本也这么期待，实际闻着偏甜，不是我平时喜欢的感觉。 | scent_preference / negative / 1 | none | 朋友评价与个人期待不等于商品宣传；severity 为教学讨论值，不推断复购。 |
| SYN-BR1-08 | synthetic / guided examples | 才插两根藤条就觉得冲，闻着难受，说不清是味道不喜欢还是太浓了。 | longevity_diffusion / negative / 待讨论 | none | 必须包含浓淡主题；若确认另有独立的气味厌恶证据，可以加 scent_preference。本句原因表达不确定，不把它仅标为偏好，也不直接等同已发生身体症状；severity 及是否加标签保留讨论。 |
| SYN-BR1-09 | synthetic / guided examples | 还行吧 | other / neutral / null | none | 少于 4 字，按当前规则归 other；“还行吧”的情绪是教学讨论值，不作唯一答案。 |
| SYN-BR1-10 | synthetic / guided examples | 家里有猫，放这款香薰会不会有影响？目前还没拆封，想先问清楚。 | safety_discomfort / neutral / null | none | 中性宠物安全咨询，未报告症状或负向体验；risk_alert=false。 |

## 第二轮：合成边界案例校准

当前记录不能确认第二轮是否由项目负责人在查看参考答案前独立完成，因此本轮按“合成边界案例校准”记录，不宣称为盲标、不计算一致率，不作为真实评测或金标准。原始 CSV 文件名仅为历史命名，不证明独立标注流程；本次不改写原始数据。仅下列两项为本次项目负责人明确裁决，不补写其他案例答案。

| case_id | 项目负责人裁决：主题 / sentiment / severity | repurchase_signal | 裁决说明 |
|---|---|---|---|
| SYN-BR2-04 | safety_discomfort / neutral / null | none | 儿童衣物香氛使用前的中性安全咨询；不触发 risk_alert，该说明不属于人工标注字段。 |
| SYN-BR2-05 | appearance_usage / positive / null；packaging_leak / negative / 2 | none | 同时保留外观肯定与漏液不满，各主题单独标情绪和严重度；没有明确再次购买意图。不新增 main_topic 或 defect-first 规则。 |

## 人工标注 CSV 契约

人工标注 CSV 包含三组主题字段；即使某条案例只有一个或两个主题，也必须保留完整表头，未使用的整组字段保持为空：

```csv
case_id,feedback_text,topic_1,sentiment_1,severity_1,topic_2,sentiment_2,severity_2,topic_3,sentiment_3,severity_3,repurchase_signal
```

多标签按主题在文本中首次出现的顺序保存，同一主题只保存一次。评测时按 topic code 组成的无序集合匹配，不能按 topic_1/topic_2/topic_3 的位置比较；如核对情绪或严重度，应先按 topic code 对齐，再比较该主题的字段。存储顺序不表示主次或优先级，不改变最多三个主题的限制。

CSV 是文本格式：已标主题的 positive/neutral 严重度可写为文本 `null`，读取后必须标准化为 Python `None`；后续 Pydantic 校验及 JSON 序列化必须使用真正的 `null`，不能输出字符串 `"null"`。未使用的主题组保持三个单元格全空，读取时视为没有该主题；不得补造主题。negative/mixed 的 severity 必须是整数 1–3，未裁定不能用 null 冒充已完成标注。此规则仅针对人工标注字段，不把 feedback_text 中的字面文本当成缺失值。

本轮只规定上述契约，不实现读取器、Pydantic 模型或评测代码。

## 第三轮：合成边界校准参考集

本组定位为 synthetic “合成边界校准参考集”，应保存在 `data/dev/synthetic_boundary_calibration_round3.csv`；不标为 Gold Standard，不进入真实评测集，不计算独立盲标一致率。taxonomy 继续为 v0.9 candidate，不冻结。

当前工作区未找到第三轮原始反馈或人工标注 CSV，等待项目负责人提供源文件后再迁移、补齐第三组字段；不得为凑齐参考集编造反馈或其余标注。以下仅记录负责人本轮明确裁决：

| case_id | topic | sentiment | severity | repurchase_signal |
|---|---|---|---|---|
| SYN-BR3-06 | safety_discomfort | negative | 3 | none |
| SYN-BR3-08 | price_value | negative | 2 | conditional |

这两条裁决不改写第一轮或第二轮同尾号案例，也不意味着其余第三轮案例已经审定。

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
4. 同一主题有多个不同程度的负向影响，含 mixed 的情况，severity 取最高影响还是其他口径？中性售前安全咨询已明确为 neutral / null；带有负向或 mixed 情绪但尚未发生伤害的安全顾虑，其严重度如何统一？另需确认 guided examples 02、05 的 severity 1/2 分界。
5. 同条反馈同时出现回购、不会回购或条件回购的矛盾表达如何选值？Q5 能否影响仅凭 Q3 文本的 repurchase_signal 标注？
6. 已有具体主题，同时含无法归类的其他内容时，other 能否与具体主题并存？

完成这些确认前，指南可用于明确案例的讲解，不视为所有边界均已定稿。
