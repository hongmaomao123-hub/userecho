import io
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from userecho.steps.data_check import data_check


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def test_upload_page_initial_state():
    app = AppTest.from_file(str(APP_PATH)).run()
    assert not app.exception
    assert app.title[0].value == "UserEcho 用户反馈检查"
    assert app.selectbox[0].options == ["满意度分析", "主要抱怨", "复购相关"]
    assert not app.dataframe


@pytest.mark.parametrize("size,label", [
    (0, "无法分析"), (1, "仅数据概览"),
    (5, "探索性分析"), (31, "标准分析"), (201, "标准分析"), (251, "标准分析"),
])
def test_uploaded_csv_results_and_preview(size, label):
    raw = "feedback_id,feedback_text\n" + "".join(
        f"{i},香味非常好闻{i}\n" for i in range(size)
    )
    with patch("streamlit.file_uploader", return_value=io.BytesIO(raw.encode("utf-8"))):
        app = AppTest.from_file(str(APP_PATH)).run()
    assert not app.exception
    cleaned, report = data_check(raw.encode("utf-8"))
    assert len(cleaned) == report["valid_sample_size"] == min(size, 200)
    assert [metric.label for metric in app.metric] == ["原始反馈数", "本次处理反馈数"]
    assert [metric.value for metric in app.metric] == [str(size), str(len(cleaned))]
    if size > 200:
        assert any(
            f"{size} 条有效反馈" in item.value
            and "本次实际处理 200 条" in item.value
            and f"{size - 200} 条未处理" in item.value
            and "原始排序影响" in item.value
            for item in app.warning
        )
    assert any(label in element.value for element in app.markdown)
    assert len(app.dataframe[0].value) == min(size, 10)
    assert bool(app.error) == (size == 0)
    if size == 5:
        assert any(item.value == "小样本，仅供探索" for item in app.warning)


def test_malformed_upload_shows_chinese_error():
    with patch("streamlit.file_uploader", return_value=io.BytesIO(b'feedback_id,feedback_text\n1,"broken')):
        app = AppTest.from_file(str(APP_PATH)).run()
    assert not app.exception
    assert "CSV 格式损坏" in app.error[0].value


@pytest.mark.parametrize("raw,message", [
    (b"", "CSV 文件为空"),
    (b"\xff", "文件编码无法识别"),
])
def test_empty_or_undecodable_upload_shows_chinese_error(raw, message):
    with patch("streamlit.file_uploader", return_value=io.BytesIO(raw)):
        app = AppTest.from_file(str(APP_PATH)).run()
    assert not app.exception
    assert message in app.error[0].value
    assert [metric.value for metric in app.metric] == ["0", "0"]
    assert app.dataframe[0].value.empty


@pytest.mark.parametrize("missing", [None, float("nan")])
def test_rating_preview_formats_missing_without_mutating_data(missing):
    raw = "feedback_id,feedback_text,rating\n1,香味非常好闻,5\n2,包装非常完整,\n".encode("utf-8")
    cleaned, report = data_check(raw)
    cleaned["rating"] = pd.Series([5.0, missing], dtype=object)
    original_df = cleaned.copy(deep=True)
    original_report = deepcopy(report)
    with patch("streamlit.file_uploader", return_value=io.BytesIO(raw)), patch(
        "userecho.steps.data_check.data_check", return_value=(cleaned, report)
    ):
        app = AppTest.from_file(str(APP_PATH)).run()
    assert not app.exception
    assert app.dataframe[0].value["rating"].tolist() == ["5", "—"]
    pd.testing.assert_frame_equal(cleaned, original_df)
    assert report == original_report
    assert report["rating_distribution"] == {"5": 1}
    assert app.table[1].value.to_dict("records") == [{"评分": "5", "反馈数": 1}]


from userecho.classification_schema import FeedbackClassification
from userecho.steps.classify import ClassificationResult


@pytest.fixture(autouse=True)
def prevent_page_tests_from_using_real_api():
    with patch('userecho.steps.classify.create_client', side_effect=AssertionError('No real API in page tests')):
        yield


def upload_bytes(size):
    return io.BytesIO(('feedback_id,feedback_text\n' + ''.join(f'{i},反馈原文\n' for i in range(size))).encode())


def classified(fid, code='longevity_diffusion', severity=1):
    return FeedbackClassification(feedback_id=str(fid), topics=[{
        'code': code, 'sentiment': 'negative', 'severity': severity,
        'source_span': '反馈原文', 'mention_type': 'asserted',
    }], repurchase_signal='none')


def test_insufficient_data_disables_formal_analysis():
    with patch('streamlit.file_uploader', return_value=upload_bytes(4)), patch('userecho.steps.classify.classify') as classify_mock:
        app = AppTest.from_file(str(APP_PATH)).run()
        assert not app.exception and app.button[0].disabled
        assert any('样本量不足，仅展示主题统计' in i.value for i in app.info)
        classify_mock.assert_not_called()


def test_classification_success_displays_topic_summary():
    result = ClassificationResult(classifications=[classified(i) for i in range(5)])
    with patch('streamlit.file_uploader', return_value=upload_bytes(5)), patch('userecho.steps.classify.classify', return_value=result) as classify_mock:
        app = AppTest.from_file(str(APP_PATH)).run()
        app.button[0].click().run()
        assert not app.exception
        assert any(s.value == '主题统计' for s in app.subheader)
        table = next(d.value for d in app.dataframe if '主题代码' in d.value.columns)
        assert table.iloc[0]['负向提及数（含正负并存）'] == 5
        assert table.iloc[0]['主题代码'] == 'longevity_diffusion'
        classify_mock.assert_called_once()


def test_risk_alert_and_review_items_are_visible():
    result = ClassificationResult(classifications=[classified(0, 'safety_discomfort', 3)],
        review_items=[{'feedback_id':'1', 'reason':'source_span_not_in_feedback'}])
    with patch('streamlit.file_uploader', return_value=upload_bytes(5)), patch('userecho.steps.classify.classify', return_value=result):
        app = AppTest.from_file(str(APP_PATH)).run()
        app.button[0].click().run()
        assert not app.exception
        assert {'风险警报', '分类人工复核清单', '主题人工复核清单'} <= {s.value for s in app.subheader}
        assert any('需人工核实' in w.value for w in app.warning)
        reviews = next(d.value for d in app.dataframe if '复核原因' in d.value.columns)
        assert reviews.iloc[0]['复核原因'] == 'source_span_not_in_feedback'


def test_api_failure_is_chinese_without_page_crash():
    result = ClassificationResult(errors=['LLM 调用失败，请稍后重试。'])
    with patch('streamlit.file_uploader', return_value=upload_bytes(5)), patch('userecho.steps.classify.classify', return_value=result):
        app = AppTest.from_file(str(APP_PATH)).run()
        app.button[0].click().run()
        assert not app.exception
        assert any('LLM 调用失败' in e.value for e in app.error)
