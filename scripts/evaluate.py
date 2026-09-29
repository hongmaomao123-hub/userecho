"""Evaluate frozen labels without exposing feedback or model evidence."""

import argparse
from contextlib import contextmanager
import hashlib
from io import BytesIO
import json
import logging
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import get_args

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from userecho.classification_schema import TopicCode
from userecho.steps.classify import classify, create_client
from userecho.classification_prompt import build_system_prompt

CODES = set(get_args(TopicCode))
EVIDENCE = ('N/A：结论级 evidence.py 尚未实现；现有 source_span 是进入最终分类前的硬校验，'
            '不等同于报告结论的 Evidence Support Rate。')
DISCLAIMER = 'n=13，仅用于小样本工作流可行性验证，不代表生产环境表现。'


class EvaluationError(ValueError):
    """A safe, user-facing evaluation error."""


def verified_bytes(data_path, labels_path, checksum_path):
    """Return precisely the bytes verified, before parsing or calling the model."""
    paths = [Path(data_path).resolve(), Path(labels_path).resolve()]
    checksum_path = Path(checksum_path).resolve()
    try:
        entries = []
        for line in checksum_path.read_text(encoding='utf-8-sig').splitlines():
            if not line.strip():
                continue
            match = re.fullmatch(r'([0-9a-fA-F]{64})\s+\*?(.+)', line)
            if not match:
                raise EvaluationError('校验清单格式无效，评测已停止，未调用模型。')
            entries.append((match[1].lower(), match[2]))
        verified = []
        for path in paths:
            hashes = [digest for digest, name in entries
                      if path in {(checksum_path.parent / name).resolve(),
                                  (ROOT / name).resolve()}]
            if len(hashes) != 1:
                raise EvaluationError('校验清单缺少文件或存在重复记录，评测已停止，未调用模型。')
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != hashes[0]:
                raise EvaluationError('文件 SHA-256 校验失败，评测已停止，未调用模型。')
            verified.append(content)
        return verified
    except OSError:
        raise EvaluationError('无法读取评测文件或校验清单，未调用模型。') from None
    except UnicodeError:
        raise EvaluationError('校验清单编码无效，未调用模型。') from None


def load_inputs(data_bytes, label_bytes, expected_size=13):
    """Validate alignment and the three manual annotation groups."""
    try:
        data = pd.read_csv(BytesIO(data_bytes), encoding='utf-8-sig', dtype=str,
                           keep_default_na=False)
        labels = pd.read_csv(BytesIO(label_bytes), encoding='utf-8-sig', dtype=str,
                             keep_default_na=False)
        for frame in (data, labels):
            if 'feedback_id' not in frame or frame.feedback_id.str.strip().eq('').any():
                raise ValueError
            if frame.feedback_id.duplicated().any():
                raise ValueError
        if len(data) != expected_size or set(data.feedback_id) != set(labels.feedback_id):
            raise ValueError
        if data.feedback_text.str.strip().eq('').any():
            raise ValueError
        gold = {}
        for row in labels.to_dict('records'):
            topics = []
            for index in range(1, 4):
                code, sentiment, severity = [row[f'{field}_{index}'].strip()
                                             for field in ('topic', 'sentiment', 'severity')]
                if not code:
                    if sentiment or severity:
                        raise ValueError
                    continue
                if code not in CODES or sentiment not in {'positive', 'negative', 'neutral', 'mixed'}:
                    raise ValueError
                level = None if severity in {'', 'null'} else int(severity)
                if sentiment in {'positive', 'neutral'}:
                    if level is not None:
                        raise ValueError
                elif level not in {1, 2, 3}:
                    raise ValueError
                topics.append({'code': code, 'sentiment': sentiment, 'severity': level})
            if not topics or len({t['code'] for t in topics}) != len(topics):
                raise ValueError
            gold[row['feedback_id']] = topics
        return data[['feedback_id', 'feedback_text']], gold
    except (ValueError, KeyError, AttributeError, UnicodeError):
        raise EvaluationError('评测 CSV 结构、标签或 ID 对齐校验失败，未调用模型。') from None


def high_risk(topics):
    return any(t['severity'] == 3 or (t['code'] == 'safety_discomfort'
               and t['sentiment'] in {'negative', 'mixed'}) for t in topics)


def summarize(gold, result):
    """Score valid runs; semantic reviews contribute empty predictions."""
    buckets = {}
    predictions = {}
    for item in result.classifications:
        fid = item.feedback_id
        if fid in buckets:
            raise EvaluationError('评测运行无效：结果桶不守恒：反馈重复。')
        buckets[fid] = 'classifications'
        predictions[fid] = [{'code': t.code, 'sentiment': t.sentiment, 'severity': t.severity}
                            for t in item.topics]
    for bucket in ('review_items', 'unprocessed'):
        for item in getattr(result, bucket):
            fid = item['feedback_id']
            if fid in buckets:
                raise EvaluationError('评测运行无效：结果桶不守恒：反馈重复。')
            buckets[fid] = bucket
    if set(buckets) != set(gold):
        raise EvaluationError('评测运行无效：结果桶不守恒：反馈缺失或出现额外 ID。')
    if result.unprocessed:
        raise EvaluationError('评测运行无效：存在未处理反馈，不计算指标。')
    infrastructure_markers = (
        'LLM 调用失败或响应异常', '分类未启动', 'API', '网络', '鉴权', '余额',
        '配置', '客户端', 'authentication', 'connection', 'timeout',
        'quota', 'rate_limit', 'network', 'initialization',
    )
    for item in result.review_items:
        reason = item.get('reason', '').casefold()
        if any(marker.casefold() in reason for marker in infrastructure_markers):
            raise EvaluationError('评测运行无效：最终人工复核中存在基础设施失败，不计算指标。')
    # Historical retry errors do not invalidate recovered final results.
    tp = fp = fn = risk_total = risk_found = 0
    differences = []
    for fid, annotations in gold.items():
        predicted = predictions.get(fid, [])
        expected_codes = {t['code'] for t in annotations}
        actual_codes = {t['code'] for t in predicted}
        if not (expected_codes | actual_codes) <= CODES:
            raise EvaluationError('结果包含固定主题表之外的代码。')
        tp += len(expected_codes & actual_codes)
        fp += len(actual_codes - expected_codes)
        fn += len(expected_codes - actual_codes)
        if high_risk(annotations):
            risk_total += 1
            risk_found += int(high_risk(predicted))
        if expected_codes != actual_codes:
            differences.append({'feedback_id': fid, 'gold_topics': sorted(expected_codes),
                                'predicted_topics': sorted(actual_codes),
                                'result_bucket': buckets[fid]})
    return {
        'eval_sample_size': len(gold),
        **{bucket: sum(value == bucket for value in buckets.values())
           for bucket in ('classifications', 'review_items', 'unprocessed')},
        'topic_micro_f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 'N/A',
        'TP': tp, 'FP': fp, 'FN': fn,
        'system_high_risk_count': sum(high_risk(topics) for topics in predictions.values()),
        'high_risk_recall': risk_found / risk_total if risk_total else 'N/A',
        'high_risk_numerator': risk_found, 'high_risk_denominator': risk_total,
        'evidence_support_rate': EVIDENCE,
        'call_count': result.call_count, 'total_tokens': result.total_tokens,
        'elapsed_seconds': result.elapsed_seconds,
        'differences': differences, 'statement': DISCLAIMER,
    }


@contextmanager
def private_model_call():
    """Prevent debug configuration from exposing prompts through SDK logging."""
    old_debug = os.environ.pop('USERECHO_DEBUG_PROMPT', None)
    old_disable = logging.root.manager.disable
    logging.disable(sys.maxsize)
    try:
        yield
    finally:
        logging.disable(old_disable)
        if old_debug is not None:
            os.environ['USERECHO_DEBUG_PROMPT'] = old_debug


def check_output_path(output):
    """Reject existing entries, including dangling symlinks, before API use."""
    if output is not None and os.path.lexists(output):
        raise EvaluationError('输出文件已存在，拒绝覆盖；未调用模型。')


def save_summary(output, payload):
    """Publish a complete file atomically without replacing a competing writer."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         dir=output.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, output)
    except FileExistsError:
        raise EvaluationError('输出文件已存在，拒绝覆盖；未写入本次结果。') from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run_evaluation(data_path, labels_path, checksum_path, *, expected_size=13, output=None):
    check_output_path(output)
    data_bytes, label_bytes = verified_bytes(data_path, labels_path, checksum_path)
    data, gold = load_inputs(data_bytes, label_bytes, expected_size)
    with private_model_call():
        try:
            build_system_prompt()
            client, model = create_client()
        except Exception:
            raise EvaluationError('评测运行无效：配置校验或客户端初始化失败，未调用模型。') from None
        try:
            if not model:
                raise EvaluationError('评测运行无效：模型配置为空，未调用模型。')
            result = classify(data, client=client, model=model)
        except EvaluationError:
            raise
        except Exception:
            raise EvaluationError('评测运行无效：分类执行异常，不计算指标。') from None
        finally:
            try:
                client.close()
            except Exception:
                pass  # Cleanup failures do not change completed predictions.
    summary = summarize(gold, result)
    if output is not None:
        save_summary(output, json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description='冻结小样本主题评测（会调用 LLM API）')
    parser.add_argument('--output', type=Path, help='可选：保存不含反馈原文的 JSON 汇总')
    args = parser.parse_args()
    eval_dir = ROOT / 'data/eval'
    try:
        if args.output and args.output.resolve().is_relative_to(eval_dir.resolve()):
            raise EvaluationError('评测结果不得写入 data/eval。')
        summary = run_evaluation(eval_dir / 'real_eval_20260927.csv',
                                 eval_dir / 'real_eval_labels_20260927.csv',
                                 eval_dir / 'CHECKSUM.sha256', output=args.output)
        payload = json.dumps(summary, ensure_ascii=False, indent=2)
        print(payload)
        return 0
    except EvaluationError as exc:
        print(str(exc), file=sys.stderr)
    except Exception:
        print('评测执行失败；为保护原文及凭据，不输出异常详情。', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
