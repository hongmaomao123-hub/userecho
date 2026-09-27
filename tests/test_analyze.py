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


from pathlib import Path
from unittest.mock import patch
import yaml
from userecho.steps.analyze import analyze, load_impact, IMPACT_PATH


def test_approved_impact_values():
    expected = {
        'scent_mismatch': (3,3,3), 'scent_preference': (2,1,2),
        'longevity_diffusion': (3,3,3), 'packaging_leak': (3,3,3),
        'safety_discomfort': (3,3,3), 'price_value': (2,2,3),
        'logistics': (2,3,2), 'appearance_usage': (2,2,2),
        'service': (2,3,2), 'other': (1,1,1),
    }
    for i, goal in enumerate(('satisfaction', 'complaints', 'repurchase')):
        assert load_impact(goal) == {code: values[i] for code, values in expected.items()}


def test_overview_only_has_no_formal_priority():
    row = analyze([feedback(1), feedback(2)], 4).iloc[0]
    assert row['path'] == 'summary_only'
    assert row['priority'] is None and row['base_score'] is None
    assert row['insufficient_evidence']


def test_negative_and_mixed_enter_priority():
    row = analyze([feedback(1), feedback(2, sentiment='mixed', severity=2)], 30).iloc[0]
    assert row['path'] == 'priority' and row['mention_count'] == 2
    assert row['S'] == 1 and row['base_score'] == 6 and row['priority'] == 'P1'
    assert not row['insufficient_evidence']


@pytest.mark.parametrize('code,severity', [('safety_discomfort', 1), ('packaging_leak', 3)])
def test_low_frequency_risk_path(code, severity):
    row = analyze([feedback(1, code, severity=severity)], 30).iloc[0]
    assert row['path'] == 'risk_only' and row['risk_alert']
    assert row['priority'] is None and row['review_required'] and row['insufficient_evidence']


def test_low_frequency_without_risk_has_insufficient_evidence():
    row = analyze([feedback(1)], 30).iloc[0]
    assert row['path'] == 'insufficient_evidence' and row['insufficient_evidence']
    assert row['priority'] is None and not row['risk_alert'] and not row['review_required']


@pytest.mark.parametrize('code,severities', [('safety_discomfort', [1,1]), ('other', [1,3])])
def test_safety_and_severity_three_enforce_minimum_p1(code, severities):
    row = analyze([feedback(i, code, severity=s) for i,s in enumerate(severities)], 200).iloc[0]
    assert row['base_score'] < 6 and row['priority'] == 'P1' and row['risk_alert']


def test_preference_is_capped_at_p2():
    row = analyze([feedback(i, 'scent_preference', severity=2) for i in range(2)], 5).iloc[0]
    assert row['base_score'] == 7 and row['priority'] == 'P2'
    assert not row['rule_violation'] and row['violation_reason'] is None


def test_preference_severity_three_conflict_is_exactly_p1_without_document_writes():
    path = Path(__file__).resolve().parents[1] / 'docs' / 'bad_case_log.md'
    before = path.read_bytes()
    with patch.object(Path, 'write_text', side_effect=AssertionError('No document writes')), patch.object(
        Path, 'write_bytes', side_effect=AssertionError('No document writes')
    ):
        row = analyze([feedback(i, 'scent_preference', severity=3) for i in range(2)], 5).iloc[0]
    assert row['base_score'] == 8 and row['priority'] == 'P1'
    assert row['review_required'] and row['rule_violation'] and row['risk_alert']
    assert 'severity=3' in row['violation_reason']
    assert path.read_bytes() == before


@pytest.mark.parametrize('defect', ['goal', 'topic', 'low', 'high', 'placeholder'])
def test_invalid_or_unapproved_impact_fails(tmp_path, defect):
    config = yaml.safe_load(IMPACT_PATH.read_text())
    if defect == 'goal':
        del config['goals']['complaints']
    elif defect == 'topic':
        del config['goals']['satisfaction']['other']
    elif defect == 'placeholder':
        config['status'] = 'placeholder'
    else:
        config['goals']['satisfaction']['other'] = 0 if defect == 'low' else 4
    path = tmp_path / 'impact.yaml'
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(ValueError, match='影响分配置无效'):
        load_impact('satisfaction', path)
    with pytest.raises(ValueError, match='影响分配置无效'):
        analyze([feedback(1)], 30, impact_path=path)
