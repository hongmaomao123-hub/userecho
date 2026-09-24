import pytest

from userecho.classification_schema import TopicAnnotation
from userecho.steps.topic_selection import select_topics


@pytest.mark.parametrize("codes,expected", [
    (["service", "logistics", "price_value"], ["service", "logistics", "price_value"]),
    (["service", "logistics", "price_value", "appearance_usage"], ["service", "logistics", "price_value"]),
    (["service", "logistics", "price_value", "safety_discomfort"], ["service", "logistics", "safety_discomfort"]),
    (["safety_discomfort", "service", "logistics", "price_value"], ["safety_discomfort", "service", "logistics"]),
    (["service", "logistics", "price_value", "safety_discomfort", "safety_discomfort"], ["service", "logistics", "safety_discomfort"]),
    (["other"], ["other"]),
])
def test_selection_and_input_isolation(codes, expected):
    topics = [TopicAnnotation(code=code, sentiment="negative", severity=1 if i < 4 else 3)
              for i, code in enumerate(codes)]
    before = [topic.model_dump() for topic in topics]
    selected = select_topics(topics)
    assert [topic.code for topic in selected] == expected
    assert [topic.model_dump() for topic in topics] == before
    if len(codes) == 5:
        assert selected[2].severity == 1
    selected[0].severity = 2
    assert [topic.model_dump() for topic in topics] == before


def test_empty_topics_fail():
    with pytest.raises(ValueError, match="分类失败"):
        select_topics([])
