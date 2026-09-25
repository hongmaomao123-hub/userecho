"""Batched OpenAI-compatible classification with bounded retries and partial results."""

import json
import logging
import os
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import dotenv_values
from openai import OpenAI
from pydantic import ValidationError

from userecho.classification_prompt import build_messages, build_system_prompt
from userecho.classification_schema import FeedbackClassification, RawFeedbackClassification
from userecho.steps.topic_selection import select_topics


LOGGER = logging.getLogger(__name__)
if not LOGGER.handlers:
    LOGGER.addHandler(logging.StreamHandler())
LOGGER.setLevel(logging.INFO)
ROOT = Path(__file__).resolve().parents[2]
CALL_LIMIT = 15


@dataclass
class ClassificationResult:
    classifications: list[FeedbackClassification] = field(default_factory=list)
    review_items: list[dict[str, str]] = field(default_factory=list)
    unprocessed: list[dict[str, str]] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    @property
    def call_count(self) -> int:
        return len(self.calls)

    @property
    def total_tokens(self) -> int:
        """Sum reported usage only; missing usage is not estimated."""
        return sum(call["total_tokens"] for call in self.calls if call["total_tokens"] is not None)

    @property
    def usage_complete(self) -> bool:
        return all(call["total_tokens"] is not None for call in self.calls)


def create_client() -> tuple[OpenAI, str]:
    """Read configuration without including credentials in prompts or errors."""
    settings = dotenv_values(ROOT / ".env")
    values = {name: os.environ.get(name) or settings.get(name)
              for name in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL")}
    if not all(values.values()):
        raise ValueError("请配置 LLM_API_KEY、LLM_BASE_URL 和 LLM_MODEL。")
    # Disable SDK retries so one counted attempt is exactly one HTTP attempt.
    return OpenAI(api_key=values["LLM_API_KEY"], base_url=values["LLM_BASE_URL"],
                  max_retries=0, timeout=30.0), values["LLM_MODEL"]


def parse_batch(content: str, expected_ids: list[str]) -> tuple[dict[str, FeedbackClassification], dict[str, str]]:
    """Validate items independently; malformed envelopes fail only this attempt."""
    failed = {fid: "分类失败：返回缺少该反馈。" for fid in expected_ids}
    passed: dict[str, FeedbackClassification] = {}
    try:
        payload = json.loads(content)
        if not isinstance(payload, dict) or set(payload) != {"results"} or not isinstance(payload["results"], list):
            raise ValueError("invalid envelope")
    except (ValueError, TypeError):
        return passed, {fid: "分类失败：返回内容不是规定的 JSON 结构。" for fid in expected_ids}
    entries = payload["results"]
    counts = Counter(item.get("feedback_id") for item in entries
                     if isinstance(item, dict) and isinstance(item.get("feedback_id"), str))
    for item in entries:
        if not isinstance(item, dict):
            continue
        fid = item.get("feedback_id")
        if not isinstance(fid, str) or fid not in failed:
            continue
        if counts[fid] != 1:
            failed[fid] = "分类失败：返回的反馈 ID 重复。"
            continue
        try:
            raw = RawFeedbackClassification.model_validate(item)
            final = FeedbackClassification(
                feedback_id=raw.feedback_id, topics=select_topics(raw.topics),
                repurchase_signal=raw.repurchase_signal,
            )
        except (ValidationError, ValueError):
            failed[fid] = "分类失败：字段、主题或严重度未通过校验。"
        else:
            passed[fid] = final
    for fid in passed:
        failed.pop(fid)
    return passed, failed


def classify(cleaned_df: pd.DataFrame, batch_size: int = 25, *, client: Any = None,
             model: str | None = None) -> ClassificationResult:
    """Return successes, review items and unprocessed IDs without raising API errors.

    Each invocation owns a single call budget shared by all its batches. A valid
    item is retained at its first successful attempt, even if later batch retries
    omit it or return invalid content for it. Retries resend the whole batch.
    The optional client/model are injection points for offline tests.
    """
    started = time.perf_counter()
    result = ClassificationResult()
    owned_client = False
    try:
        if type(batch_size) is not int or not 1 <= batch_size <= 25:
            result.errors.append("批大小必须是 1–25 的整数。")
            return result
        if not isinstance(cleaned_df, pd.DataFrame) or not {"feedback_id", "feedback_text"} <= set(cleaned_df.columns):
            result.errors.append("输入缺少 feedback_id 或 feedback_text 字段。")
            return result
        records = cleaned_df[["feedback_id", "feedback_text"]].to_dict("records")
        if not records:
            return result
        ids = [row["feedback_id"] for row in records]
        if any(not isinstance(value, str) or not value.strip()
               for row in records for value in row.values()) or len(ids) != len(set(ids)):
            result.errors.append("输入必须是已清洗的非空文本，且反馈 ID 不重复。")
            return result
        try:
            system_prompt = build_system_prompt()
            if client is None:
                client, configured_model = create_client()
                owned_client = True
                model = model or configured_model
            if not model:
                raise ValueError("missing model")
        except Exception:
            message = "分类未启动：请检查主题配置、依赖及 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL。"
            result.errors.append(message)
            result.unprocessed = [{"feedback_id": fid, "reason": message} for fid in ids]
            return result
        successes: dict[str, FeedbackClassification] = {}
        for start in range(0, len(records), batch_size):
            batch = records[start:start + batch_size]
            batch_ids = [row["feedback_id"] for row in batch]
            pending = {fid: "分类失败：未获得有效结果。" for fid in batch_ids}
            attempts_made = 0
            for attempt in range(1, 4):
                if result.call_count >= CALL_LIMIT:
                    break
                messages = build_messages(batch, system_prompt)
                if os.environ.get("USERECHO_DEBUG_PROMPT") == "1":
                    LOGGER.info("完整分类 Prompt：\n%s",
                                json.dumps(messages, ensure_ascii=False, indent=2))
                call = {"batch": start // batch_size + 1, "attempt": attempt,
                        "prompt_tokens": None, "completion_tokens": None, "total_tokens": None,
                        "elapsed_seconds": 0.0, "error": None}
                result.calls.append(call)
                attempts_made += 1
                call_started = time.perf_counter()
                try:
                    response = client.chat.completions.create(
                        model=model, messages=messages, response_format={"type": "json_object"},
                        temperature=0,
                    )
                    usage = getattr(response, "usage", None)
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        value = getattr(usage, key, None)
                        if type(value) is int and value >= 0:
                            call[key] = value
                    content = response.choices[0].message.content
                    passed, failed = parse_batch(content, batch_ids)
                    for fid, classification in passed.items():
                        successes.setdefault(fid, classification)
                    pending = {fid: failed.get(fid, "分类失败：未获得有效结果。")
                               for fid in batch_ids if fid not in successes}
                    if pending:
                        call["error"] = "部分反馈未通过分类校验。"
                except Exception as exc:
                    # Never log exception messages, bodies, headers or tracebacks.
                    status = getattr(exc, "status_code", None)
                    safe_status = status if type(status) is int and 100 <= status <= 599 else "未知"
                    LOGGER.warning("LLM 调用失败：%s/%s", type(exc).__name__, safe_status)
                    call["error"] = "LLM 调用失败或响应异常，请稍后重试。"
                    pending = {fid: call["error"] for fid in batch_ids if fid not in successes}
                finally:
                    call["elapsed_seconds"] = time.perf_counter() - call_started
                    LOGGER.info(
                        "LLM 调用：batch_size=%s call_count=%s model=%r elapsed_seconds=%.3f "
                        "prompt_tokens=%s completion_tokens=%s total_tokens=%s",
                        len(batch), result.call_count, model, call["elapsed_seconds"],
                        call["prompt_tokens"], call["completion_tokens"], call["total_tokens"],
                    )
                if not pending:
                    break
            if pending:
                if result.call_count >= CALL_LIMIT and attempts_made < 3:
                    # Budget prevents the remaining attempts, so these are unfinished.
                    result.unprocessed.extend({"feedback_id": fid, "reason": "未处理（已达 LLM 调用上限）"}
                                              for fid in pending)
                else:
                    result.review_items.extend({"feedback_id": fid, "reason": reason}
                                               for fid, reason in pending.items())
            if result.call_count >= CALL_LIMIT:
                result.unprocessed.extend(
                    {"feedback_id": row["feedback_id"], "reason": "未处理（已达 LLM 调用上限）"}
                    for row in records[start + len(batch):]
                )
                break
        result.classifications = [successes[fid] for fid in ids if fid in successes]
        return result
    finally:
        if owned_client:
            try:
                client.close()
            except Exception:
                result.errors.append("LLM 客户端关闭失败。")
        result.elapsed_seconds = time.perf_counter() - started
