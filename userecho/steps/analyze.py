"""Deterministic topic statistics for validated classification outputs."""

import math
from pathlib import Path
from typing import Literal, get_args

import pandas as pd
import yaml
from collections import defaultdict
from statistics import median

from pydantic import BaseModel, ConfigDict

from userecho.classification_schema import FeedbackClassification, TopicAnnotation, TopicCode


COLUMN_LABELS = {
    "topic_code": "主题代码", "total_mention_count": "全部提及数",
    "mention_count": "负向提及数（含正负并存）", "share": "负向提及占有效反馈比例",
    "F": "频率分", "S": "严重度分（中位数向下取整）",
    "risk_alert": "风险警报", "insufficient_evidence": "证据不足",
    "evidence": "原文证据", "priority": "优先级", "I": "影响分",
    "review_required": "需要人工复核",
}


class TopicEvidence(TopicAnnotation):
    feedback_id: str


class TopicStatistics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic_code: TopicCode
    total_mention_count: int
    mention_count: int
    share: float
    F: int
    S: int | None
    risk_alert: bool
    insufficient_evidence: bool
    evidence: list[TopicEvidence]


def frequency_score(share: float) -> int:
    """Use the unrounded proportion, including exact threshold equality."""
    if not math.isfinite(share) or not 0 <= share <= 1:
        raise ValueError("负向提及比例必须在 0 到 1 之间。")
    return 3 if share >= 0.15 else 2 if share >= 0.05 else 1


def topic_statistics(classifications: list[FeedbackClassification],
                     valid_sample_size: int) -> list[TopicStatistics]:
    """Keep the cleaned-sample denominator even when classification is partial."""
    if type(valid_sample_size) is not int or not 0 <= valid_sample_size <= 200:
        raise ValueError("有效样本量必须是 0–200 的整数。")
    ids = []
    groups = defaultdict(list)
    for classification in classifications:
        if not isinstance(classification, FeedbackClassification):
            raise ValueError("统计输入必须是分类模块的最终分类结果。")
        value = FeedbackClassification.model_validate(classification.model_dump())
        ids.append(value.feedback_id)
        for topic in value.topics:
            if topic.mention_type == "uncertain" or not topic.source_span.strip():
                raise ValueError("统计输入包含未经证据过滤的主题。")
            if topic.mention_type == "consultation" and (
                topic.code not in {"other", "safety_discomfort"}
                or topic.sentiment != "neutral" or topic.severity is not None
            ):
                raise ValueError("统计输入中的咨询主题尚未规范化。")
            groups[topic.code].append(TopicEvidence(feedback_id=value.feedback_id, **topic.model_dump()))
    if len(ids) != len(set(ids)) or any(not fid.strip() for fid in ids):
        raise ValueError("分类反馈 ID 必须非空且不重复。")
    if len(ids) > valid_sample_size:
        raise ValueError("成功分类数不能超过有效样本量。")
    result = []
    for code, evidence in groups.items():
        negative = [e for e in evidence if e.sentiment in {"negative", "mixed"}]
        share = len(negative) / valid_sample_size
        risk = any(e.severity == 3 or (code == "safety_discomfort" and
                   e.sentiment in {"negative", "mixed"}) for e in evidence)
        result.append(TopicStatistics(
            topic_code=code, total_mention_count=len(evidence), mention_count=len(negative),
            share=share, F=frequency_score(share),
            S=math.floor(median(e.severity for e in negative)) if negative else None,
            risk_alert=risk, insufficient_evidence=len(negative) < 2, evidence=evidence,
        ))
    return result


ROOT = Path(__file__).resolve().parents[2]
IMPACT_PATH = ROOT / "config" / "impact.yaml"
GOALS = ("satisfaction", "complaints", "repurchase")
COLUMN_LABELS.update({
    "base_score": "基础分", "score_explanation": "打分与规则说明",
    "path": "处理路径", "rule_violation": "规则冲突", "violation_reason": "冲突原因",
})


class TopicAnalysis(TopicStatistics):
    I: int
    priority: Literal["P0", "P1", "P2", "P3"] | None
    base_score: int | None
    score_explanation: str
    path: str
    review_required: bool
    rule_violation: bool
    violation_reason: str | None


def load_impact(goal_type: str, path: Path = IMPACT_PATH) -> dict[str, int]:
    """Require complete explicit impact values; never silently fill defaults."""
    if goal_type not in GOALS:
        raise ValueError("未知分析目标。")
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(config, dict) or config.get("status") != "approved":
            raise ValueError()
        goals = config["goals"]
        if not isinstance(goals, dict):
            raise ValueError()
        if set(goals) != set(GOALS):
            raise ValueError()
        for values in goals.values():
            if not isinstance(values, dict) or set(values) != set(get_args(TopicCode)) or any(
                type(v) is not int or not 1 <= v <= 3 for v in values.values()
            ):
                raise ValueError()
        return dict(goals[goal_type])
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise ValueError("影响分配置无效：必须为 approved，且每个分析目标包含十个主题的 1–3 整数分值。") from exc


def analyze(classifications: list[FeedbackClassification], valid_sample_size: int,
            goal_type: str = "satisfaction", *, impact_path: Path = IMPACT_PATH) -> pd.DataFrame:
    """Aggregate final topics and apply the three paths without any LLM calls."""
    statistics = topic_statistics(classifications, valid_sample_size)
    impact = load_impact(goal_type, impact_path)
    rows = []
    for topic in statistics:
        violation_ids = [e.feedback_id for e in topic.evidence
                         if topic.topic_code == "scent_preference" and e.severity == 3]
        violation = bool(violation_ids)
        priority = score = None
        review = violation or (topic.risk_alert and (topic.mention_count < 2 or valid_sample_size < 5))
        if valid_sample_size < 5:
            path = "summary_only"
            explanation = "样本量不足，仅展示主题统计"
        elif topic.mention_count >= 2:
            path = "priority"
            score = topic.F + topic.S + impact[topic.topic_code]
            level = 0 if score >= 8 else 1 if score >= 6 else 2 if score >= 4 else 3
            rules = []
            if topic.topic_code == "scent_preference":
                level = max(level, 2)
                rules.append("个人偏好最高 P2")
            if topic.topic_code == "safety_discomfort":
                level = min(level, 1)
                rules.append("安全主题最低 P1")
            if any(e.severity == 3 for e in topic.evidence):
                # Restore the base level so a safety override never demotes P0.
                base_level = 0 if score >= 8 else 1 if score >= 6 else 2 if score >= 4 else 3
                level = min(base_level, 1)
                rules.append("severity=3 最低 P1，优先于偏好上限")
            if violation:
                level = 1
                rules.append("偏好与 severity=3 冲突，按负责人裁决固定 P1 并复核")
            priority = f"P{level}"
            explanation = f"F{topic.F} + S{topic.S} + I{impact[topic.topic_code]} = {score} → {priority}"
            if rules:
                explanation += "；" + "；".join(rules)
        elif topic.risk_alert:
            path, explanation = "risk_only", "负向提及不足 2 条，仅风险警报并人工复核"
        else:
            path, explanation = "insufficient_evidence", "负向提及不足 2 条，不计算优先级"
        row = TopicAnalysis(**topic.model_dump(), I=impact[topic.topic_code],
            priority=priority, base_score=score, score_explanation=explanation, path=path,
            review_required=review, rule_violation=violation,
            violation_reason="scent_preference 与 severity=3 冲突，需人工核对主题及严重度" if violation else None)
        if valid_sample_size < 5:
            row.insufficient_evidence = True
        rows.append(row.model_dump())
    frame = pd.DataFrame(rows, columns=list(TopicAnalysis.model_fields))
    if not frame.empty:
        frame = frame.sort_values(["priority", "mention_count", "topic_code"],
                                  ascending=[True, False, True], na_position="last", kind="stable").reset_index(drop=True)
    return frame


def display_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a display-only copy with Chinese labels and readable evidence."""
    display = frame.copy(deep=True)
    if not display.empty:
        display["share"] = display["share"].map(lambda value: f"{value:.1%}")
        display["evidence"] = display["evidence"].map(lambda items: "；".join(
            f"{e['feedback_id']}：{e['source_span']}（{e['sentiment']}）" for e in items))
        display["path"] = display["path"].map({"priority":"优先级排序", "risk_only":"风险复核",
            "insufficient_evidence":"证据不足", "summary_only":"仅主题统计"})
    return display.rename(columns=COLUMN_LABELS)
