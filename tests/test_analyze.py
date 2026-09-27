"""Offline tests for deterministic statistics and priority calculation."""

import pytest

from userecho.classification_schema import FeedbackClassification
from userecho.steps.analyze import frequency_score, topic_statistics


def feedback(fid, code="longevity_diffusion", sentiment="negative", severity=1,
             kind="asserted"):
    return FeedbackClassification(feedback_id=str(fid), topics=[{
        "code": code, "sentiment": sentiment, "severity": severity,
        "source_span": "反馈原文", "mention_type": kind,
    }], repurchase_signal="none")


@pytest.mark.parametrize("share,score", [(0.149, 2), (0.15, 3), (0.049, 1), (0.05, 2)])
def test_frequency_boundaries(share, score):
    assert frequency_score(share) == score


@pytest.mark.parametrize("severities,expected", [([1, 2], 1), ([2, 3], 2), ([1, 3], 2), ([1, 2, 3], 2)])
def test_severity_median_rounds_down(severities, expected):
    values = [feedback(i, severity=s, sentiment="mixed" if i % 2 else "negative")
              for i, s in enumerate(severities)]
    assert topic_statistics(values, 30)[0].S == expected


def test_partial_classification_keeps_cleaned_denominator():
    row = topic_statistics([feedback(1), feedback(2)], 200)[0]
    assert row.share == 0.01 and row.F == 1
    assert row.mention_count == 2 and not row.insufficient_evidence


def test_positive_neutral_do_not_enter_negative_statistics():
    row = topic_statistics([feedback(1), feedback(2, sentiment="mixed", severity=2),
                            feedback(3, sentiment="positive", severity=None),
                            feedback(4, sentiment="neutral", severity=None)], 30)[0]
    assert row.total_mention_count == 4 and row.mention_count == 2
    assert row.S == 1 and len(row.evidence) == 4
    assert row.evidence[0].source_span == "反馈原文"
    assert row.evidence[0].feedback_id == "1"


def test_neutral_safety_consultation_never_alerts():
    row = topic_statistics([feedback(1, "safety_discomfort", "neutral", None, "consultation")], 30)[0]
    assert not row.risk_alert and row.insufficient_evidence
    assert row.mention_count == 0 and row.S is None


@pytest.mark.parametrize("code,severity", [("safety_discomfort", 1), ("packaging_leak", 3)])
def test_risk_is_independent_of_low_frequency(code, severity):
    row = topic_statistics([feedback(1, code, severity=severity)], 30)[0]
    assert row.risk_alert and row.insufficient_evidence


def test_empty_results_are_safe():
    assert topic_statistics([], 0) == []
    assert topic_statistics([], 200) == []


@pytest.mark.parametrize("size", [-1, 201, True, 1.5])
def test_invalid_denominator_rejected(size):
    with pytest.raises(ValueError):
        topic_statistics([], size)


def test_duplicates_and_excess_classifications_rejected():
    with pytest.raises(ValueError):
        topic_statistics([feedback(1), feedback(1)], 30)
    with pytest.raises(ValueError):
        topic_statistics([feedback(1)], 0)
