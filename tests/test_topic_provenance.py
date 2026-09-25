"""Check the evidence transformation is deterministic and does not mutate input."""

from userecho.classification_schema import RawFeedbackClassification
from userecho.steps.topic_provenance import filter_topics


def test_filter_is_pure_and_retains_verbatim_consultation_evidence():
    raw = RawFeedbackClassification.model_validate({
        "feedback_id": "a", "repurchase_signal": "none", "topics": [{
            "code": "safety_discomfort", "sentiment": "negative", "severity": 3,
            "source_span": "  孩子能用吗？ ", "mention_type": "consultation"}]})
    before = raw.model_dump()
    first = filter_topics(raw, "孩子能用吗？")
    second = filter_topics(raw, "孩子能用吗？")
    assert first == second
    assert raw.model_dump() == before
    assert first.topics[0].source_span == "孩子能用吗？"
    assert first.topics[0].sentiment == "neutral" and first.topics[0].severity is None
    first.topics[0].source_span = "changed"
    assert raw.model_dump() == before


def test_uncertain_topic_is_removed_with_machine_readable_reason():
    raw = RawFeedbackClassification.model_validate({
        "feedback_id": "a", "repurchase_signal": "none", "topics": [
            {"code": "longevity_diffusion", "sentiment": "negative", "severity": 2,
             "source_span": "才插两根就很冲", "mention_type": "asserted"},
            {"code": "scent_preference", "sentiment": "negative", "severity": 1,
             "source_span": "说不清是不是不喜欢味道", "mention_type": "uncertain"},
        ]})
    result = filter_topics(raw, "才插两根就很冲，说不清是不是不喜欢味道。")
    assert result.review_reason is None
    assert [topic.model_dump() for topic in result.topics] == [raw.topics[0].model_dump()]
    assert result.events == [{"feedback_id": "a", "code": "scent_preference",
                              "reason": "dropped_uncertain_topic"}]


def test_all_uncertain_topics_require_whole_feedback_review():
    raw = RawFeedbackClassification.model_validate({
        "feedback_id": "a", "repurchase_signal": "none", "topics": [
            {"code": "longevity_diffusion", "sentiment": "negative", "severity": 2,
             "source_span": "不知道是太浓还是不喜欢味道", "mention_type": "uncertain"},
            {"code": "scent_preference", "sentiment": "negative", "severity": 1,
             "source_span": "不知道是太浓还是不喜欢味道", "mention_type": "uncertain"},
        ]})
    result = filter_topics(raw, "不知道是太浓还是不喜欢味道。")
    assert result.topics == []
    assert result.review_reason == "uncertain_only_requires_review"


def test_asserted_wins_over_same_topic_uncertain_in_either_order():
    raw = RawFeedbackClassification.model_validate({
        "feedback_id": "a", "repurchase_signal": "none", "topics": [
            {"code": "longevity_diffusion", "sentiment": "negative", "severity": 1,
             "source_span": "可能太浓", "mention_type": "uncertain"},
            {"code": "longevity_diffusion", "sentiment": "negative", "severity": 2,
             "source_span": "两根藤条就很冲", "mention_type": "asserted"},
        ]})
    expected = raw.topics[1].model_dump()
    for topics in [raw.topics, list(reversed(raw.topics))]:
        ordered = raw.model_copy(update={"topics": topics}, deep=True)
        result = filter_topics(ordered, "可能太浓，两根藤条就很冲。")
        assert result.review_reason is None
        assert [topic.model_dump() for topic in result.topics] == [expected]
        assert result.events == [{"feedback_id": "a", "code": "longevity_diffusion",
                                  "reason": "dropped_uncertain_duplicate"}]
