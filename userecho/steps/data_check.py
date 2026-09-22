"""Read CSV bytes and produce deterministic data-quality results."""

import csv
import io
from typing import Literal, TypedDict

import pandas as pd


class DataCheckReport(TypedDict):
    raw_sample_size: int
    valid_sample_size: int
    missing_fields: list[str]
    empty_id_count: int
    empty_text_count: int
    duplicate_id_count: int
    duplicate_text_count: int
    short_text_count: int
    invalid_rating_count: int
    rating_distribution: dict[str, int]
    analysis_mode: Literal["blocked", "summary_only", "exploratory", "standard"]
    warnings: list[str]
    errors: list[str]
    can_proceed: bool


def data_check(raw_bytes: bytes) -> tuple[pd.DataFrame, DataCheckReport]:
    """Validate all rows, preserving the first ID before removing empty fields.

    Counts for each exclusion apply at that stage of the cleaning sequence.
    Return at most the first 200 valid rows after cleaning the entire CSV.
    Text and rating statistics apply only to these final retained rows. Empty
    fields mean empty or whitespace-only CSV cells; literal NA/NULL are text.
    Invalid ratings become NaN so downstream numeric summaries exclude them.
    """
    report: DataCheckReport = {
        "raw_sample_size": 0,
        "valid_sample_size": 0,
        "missing_fields": [],
        "empty_id_count": 0,
        "empty_text_count": 0,
        "duplicate_id_count": 0,
        "duplicate_text_count": 0,
        "short_text_count": 0,
        "invalid_rating_count": 0,
        "rating_distribution": {},
        "analysis_mode": "blocked",
        "warnings": [],
        "errors": [],
        "can_proceed": False,
    }
    empty = pd.DataFrame(columns=["feedback_id", "feedback_text"])
    decoded = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            decoded = raw_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        report["errors"].append("文件编码无法识别，请使用 UTF-8 或 GB18030 编码的 CSV。")
        return empty, report
    if not decoded.strip():
        report["errors"].append("CSV 文件为空，请上传包含必填字段和反馈数据的文件。")
        return empty, report
    if "\x00" in decoded:
        report["errors"].append("CSV 含有非法空字符，请检查文件格式。")
        return empty, report

    # Strict parsing rejects malformed quotes and inconsistent row widths.
    try:
        rows = list(csv.reader(io.StringIO(decoded, newline=""), strict=True))
    except csv.Error:
        report["errors"].append("CSV 格式损坏，请检查引号、分隔符和字段数量。")
        return empty, report
    if not rows or not rows[0]:
        report["errors"].append("CSV 缺少表头，请检查文件格式。")
        return empty, report
    headers, records = rows[0], rows[1:]
    report["raw_sample_size"] = len(records)
    if len(set(headers)) != len(headers) or any(not name.strip() for name in headers):
        report["errors"].append("CSV 表头包含重复或空列名，请修正后重新上传。")
        return empty, report
    report["missing_fields"] = [
        name for name in ("feedback_id", "feedback_text") if name not in headers
    ]
    if report["missing_fields"]:
        report["errors"].append("缺少必填字段：" + "、".join(report["missing_fields"]))
        return empty, report
    if any(len(row) != len(headers) for row in records):
        report["errors"].append("CSV 数据行与表头的字段数量不一致，请检查文件格式。")
        return empty, report

    cleaned = pd.DataFrame(records, columns=headers, dtype=str)
    duplicate_ids = cleaned["feedback_id"].duplicated(keep="first")
    report["duplicate_id_count"] = int(duplicate_ids.sum())
    cleaned = cleaned.loc[~duplicate_ids].copy()
    if report["duplicate_id_count"]:
        report["warnings"].append(
            f"发现 {report['duplicate_id_count']} 条重复反馈 ID，已保留第一次出现的记录。"
        )

    empty_ids = cleaned["feedback_id"].str.strip().eq("")
    report["empty_id_count"] = int(empty_ids.sum())
    cleaned = cleaned.loc[~empty_ids].copy()
    if report["empty_id_count"]:
        report["warnings"].append(f"已排除 {report['empty_id_count']} 条空反馈 ID 记录。")

    empty_texts = cleaned["feedback_text"].str.strip().eq("")
    report["empty_text_count"] = int(empty_texts.sum())
    cleaned = cleaned.loc[~empty_texts].copy().reset_index(drop=True)
    if report["empty_text_count"]:
        report["warnings"].append(f"已排除 {report['empty_text_count']} 条空反馈文本记录。")

    total_valid = len(cleaned)
    if total_valid > 200:
        report["warnings"].append(
            f"清洗后共发现 {total_valid} 条有效反馈，本次实际处理 200 条，"
            f"另有 {total_valid - 200} 条未处理；只取前 200 条可能受到原始排序影响。"
        )
        cleaned = cleaned.iloc[:200].copy()

    report["duplicate_text_count"] = int(cleaned["feedback_text"].duplicated().sum())
    if report["duplicate_text_count"]:
        report["warnings"].append(
            f"发现 {report['duplicate_text_count']} 条重复反馈文本，已保留全部记录。"
        )
    report["short_text_count"] = int(
        cleaned["feedback_text"].str.replace(r"\s", "", regex=True).str.len().lt(4).sum()
    )
    if report["short_text_count"]:
        report["warnings"].append(
            f"发现 {report['short_text_count']} 条去空白后不足 4 个字的短文本，已保留。"
        )
    if "rating" in cleaned.columns:
        ratings = pd.to_numeric(cleaned["rating"], errors="coerce")
        valid_ratings = ratings.between(1, 5)
        report["invalid_rating_count"] = int((~valid_ratings).sum())
        cleaned["rating"] = ratings.where(valid_ratings)
        report["rating_distribution"] = {
            format(float(value), "g"): int(count)
            for value, count in cleaned["rating"].value_counts().sort_index().items()
        }
        if report["invalid_rating_count"]:
            report["warnings"].append(
                f"发现 {report['invalid_rating_count']} 条无效评分，已从评分统计中排除，反馈仍保留。"
            )

    size = len(cleaned)
    report["valid_sample_size"] = size
    report["can_proceed"] = size > 0
    if size == 0:
        report["errors"].append("有效反馈为 0，无法继续分析。")
    elif size < 5:
        report["analysis_mode"] = "summary_only"
        report["warnings"].append("有效反馈不足 5 条，仅展示数据概览，不做优先级排序。")
    elif size < 30:
        report["analysis_mode"] = "exploratory"
        report["warnings"].append("小样本，仅供探索")
    else:
        report["analysis_mode"] = "standard"
    return cleaned, report
