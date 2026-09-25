"""Exact evidence checks and deterministic candidate filtering; no API calls."""

from dataclasses import dataclass, field

from userecho.classification_schema import CandidateTopic, RawFeedbackClassification
from userecho.steps.topic_selection import select_topics


@dataclass
class ProvenanceResult:
    topics: list[CandidateTopic] = field(default_factory=list)
    review_reason: str | None = None
    events: list[dict[str, str]] = field(default_factory=list)


def filter_topics(raw: RawFeedbackClassification, feedback_text: str) -> ProvenanceResult:
    """Validate every span before deduplication, filtering and slot selection."""
    result = ProvenanceResult()
    topics = [t.model_copy(deep=True) for t in raw.topics]
    for topic in topics:
        topic.source_span = topic.source_span.strip()
        if not topic.source_span or topic.source_span not in feedback_text:
            result.review_reason = "source_span_not_in_feedback"
            return result

    def event(topic: CandidateTopic, reason: str) -> None:
        result.events.append({"feedback_id": raw.feedback_id, "code": topic.code, "reason": reason})

    # Preserve the retained candidate's original position. For equal mention
    # types, retain the first occurrence, without inventing a merged annotation.
    rank = {"asserted": 0, "consultation": 1, "uncertain": 2}
    winners: dict[str, int] = {}
    asserted_codes = {t.code for t in topics if t.mention_type == "asserted"}
    for i, topic in enumerate(topics):
        previous = winners.get(topic.code)
        if previous is None or rank[topic.mention_type] < rank[topics[previous].mention_type]:
            winners[topic.code] = i
    deduped = []
    for i, topic in enumerate(topics):
        if winners[topic.code] == i:
            deduped.append(topic)
        else:
            reason = ("dropped_uncertain_duplicate" if topic.mention_type == "uncertain"
                      and topic.code in asserted_codes else "dropped_duplicate_topic")
            event(topic, reason)

    if all(t.mention_type == "uncertain" for t in deduped):
        result.review_reason = "uncertain_only_requires_review"
        return result
    retained = []
    consultations = []
    for topic in deduped:
        if topic.mention_type == "uncertain":
            event(topic, "dropped_uncertain_topic")
        elif topic.mention_type == "consultation":
            if topic.code == "safety_discomfort":
                topic.sentiment, topic.severity = "neutral", None
                retained.append(topic)
            else:
                consultations.append(topic)
                event(topic, "dropped_non_safety_consultation")
        else:
            retained.append(topic)
    if not retained and consultations:
        topic = consultations[0].model_copy(deep=True)
        topic.code, topic.sentiment, topic.severity = "other", "neutral", None
        retained.append(topic)
        event(topic, "converted_consultation_to_other")
    result.topics = select_topics(retained)
    return result
