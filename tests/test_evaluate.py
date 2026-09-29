"""Evaluation tests use synthetic files and never access frozen data or APIs."""

import hashlib
import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from scripts import evaluate


def topic(code='price_value', sentiment='negative', severity=2):
    return dict(code=code, sentiment=sentiment, severity=severity)


def result(predictions=None, reviews=(), unprocessed=()):
    return SimpleNamespace(
        classifications=[SimpleNamespace(feedback_id=fid,
                         topics=[SimpleNamespace(**t) for t in topics])
                         for fid, topics in (predictions or {}).items()],
        review_items=[{'feedback_id': fid, 'reason': 'private reason'} for fid in reviews],
        unprocessed=[{'feedback_id': fid} for fid in unprocessed],
        call_count=1, total_tokens=99, elapsed_seconds=0.5,
    )


@pytest.fixture
def frozen_files(tmp_path):
    data = tmp_path / 'input.csv'
    labels = tmp_path / 'labels.csv'
    checksum = tmp_path / 'CHECKSUM.sha256'
    pd.DataFrame([{'feedback_id': 'R001_P1', 'feedback_text': '合成测试原文不应出现在报告'}]).to_csv(data, index=False)
    row = {'feedback_id': 'R001_P1'}
    for i in range(1, 4):
        row.update({f'topic_{i}': 'price_value' if i == 1 else '',
                    f'sentiment_{i}': 'negative' if i == 1 else '',
                    f'severity_{i}': '2' if i == 1 else ''})
    pd.DataFrame([row]).to_csv(labels, index=False)
    checksum.write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n'
                                for p in (data, labels)))
    return data, labels, checksum


@pytest.mark.parametrize('index', [0, 1])
def test_checksum_failure_never_calls_model(frozen_files, monkeypatch, index):
    frozen_files[index].write_bytes(b'changed')
    model = Mock()
    monkeypatch.setattr(evaluate, 'classify', model)
    with pytest.raises(evaluate.EvaluationError, match='SHA-256 校验失败'):
        evaluate.run_evaluation(*frozen_files, expected_size=1)
    model.assert_not_called()


def test_multilabel_micro_f1_uses_sets():
    gold = {'a': [topic('price_value'), topic('logistics')], 'b': [topic('service')]}
    output = result({'a': [topic('logistics'), topic('appearance_usage')],
                     'b': [topic('service')]})
    summary = evaluate.summarize(gold, output)
    assert (summary['TP'], summary['FP'], summary['FN']) == (2, 1, 1)
    assert summary['topic_micro_f1'] == pytest.approx(2 / 3)
    reordered = result({'a': [topic('appearance_usage'), topic('logistics')],
                        'b': [topic('service')]})
    assert evaluate.summarize(gold, reordered) == summary


def test_semantic_reviews_are_empty_predictions_in_denominator():
    summary = evaluate.summarize({fid: [topic()] for fid in ('a', 'b', 'c')},
                                 result({'a': [topic()]}, reviews=['b', 'c']))
    assert (summary['TP'], summary['FP'], summary['FN']) == (1, 0, 2)
    assert summary['topic_micro_f1'] == 0.5
    assert sum(summary[k] for k in ('classifications', 'review_items', 'unprocessed')) == 3
    assert [d['predicted_topics'] for d in summary['differences']] == [[], []]


def test_high_risk_is_counted_once_per_feedback():
    gold = {
        'a': [topic('safety_discomfort', 'mixed', 3), topic('packaging_leak', severity=3)],
        'b': [topic('safety_discomfort', severity=1)],
        'c': [topic('price_value', severity=3)],
        'd': [topic('safety_discomfort', 'neutral', None)],
    }
    summary = evaluate.summarize(gold, result({'a': [topic('packaging_leak', severity=3)],
                                              'd': [topic('safety_discomfort', 'neutral', None)]},
                                             reviews=['b', 'c']))
    assert summary['high_risk_numerator'] == 1
    assert summary['high_risk_denominator'] == 3
    assert summary['high_risk_recall'] == pytest.approx(1 / 3)


def test_no_gold_risk_is_na_even_with_false_positive_risk():
    summary = evaluate.summarize({'a': [topic('safety_discomfort', 'neutral', None)]},
                                 result({'a': [topic('safety_discomfort', severity=3)]}))
    assert summary['high_risk_recall'] == 'N/A'
    assert summary['system_high_risk_count'] == 1
    assert summary['high_risk_denominator'] == 0
    assert summary['evidence_support_rate'] == evaluate.EVIDENCE


@pytest.mark.parametrize('output', [
    result(), result({'extra': [topic()]}),
    result({'a': [topic()]}, reviews=['a']), result(reviews=['a', 'a']),
])
def test_bucket_conservation_requires_exact_exclusive_ids(output):
    with pytest.raises(evaluate.EvaluationError, match='结果桶不守恒'):
        evaluate.summarize({'a': [topic()]}, output)


def test_report_allowlist_excludes_all_original_content(frozen_files, monkeypatch):
    output = result({'R001_P1': [topic('logistics')]})
    output.classifications[0].topics[0].source_span = '合成测试原文'
    output.errors = ['API key secret']
    monkeypatch.setattr(evaluate, 'classify', Mock(return_value=output))
    summary = evaluate.run_evaluation(*frozen_files, expected_size=1)
    serialized = json.dumps(summary, ensure_ascii=False)
    for forbidden in ('"feedback_text"', '"source_span"', '合成测试原文', 'secret', 'Prompt 内容'):
        assert forbidden not in serialized
    assert set(summary['differences'][0]) == {
        'feedback_id', 'gold_topics', 'predicted_topics', 'result_bucket'}
    assert summary['statement'] == evaluate.DISCLAIMER
    assert (summary['call_count'], summary['total_tokens'], summary['elapsed_seconds']) == (1, 99, .5)


def test_debug_logging_is_disabled_during_model_call_and_restored(frozen_files, monkeypatch, caplog):
    monkeypatch.setenv('USERECHO_DEBUG_PROMPT', '1')
    old_disable = logging.root.manager.disable

    def model(frame, **kwargs):
        assert evaluate.os.environ.get('USERECHO_DEBUG_PROMPT') != '1'
        logging.getLogger('openai').critical('private prompt')
        return result({'R001_P1': [topic()]})

    monkeypatch.setattr(evaluate, 'classify', model)
    evaluate.run_evaluation(*frozen_files, expected_size=1)
    assert 'private prompt' not in caplog.text
    assert evaluate.os.environ['USERECHO_DEBUG_PROMPT'] == '1'
    assert logging.root.manager.disable == old_disable


def test_misaligned_labels_stop_before_model(frozen_files, monkeypatch):
    data, labels, checksum = frozen_files
    labels.write_text(labels.read_text().replace('R001_P1', 'R999_P1'))
    checksum.write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n'
                                for p in (data, labels)))
    model = Mock()
    monkeypatch.setattr(evaluate, 'classify', model)
    with pytest.raises(evaluate.EvaluationError, match='ID 对齐'):
        evaluate.run_evaluation(*frozen_files, expected_size=1)
    model.assert_not_called()


@pytest.fixture(autouse=True)
def offline_configuration(monkeypatch):
    monkeypatch.setattr(evaluate, 'build_system_prompt', Mock(return_value='synthetic'))
    monkeypatch.setattr(evaluate, 'create_client', Mock(return_value=(Mock(), 'test')))
    def blocked(*args, **kwargs):
        raise AssertionError('Network is forbidden in evaluation tests')
    monkeypatch.setattr('socket.socket.connect', blocked)
    monkeypatch.setattr('socket.create_connection', blocked)


@pytest.mark.parametrize('reason', [
    'LLM 调用失败或响应异常，请稍后重试。', 'API 鉴权失败', '网络失败',
    '余额不足', '配置失败', '客户端初始化失败',
])
@pytest.mark.parametrize('partial', [False, True])
def test_final_infrastructure_failure_invalid(reason, partial):
    output = result({'a': [topic()]} if partial else {}, reviews=['b'] if partial else ['a', 'b'])
    for item in output.review_items:
        item['reason'] = reason
    with pytest.raises(evaluate.EvaluationError, match='基础设施失败'):
        evaluate.summarize({'a': [topic()], 'b': [topic()]}, output)


@pytest.mark.parametrize('reason', [
    'uncertain_only_requires_review', 'source_span_not_in_feedback',
    '分类失败：字段、主题或严重度未通过校验。',
    '分类失败：返回内容不是规定的 JSON 结构。', 'other_semantic_review',
])
def test_semantic_review_remains_valid(reason):
    output = result(reviews=['a'])
    output.review_items[0]['reason'] = reason
    output.errors = ['historical API failure']
    summary = evaluate.summarize({'a': [topic()]}, output)
    assert summary['topic_micro_f1'] == 0
    assert summary['FN'] == 1


def test_unprocessed_invalid():
    with pytest.raises(evaluate.EvaluationError, match='未处理反馈'):
        evaluate.summarize({'a': [topic()]}, result(unprocessed=['a']))


@pytest.mark.parametrize('function', ['create_client', 'build_system_prompt'])
def test_configuration_failure_before_api(frozen_files, monkeypatch, tmp_path, function):
    monkeypatch.setattr(evaluate, function, Mock(side_effect=ValueError('private credential')))
    model = Mock()
    monkeypatch.setattr(evaluate, 'classify', model)
    output = tmp_path / 'report.json'
    with pytest.raises(evaluate.EvaluationError, match='配置校验或客户端初始化失败'):
        evaluate.run_evaluation(*frozen_files, expected_size=1, output=output)
    model.assert_not_called()
    assert not output.exists()


def test_existing_output_stops_before_api(frozen_files, monkeypatch, tmp_path):
    output = tmp_path / 'report.json'
    output.write_text('original')
    model = Mock()
    monkeypatch.setattr(evaluate, 'classify', model)
    with pytest.raises(evaluate.EvaluationError, match='输出文件已存在'):
        evaluate.run_evaluation(*frozen_files, expected_size=1, output=output)
    model.assert_not_called()
    evaluate.create_client.assert_not_called()
    assert output.read_text() == 'original'


def test_atomic_publish_does_not_overwrite(tmp_path):
    output = tmp_path / 'report.json'
    output.write_text('original')
    with pytest.raises(evaluate.EvaluationError, match='拒绝覆盖'):
        evaluate.save_summary(output, 'new')
    assert output.read_text() == 'original'
    assert list(tmp_path.iterdir()) == [output]


def test_invalid_cli_no_metrics_or_file(frozen_files, monkeypatch, tmp_path, capsys):
    output = tmp_path / 'report.json'
    failed = result(reviews=['R001_P1'])
    failed.review_items[0]['reason'] = 'LLM 调用失败或响应异常，请稍后重试。'
    monkeypatch.setattr(evaluate, 'classify', Mock(return_value=failed))
    original = evaluate.run_evaluation
    def synthetic_run(*args, **kwargs):
        return original(*frozen_files, expected_size=1, output=kwargs['output'])
    monkeypatch.setattr(evaluate, 'run_evaluation', synthetic_run)
    monkeypatch.setattr('sys.argv', ['evaluate', '--output', str(output)])
    assert evaluate.main() == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert '评测运行无效' in captured.err
    assert not output.exists()


def test_retry_recovery_with_real_classifier(frozen_files, monkeypatch):
    from userecho.steps.classify import classify
    client = Mock()
    entry = dict(feedback_id='R001_P1', topics=[dict(
        **topic(), source_span='合成测试原文', mention_type='asserted')], repurchase_signal='none')
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content=json.dumps({'results': [entry]})))], usage=None)
    client.chat.completions.create.side_effect = [ConnectionError('private'), response]
    monkeypatch.setattr(evaluate, 'create_client', Mock(return_value=(client, 'test')))
    def model(*args, **kwargs):
        output = classify(*args, **kwargs)
        output.errors.append('historical API error')
        return output
    monkeypatch.setattr(evaluate, 'classify', model)
    summary = evaluate.run_evaluation(*frozen_files, expected_size=1)
    assert summary['topic_micro_f1'] == 1
    assert summary['call_count'] == 2
    client.close.assert_called_once()


def test_real_classifier_exhausted_network_failure(frozen_files, monkeypatch, tmp_path):
    from userecho.steps.classify import classify
    client = Mock()
    client.chat.completions.create.side_effect = ConnectionError('private')
    monkeypatch.setattr(evaluate, 'create_client', Mock(return_value=(client, 'test')))
    monkeypatch.setattr(evaluate, 'classify', classify)
    output = tmp_path / 'report.json'
    with pytest.raises(evaluate.EvaluationError, match='基础设施失败'):
        evaluate.run_evaluation(*frozen_files, expected_size=1, output=output)
    assert client.chat.completions.create.call_count == 3
    assert not output.exists()


def test_system_risk_counts_feedback_once():
    output = result({'a': [topic('safety_discomfort', severity=3), topic('packaging_leak', severity=3)],
                     'b': [topic('safety_discomfort', severity=1)], 'c': [topic()]})
    summary = evaluate.summarize({fid: [topic()] for fid in ('a', 'b', 'c')}, output)
    assert summary['system_high_risk_count'] == 2
    assert summary['high_risk_recall'] == 'N/A'
