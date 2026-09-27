import json
import logging

from openai import APIStatusError
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from userecho.classification_schema import FeedbackClassification
from userecho.steps.classify import classify, create_client, parse_batch


@pytest.fixture(autouse=True)
def prevent_real_network(monkeypatch):
    monkeypatch.delenv("USERECHO_DEBUG_PROMPT", raising=False)
    def blocked(*args, **kwargs):
        raise AssertionError("Tests must not access the network")
    monkeypatch.setattr("socket.socket.connect", blocked)
    monkeypatch.setattr("socket.create_connection", blocked)


@pytest.fixture
def client():
    return Mock()


def data(size):
    return pd.DataFrame({"feedback_id": [str(i) for i in range(size)],
                         "feedback_text": ["香味使用反馈" for _ in range(size)]})


def item(fid, span="香味使用反馈", **changes):
    value = {"feedback_id": fid, "topics": [
        {"code": "other", "sentiment": "neutral", "severity": None,
         "source_span": span, "mention_type": "asserted"}
    ], "repurchase_signal": "none"}
    value.update(changes)
    return value


def response(entries=None, *, content=None, usage=True):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content=content if content is not None else json.dumps({"results": entries})))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15) if usage else None,
    )


def echo(**kwargs):
    rows = json.loads(kwargs["messages"][1]["content"])["feedback"]
    return response([item(row["feedback_id"], span=row["feedback_text"]) for row in rows])


def test_json_failure_then_success(client):
    client.chat.completions.create.side_effect = [response(content="not json"), response([item("0")])]
    result = classify(data(1), client=client, model="test")
    assert result.call_count == 2
    assert len(result.classifications) == 1
    assert not result.review_items and not result.unprocessed
    assert result.total_tokens == 30 and result.usage_complete
    assert result.elapsed_seconds >= 0


def test_invalid_item_does_not_discard_good_items(client):
    client.chat.completions.create.side_effect = [
        response([item("0"), item("1", topics=[])]),
        response(content="bad json"),
        response([item("0", topics=[]), item("1", topics=[])]),
    ]
    result = classify(data(2), client=client, model="test")
    assert result.call_count == 3
    assert [x.feedback_id for x in result.classifications] == ["0"]
    assert [x["feedback_id"] for x in result.review_items] == ["1"]
    assert not result.unprocessed


def test_successes_accumulate_across_whole_batch_retries(client):
    client.chat.completions.create.side_effect = [
        response([item("0"), item("1", topics=[])]), response([item("1")]),
    ]
    result = classify(data(2), client=client, model="test")
    assert [x.feedback_id for x in result.classifications] == ["0", "1"]
    assert result.call_count == 2
    for call in client.chat.completions.create.call_args_list:
        assert len(json.loads(call.kwargs["messages"][1]["content"])["feedback"]) == 2


def test_call_budget_preserves_partial_results(client):
    def partial(**kwargs):
        rows = json.loads(kwargs["messages"][1]["content"])["feedback"]
        return response([item(rows[0]["feedback_id"])])
    client.chat.completions.create.side_effect = partial
    result = classify(data(200), client=client, model="test")
    assert result.call_count == client.chat.completions.create.call_count == 15
    assert len(result.classifications) == 5
    assert len(result.review_items) == 120
    assert [row["feedback_id"] for row in result.unprocessed] == [str(i) for i in range(125, 200)]
    assert {row["reason"] for row in result.unprocessed} == {"未处理（已达 LLM 调用上限）"}
    assert result.total_tokens == 225


def test_budget_during_batch_before_retry_exhaustion(client):
    counter = 0
    def serve(**kwargs):
        nonlocal counter
        counter += 1
        return echo(**kwargs) if counter <= 14 else response(content="bad")
    client.chat.completions.create.side_effect = serve
    result = classify(data(17), batch_size=1, client=client, model="test")
    assert result.call_count == 15
    assert len(result.classifications) == 14
    assert not result.review_items
    assert [x["feedback_id"] for x in result.unprocessed] == ["14", "15", "16"]


@pytest.mark.parametrize("size,expected", [(1, [1]), (25, [25]), (26, [25, 1]), (50, [25, 25]), (51, [25, 25, 1])])
def test_batch_boundaries_and_normal_results(client, size, expected):
    client.chat.completions.create.side_effect = echo
    result = classify(data(size), client=client, model="test")
    assert result.call_count == len(expected)
    assert all(isinstance(x, FeedbackClassification) for x in result.classifications)
    assert [x.feedback_id for x in result.classifications] == [str(i) for i in range(size)]
    actual = []
    for call in client.chat.completions.create.call_args_list:
        assert call.kwargs["response_format"] == {"type": "json_object"}
        actual.append(len(json.loads(call.kwargs["messages"][1]["content"])["feedback"]))
    assert actual == expected


def test_short_text_still_sent_to_llm(client):
    client.chat.completions.create.side_effect = echo
    frame = data(1)
    frame.loc[0, "feedback_text"] = "好"
    result = classify(frame, client=client, model="test")
    assert result.call_count == 1
    messages = client.chat.completions.create.call_args.kwargs["messages"]
    assert json.loads(messages[1]["content"])["feedback"][0]["feedback_text"] == "好"


def test_api_exceptions_are_chinese_and_usage_not_invented(client):
    client.chat.completions.create.side_effect = ConnectionError("secret credentials")
    result = classify(data(1), client=client, model="test")
    assert result.call_count == 3
    assert len(result.review_items) == 1
    assert "secret" not in str(result)
    assert result.total_tokens == 0 and not result.usage_complete
    assert all(call["total_tokens"] is None for call in result.calls)


def test_missing_usage_is_explicit(client):
    client.chat.completions.create.return_value = response([item("0")], usage=False)
    result = classify(data(1), client=client, model="test")
    assert not result.usage_complete
    assert result.calls[0]["total_tokens"] is None
    assert len(result.classifications) == 1


def test_parse_crops_after_evidence_and_deduplicates_codes():
    topics = [{"code": code, "sentiment": "neutral", "severity": None, "source_span": "香味使用反馈", "mention_type": "asserted"}
              for code in ["service", "logistics", "price_value", "safety_discomfort"]]
    passed, failed, reviews, events = parse_batch(json.dumps({"results": [item("0", topics=topics)]}), {"0": "香味使用反馈"})
    assert not failed
    assert [x.code for x in passed["0"].topics] == ["service", "logistics", "safety_discomfort"]
    topics.append(topics[-1])
    passed, failed, reviews, events = parse_batch(json.dumps({"results": [item("0", topics=topics)]}), {"0": "香味使用反馈"})
    assert passed and not failed
    assert events[0]["reason"] == "dropped_duplicate_topic"


@pytest.mark.parametrize("entries", [[item("wrong")], [item("0"), item("0")], ["invalid item"], []])
def test_bad_ids_or_missing_items_fail(entries):
    passed, failed, reviews, events = parse_batch(json.dumps({"results": entries}), {"0": "香味使用反馈"})
    assert not passed and "0" in failed


def test_configuration_failure_is_reported_without_network():
    with patch("userecho.steps.classify.create_client", side_effect=ValueError("secret")):
        result = classify(data(1))
    assert result.call_count == 0 and result.errors
    assert result.unprocessed[0]["feedback_id"] == "0"
    assert "secret" not in str(result)


def test_create_client_disables_hidden_retries():
    settings = {"LLM_API_KEY": "fake", "LLM_BASE_URL": "https://example.invalid/v1", "LLM_MODEL": "mock"}
    with patch.dict("os.environ", {}, clear=True), patch("userecho.steps.classify.dotenv_values", return_value=settings), patch("userecho.steps.classify.OpenAI") as constructor:
        api, model = create_client()
    assert constructor.call_args.kwargs["max_retries"] == 0
    assert constructor.call_args.kwargs["timeout"] == 30.0
    assert model == "mock" and api is constructor.return_value


def test_empty_or_invalid_input_does_not_call_api(client):
    result = classify(data(0), client=client, model="test")
    assert not result.errors and result.call_count == 0
    for frame, size in [(pd.DataFrame(), 25), (data(1), 0), (pd.concat([data(1), data(1)]), 25)]:
        assert classify(frame, batch_size=size, client=client, model="test").errors
    client.chat.completions.create.assert_not_called()


@pytest.mark.parametrize("flag", [None, "0", "true", "yes"])
def test_default_logs_only_call_metadata(client, monkeypatch, caplog, flag):
    if flag is not None:
        monkeypatch.setenv("USERECHO_DEBUG_PROMPT", flag)
    caplog.set_level(logging.DEBUG)
    frame = data(1)
    frame.loc[0, "feedback_text"] = "私人反馈内容不可打印"
    client.chat.completions.create.side_effect = echo
    with patch("userecho.steps.classify.build_system_prompt", return_value="PRIVATE_SYSTEM_PROMPT"):
        result = classify(frame, client=client, model="test")
    assert len(result.classifications) == 1
    records = [r for r in caplog.records if r.name == "userecho.steps.classify"]
    assert len(records) == 1
    message = records[0].getMessage()
    assert message.startswith("LLM 调用：batch_size=1 call_count=1 model='test' elapsed_seconds=")
    assert message.endswith("prompt_tokens=10 completion_tokens=5 total_tokens=15")
    messages = client.chat.completions.create.call_args.kwargs["messages"]
    for entry in messages:
        assert entry["content"] not in caplog.text
    assert "私人反馈内容不可打印" not in caplog.text
    assert "Prompt" not in caplog.text


def test_explicit_debug_logs_complete_sent_prompt(client, monkeypatch, caplog):
    monkeypatch.setenv("USERECHO_DEBUG_PROMPT", "1")
    monkeypatch.setenv("LLM_API_KEY", "sk-private-test-key")
    client.chat.completions.create.side_effect = echo
    classify(data(1), client=client, model="test")
    messages = client.chat.completions.create.call_args.kwargs["messages"]
    assert json.dumps(messages, ensure_ascii=False, indent=2) in caplog.text
    assert "sk-private-test-key" not in caplog.text


def test_api_status_error_logs_type_and_status_without_secrets(client, caplog):
    secret = "sk-private-test-key"
    request = Mock(url="https://example.invalid/?api_key=" + secret,
                   headers={"Authorization": "Bearer " + secret})
    error = APIStatusError("private response " + secret,
                           response=Mock(status_code=402, request=request, headers={}),
                           body={"message": "private feedback " + secret})
    client.chat.completions.create.side_effect = error
    result = classify(data(1), client=client, model="test")
    assert result.call_count == 1 and len(result.review_items) == 1
    assert caplog.text.count("APIStatusError/402") == 1
    for forbidden in [secret, "private response", "private feedback", "Authorization", "example.invalid", "香味使用反馈"]:
        assert forbidden not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_non_http_error_does_not_log_message_or_invalid_status(client, caplog):
    error = RuntimeError("private credentials")
    error.status_code = "private credentials"
    client.chat.completions.create.side_effect = error
    classify(data(1), client=client, model="test")
    assert caplog.text.count("RuntimeError/未知") == 1
    assert "private credentials" not in caplog.text


def test_temperature_zero_is_sent_for_every_batch_and_retry(client):
    client.chat.completions.create.side_effect = [
        response(content="bad json"), response([item(str(i)) for i in range(25)]),
        response([item("25")]),
    ]
    result = classify(data(26), client=client, model="test")
    assert result.call_count == 3
    assert len(result.classifications) == 26
    for call in client.chat.completions.create.call_args_list:
        assert call.kwargs["temperature"] == 0
        assert set(call.kwargs) == {"model", "messages", "response_format", "temperature"}


def candidate(code, span, kind="asserted", sentiment="negative", severity=2):
    return {"code": code, "source_span": span, "mention_type": kind,
            "sentiment": sentiment, "severity": severity}


def classify_candidates(client, text, topics):
    client.chat.completions.create.return_value = response([item("0", topics=topics)])
    frame = pd.DataFrame([{"feedback_id": "0", "feedback_text": text}])
    return classify(frame, client=client, model="test")


def test_asserted_retains_exact_evidence_and_strips_only_edges(client):
    result = classify_candidates(client, "味道  很好！", [
        candidate("scent_preference", "  味道  很好！  ", sentiment="positive", severity=None)])
    topic = result.classifications[0].topics[0]
    assert topic.source_span == "味道  很好！"
    assert topic.mention_type == "asserted"
    assert result.call_count == 1


@pytest.mark.parametrize("text,topics,expected", [
    ("才插两根藤条就觉得冲，闻着难受，说不清是味道不喜欢还是太浓了。", [
        candidate("longevity_diffusion", "才插两根藤条就觉得冲"),
        candidate("scent_preference", "说不清是味道不喜欢还是太浓了。", "uncertain")], "longevity_diffusion"),
    ("试香纸上明明挺柔和，到衣服上就像洗衣粉，这是味道变了还是我鼻子太挑？", [
        candidate("scent_preference", "到衣服上就像洗衣粉", severity=1),
        candidate("scent_mismatch", "这是味道变了还是我鼻子太挑？", "uncertain")], "scent_preference"),
])
def test_uncertain_alternative_is_removed(client, text, topics, expected):
    result = classify_candidates(client, text, topics)
    assert [t.code for t in result.classifications[0].topics] == [expected]
    assert result.provenance_events[0]["reason"] == "dropped_uncertain_topic"
    assert result.call_count == 1


def test_uncertain_only_is_terminal_review(client):
    result = classify_candidates(client, "不知道是不是太浓", [
        candidate("longevity_diffusion", "不知道是不是太浓", "uncertain")])
    assert not result.classifications
    assert result.review_items == [{"feedback_id": "0", "reason": "uncertain_only_requires_review"}]
    assert result.call_count == 1


def test_non_safety_consultation_becomes_other(client):
    result = classify_candidates(client, "请问多久能送到？", [
        candidate("logistics", "请问多久能送到？", "consultation", "negative", None)])
    topic = result.classifications[0].topics[0]
    assert (topic.code, topic.sentiment, topic.severity) == ("other", "neutral", None)
    assert topic.source_span == "请问多久能送到？" and topic.mention_type == "consultation"
    assert result.call_count == 1 and not result.review_items


def test_non_safety_consultation_dropped_beside_asserted(client):
    result = classify_candidates(client, "瓶子好看，多久送到？", [
        candidate("appearance_usage", "瓶子好看", sentiment="positive", severity=None),
        candidate("logistics", "多久送到？", "consultation")])
    assert [t.code for t in result.classifications[0].topics] == ["appearance_usage"]
    assert result.call_count == 1


@pytest.mark.parametrize("subject", ["儿童", "孕妇", "宠物"])
def test_safety_consultation_forced_neutral_null(client, subject):
    text = subject + "能使用吗？"
    result = classify_candidates(client, text, [candidate("safety_discomfort", text, "consultation", "negative", 3)])
    topic = result.classifications[0].topics[0]
    assert (topic.code, topic.sentiment, topic.severity) == ("safety_discomfort", "neutral", None)
    assert result.call_count == 1 and not result.review_items
    assert "risk_alert" not in topic.model_dump()


@pytest.mark.parametrize("reverse", [False, True])
def test_same_topic_asserted_wins_over_uncertain(client, reverse):
    topics = [candidate("longevity_diffusion", "可能太浓", "uncertain"),
              candidate("longevity_diffusion", "浓得冲", severity=2)]
    if reverse:
        topics.reverse()
    result = classify_candidates(client, "可能太浓，浓得冲", topics)
    assert len(result.classifications[0].topics) == 1
    assert result.classifications[0].topics[0].source_span == "浓得冲"
    assert result.provenance_events[0]["reason"] == "dropped_uncertain_duplicate"
    assert result.call_count == 1


@pytest.mark.parametrize("span", ["不存在的原文", "香味很好,包装漂亮。", "香味很好……", "香味 很好，包装漂亮。", "   "])
def test_source_span_including_slight_punctuation_deviation_requires_review(client, caplog, span):
    text = "香味很好，包装漂亮。"
    result = classify_candidates(client, text, [candidate("scent_preference", span)])
    assert not result.classifications
    assert result.review_items == [{"feedback_id": "0", "reason": "source_span_not_in_feedback"}]
    assert result.call_count == 1
    assert text not in caplog.text
    if span.strip():
        assert span not in caplog.text


def test_invalid_span_checked_even_on_duplicate_or_uncertain(client):
    result = classify_candidates(client, "太浓", [candidate("longevity_diffusion", "太浓"),
        candidate("longevity_diffusion", "错误引用", "uncertain")])
    assert result.review_items[0]["reason"] == "source_span_not_in_feedback"
    assert not result.classifications and result.call_count == 1


def test_evidence_filter_precedes_three_topic_selection(client):
    result = classify_candidates(client, "原文", [
        candidate("safety_discomfort", "原文", "uncertain"),
        candidate("logistics", "原文"), candidate("service", "原文"),
        candidate("appearance_usage", "原文"), candidate("price_value", "原文")])
    assert [t.code for t in result.classifications[0].topics] == ["logistics", "service", "appearance_usage"]
    assert result.call_count == 1


def test_terminal_review_excluded_from_other_items_retry(client):
    client.chat.completions.create.side_effect = [
        response([item("0", topics=[candidate("other", "香味使用反馈", "uncertain")]), item("1", topics=[])]),
        response([item("1")]),
    ]
    result = classify(data(2), client=client, model="test")
    assert result.call_count == 2
    assert [v.feedback_id for v in result.classifications] == ["1"]
    assert len(result.review_items) == 1
    second = client.chat.completions.create.call_args_list[1].kwargs
    assert [v["feedback_id"] for v in json.loads(second["messages"][1]["content"])["feedback"]] == ["1"]


def test_default_log_does_not_include_valid_source_span(client, caplog):
    result = classify_candidates(client, "用户秘密：特殊香调太浓", [candidate("longevity_diffusion", "特殊香调太浓")])
    assert len(result.classifications) == 1
    assert "用户秘密" not in caplog.text and "特殊香调太浓" not in caplog.text


def test_final_sentiment_constraint_is_checked_after_consultation_conversion(client):
    result = classify_candidates(client, "孩子能用吗", [candidate("safety_discomfort", "孩子能用吗", "consultation", "neutral", 3)])
    assert result.classifications[0].topics[0].severity is None
    assert result.call_count == 1


def test_asserted_invalid_sentiment_severity_retries(client):
    result = classify_candidates(client, "香味使用反馈", [candidate("other", "香味使用反馈", "asserted", "neutral", 3)])
    assert result.call_count == 3
    assert result.review_items and not result.classifications


@pytest.mark.parametrize("status", [408, 409, 429, 500, 503])
def test_temporary_http_errors_retry(client, status):
    error = APIStatusError("private", response=Mock(status_code=status, request=Mock(), headers={}), body=None)
    client.chat.completions.create.side_effect = [error, response([item("0")])]
    result = classify(data(1), client=client, model="test")
    assert result.call_count == 2 and len(result.classifications) == 1


def test_semantic_review_does_not_interrupt_successful_sibling(client):
    client.chat.completions.create.return_value = response([
        item("0", topics=[candidate("other", "不在原文")]), item("1")])
    result = classify(data(2), client=client, model="test")
    assert result.call_count == 1
    assert [v.feedback_id for v in result.classifications] == ["1"]
    assert result.review_items[0]["reason"] == "source_span_not_in_feedback"


def test_uncertain_safety_does_not_displace_trusted_topics(client):
    result = classify_candidates(client, "原文", [
        candidate("service", "原文"), candidate("logistics", "原文"),
        candidate("price_value", "原文"), candidate("safety_discomfort", "原文", "uncertain")])
    assert [t.code for t in result.classifications[0].topics] == ["service", "logistics", "price_value"]


def test_uncertain_with_safety_consultation_keeps_only_consultation(client):
    result = classify_candidates(client, "原文", [candidate("scent_mismatch", "原文", "uncertain"),
        candidate("safety_discomfort", "原文", "consultation")])
    assert [t.code for t in result.classifications[0].topics] == ["safety_discomfort"]
    assert result.call_count == 1


def test_final_cross_field_constraints_follow_cropping(client):
    result = classify_candidates(client, "原文", [
        candidate("service", "原文"), candidate("logistics", "原文"),
        candidate("price_value", "原文"), candidate("appearance_usage", "原文", sentiment="neutral", severity=3)])
    assert result.call_count == 1 and len(result.classifications[0].topics) == 3


@pytest.mark.parametrize("exhausted", [False, True])
def test_owned_client_retry_count_matches_sdk_calls_without_internal_retries(exhausted):
    settings = {"LLM_API_KEY": "fake", "LLM_BASE_URL": "https://example.invalid/v1",
                "LLM_MODEL": "mock"}
    with patch.dict("os.environ", {}, clear=True), patch(
        "userecho.steps.classify.dotenv_values", return_value=settings
    ), patch("userecho.steps.classify.OpenAI") as constructor:
        api = constructor.return_value
        if exhausted:
            api.chat.completions.create.side_effect = ConnectionError("temporary")
        else:
            api.chat.completions.create.side_effect = [
                ConnectionError("temporary"), response([item("0")]),
            ]
        result = classify(data(1))
    constructor.assert_called_once()
    assert constructor.call_args.kwargs["max_retries"] == 0
    assert result.call_count == api.chat.completions.create.call_count == (3 if exhausted else 2)
    assert [call["attempt"] for call in result.calls] == list(range(1, result.call_count + 1))
    assert len(result.classifications) == (0 if exhausted else 1)
    assert len(result.review_items) == (1 if exhausted else 0)
    assert not result.unprocessed
    api.close.assert_called_once()
