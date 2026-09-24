"""Strict classification output models; no LLM calls or derived risk fields."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


TopicCode = Literal[
    "scent_mismatch", "scent_preference", "longevity_diffusion",
    "packaging_leak", "safety_discomfort", "price_value", "logistics",
    "appearance_usage", "service", "other",
]
Sentiment = Literal["positive", "negative", "neutral", "mixed"]
RepurchaseSignal = Literal["positive", "negative", "conditional", "none"]
Severity = Annotated[int, Field(strict=True, ge=1, le=3)]


class TopicAnnotation(BaseModel):
    """One topic with a required, sentiment-dependent severity value."""

    model_config = ConfigDict(extra="forbid", strict=True)

    code: TopicCode
    sentiment: Sentiment
    severity: Severity | None

    @model_validator(mode="after")
    def validate_severity(self) -> Self:
        if self.sentiment in {"positive", "neutral"}:
            if self.severity is not None:
                raise ValueError("Positive and neutral sentiments require null severity")
        elif self.severity is None:
            raise ValueError("Negative and mixed sentiments require severity 1, 2 or 3")
        return self


class RawFeedbackClassification(BaseModel):
    """Validate every recognized topic before deterministic selection."""

    model_config = ConfigDict(extra="forbid", strict=True)

    feedback_id: str
    topics: list[TopicAnnotation] = Field(min_length=1, max_length=10)
    repurchase_signal: RepurchaseSignal

    @model_validator(mode="after")
    def validate_unique_codes(self) -> Self:
        codes = [topic.code for topic in self.topics]
        if len(codes) != len(set(codes)):
            raise ValueError("Topic codes must be unique within one feedback")
        return self


class FeedbackClassification(RawFeedbackClassification):
    """Public classification after selection, with at most three topics."""

    topics: list[TopicAnnotation] = Field(min_length=1, max_length=3)
