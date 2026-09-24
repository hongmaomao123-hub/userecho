"""Exercise strict output validation without calling an LLM."""

import json
from pathlib import Path
from typing import get_args

import pytest
import yaml
from pydantic import ValidationError

from userecho.classification_schema import (
    FeedbackClassification, RawFeedbackClassification, TopicAnnotation, TopicCode,
)


@pytest.mark.parametrize("sentiment", ["positive", "neutral"])
def test_nonnegative_severity_is_real_null(sentiment):
    model = TopicAnnotation(code="other", sentiment=sentiment, severity=None)
    assert model.severity is None
    assert json.loads(model.model_dump_json())["severity"] is None


@pytest.mark.parametrize("sentiment", ["negative", "mixed"])
@pytest.mark.parametrize("severity", [1, 2, 3])
def test_negative_severity_range(sentiment, severity):
    model = TopicAnnotation(code="safety_discomfort", sentiment=sentiment, severity=severity)
    assert model.severity == severity


@pytest.mark.parametrize("sentiment,severity", [
    ("positive", 1), ("neutral", 3), ("negative", None), ("mixed", None),
    ("negative", 0), ("negative", 4), ("negative", True), ("negative", 2.0),
    ("negative", "2"), ("neutral", "null"),
])
def test_invalid_severity_is_rejected(sentiment, severity):
    with pytest.raises(ValidationError):
        TopicAnnotation(code="other", sentiment=sentiment, severity=severity)


def test_severity_must_be_present():
    with pytest.raises(ValidationError):
        TopicAnnotation.model_validate({"code": "other", "sentiment": "neutral"})


@pytest.mark.parametrize("field,value", [
    ("code", "unknown"), ("sentiment", "uncertain"), ("risk_alert", False),
])
def test_invalid_enum_or_extra_field_is_rejected(field, value):
    payload = {"code": "other", "sentiment": "neutral", "severity": None}
    payload[field] = value
    with pytest.raises(ValidationError):
        TopicAnnotation.model_validate(payload)


def test_topic_codes_match_configuration():
    path = Path(__file__).resolve().parents[1] / "config" / "taxonomy.yaml"
    topics = yaml.safe_load(path.read_text(encoding="utf-8"))["topics"]
    assert set(get_args(TopicCode)) == set(topics)


@pytest.mark.parametrize("model,limit", [(RawFeedbackClassification, 10), (FeedbackClassification, 3)])
def test_feedback_model_limits(model, limit):
    codes = list(get_args(TopicCode))
    payload = {"feedback_id": "001", "topics": [
        {"code": code, "sentiment": "neutral", "severity": None} for code in codes[:limit]
    ], "repurchase_signal": "none"}
    assert len(model.model_validate(payload).topics) == limit
    payload["topics"] = []
    with pytest.raises(ValidationError):
        model.model_validate(payload)
    payload["topics"] = [{"code": "other", "sentiment": "neutral", "severity": None}] * (limit + 1)
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("model", [RawFeedbackClassification, FeedbackClassification])
@pytest.mark.parametrize("change", ["duplicate", "repurchase", "id", "extra"])
def test_feedback_model_rejects_invalid_contract(model, change):
    payload = {"feedback_id": "001", "topics": [
        {"code": "other", "sentiment": "neutral", "severity": None}
    ], "repurchase_signal": "none"}
    if change == "duplicate":
        payload["topics"] *= 2
    elif change == "repurchase":
        payload["repurchase_signal"] = "maybe"
    elif change == "id":
        payload["feedback_id"] = 1
    else:
        payload["risk_alert"] = True
    with pytest.raises(ValidationError):
        model.model_validate(payload)
