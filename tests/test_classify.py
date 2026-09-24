import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from userecho.classification_schema import FeedbackClassification
from userecho.steps.classify import classify, create_client, parse_batch


@pytest.fixture(autouse=True)
def prevent_real_network(monkeypatch):
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


def item(fid, **changes):
    value = {"feedback_id": fid, "topics": [
        {"code": "other", "sentiment": "neutral", "severity": None}
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
    return response([item(row["feedback_id"]) for row in rows])


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
    with patch("userecho.steps.classify.LOGGER.debug") as debug:
        result = classify(data(size), client=client, model="test")
    assert result.call_count == len(expected)
    assert all(isinstance(x, FeedbackClassification) for x in result.classifications)
    assert [x.feedback_id for x in result.classifications] == [str(i) for i in range(size)]
    actual = []
    for call, log_call in zip(client.chat.completions.create.call_args_list, debug.call_args_list):
        assert call.kwargs["response_format"] == {"type": "json_object"}
        assert json.loads(log_call.args[-1]) == call.kwargs["messages"]
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
    client.chat.completions.create.side_effect = RuntimeError("secret credentials")
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


def test_parse_crops_after_validation_and_rejects_duplicate_codes():
    topics = [{"code": code, "sentiment": "neutral", "severity": None}
              for code in ["service", "logistics", "price_value", "safety_discomfort"]]
    passed, failed = parse_batch(json.dumps({"results": [item("0", topics=topics)]}), ["0"])
    assert not failed
    assert [x.code for x in passed["0"].topics] == ["service", "logistics", "safety_discomfort"]
    topics.append(topics[-1])
    passed, failed = parse_batch(json.dumps({"results": [item("0", topics=topics)]}), ["0"])
    assert not passed and "0" in failed


@pytest.mark.parametrize("entries", [[item("wrong")], [item("0"), item("0")], ["invalid item"], []])
def test_bad_ids_or_missing_items_fail(entries):
    passed, failed = parse_batch(json.dumps({"results": entries}), ["0"])
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
