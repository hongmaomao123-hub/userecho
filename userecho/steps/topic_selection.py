"""Deterministic, network-free selection of classified topics."""

from userecho.classification_schema import TopicAnnotation


def select_topics(topics: list[TopicAnnotation]) -> list[TopicAnnotation]:
    """Keep the first three, replacing the third with the first later safety item.

    Raw model validation rejects duplicate codes before this function is used
    in classification. The function independently handles repeated safety items
    so its selection rule remains deterministic for any nonempty topic list.
    Return copies to avoid sharing mutable model instances with the input.
    """
    if not topics:
        raise ValueError("分类失败：未返回任何主题。")
    selected = topics[:3]
    if len(topics) > 3 and not any(t.code == "safety_discomfort" for t in selected):
        for topic in topics[3:]:
            if topic.code == "safety_discomfort":
                selected[2] = topic
                break
    return [topic.model_copy(deep=True) for topic in selected]
