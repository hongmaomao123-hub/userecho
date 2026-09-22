import csv
import io
import json

import pytest

from userecho.steps.data_check import data_check


def csv_bytes(rows, headers=("feedback_id", "feedback_text"), encoding="utf-8"):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(headers)
    writer.writerows(rows)
    return stream.getvalue().encode(encoding)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "gb18030", "gbk"])
def test_encodings(encoding):
    cleaned, report = data_check(csv_bytes([("001", "香味非常好闻")], encoding=encoding))
    assert cleaned.iloc[0].to_dict() == {"feedback_id": "001", "feedback_text": "香味非常好闻"}
    assert report["raw_sample_size"] == report["valid_sample_size"] == 1
    assert report["can_proceed"] is True
    json.dumps(report, ensure_ascii=False, allow_nan=False)


def test_gb18030_extended_character():
    cleaned, report = data_check(csv_bytes([("1", "香味𠀀非常好")], encoding="gb18030"))
    assert cleaned.iloc[0]["feedback_text"] == "香味𠀀非常好"
    assert report["can_proceed"] is True


@pytest.mark.parametrize("raw", [
    b"", b" \n\t", b"\xef\xbb\xbf", b"\xff",
    b'feedback_id,feedback_text\n1,"unclosed',
    b"feedback_id,feedback_text\n1,text,extra",
    b"feedback_id,feedback_text\n1",
    b"feedback_id,feedback_text,feedback_text\n1,a,b",
    b"feedback_id,feedback_text\n1,abc\x00def",
])
def test_empty_or_damaged_csv(raw):
    cleaned, report = data_check(raw)
    assert cleaned.empty
    assert report["analysis_mode"] == "blocked"
    assert report["can_proceed"] is False
    assert report["errors"]


@pytest.mark.parametrize("headers,missing", [
    (("other",), ["feedback_id", "feedback_text"]),
    (("feedback_id",), ["feedback_text"]),
    (("feedback_text",), ["feedback_id"]),
])
def test_missing_fields(headers, missing):
    cleaned, report = data_check(csv_bytes([("value",)], headers=headers))
    assert cleaned.empty
    assert report["missing_fields"] == missing
    assert report["raw_sample_size"] == 1
    assert not report["can_proceed"]


def test_duplicate_text_retained():
    cleaned, report = data_check(csv_bytes([("1", "香味非常好闻"), ("2", "香味非常好闻")]))
    assert len(cleaned) == 2
    assert report["duplicate_text_count"] == 1
    assert report["warnings"]


def test_short_text_retained():
    cleaned, report = data_check(csv_bytes([("1", "好"), ("2", " 好 闻 "), ("3", "香味非常好")]))
    assert len(cleaned) == 3
    assert report["short_text_count"] == 2
    assert cleaned.iloc[1]["feedback_text"] == " 好 闻 "


def test_invalid_ratings_excluded():
    values = ["1", "5", "3.5", "0", "6", "abc", "", "NaN", "inf", "-inf"]
    cleaned, report = data_check(csv_bytes(
        [(str(i), "香味非常好闻", value) for i, value in enumerate(values)],
        headers=("feedback_id", "feedback_text", "rating"),
    ))
    assert len(cleaned) == 10
    assert report["invalid_rating_count"] == 7
    assert report["rating_distribution"] == {"1": 1, "3.5": 1, "5": 1}
    assert cleaned["rating"].notna().sum() == 3
    assert cleaned["rating"].mean() == pytest.approx(9.5 / 3)
    json.dumps(report, allow_nan=False)


def test_missing_optional_rating():
    _, report = data_check(csv_bytes([("1", "香味非常好闻")]))
    assert report["invalid_rating_count"] == 0
    assert report["rating_distribution"] == {}


@pytest.mark.parametrize("size,mode", [
    (0, "blocked"), (1, "summary_only"), (4, "summary_only"),
    (5, "exploratory"), (29, "exploratory"), (30, "standard"), (31, "standard"),
])
def test_analysis_modes(size, mode):
    cleaned, report = data_check(csv_bytes([(str(i), "香味非常好闻") for i in range(size)]))
    assert len(cleaned) == report["valid_sample_size"] == report["raw_sample_size"] == size
    assert report["analysis_mode"] == mode
    assert report["can_proceed"] == (size > 0)
    if mode == "exploratory":
        assert "小样本，仅供探索" in report["warnings"]


def test_quoted_comma_and_multiline_text():
    text = '香味不错,但有点浓\n"包装很好"'
    cleaned, _ = data_check(csv_bytes([("NA", text), ("002", "NULL")]))
    assert cleaned["feedback_id"].tolist() == ["NA", "002"]
    assert cleaned["feedback_text"].tolist() == [text, "NULL"]


def test_cleaning_order_and_stage_counts():
    rows = [
        ("1", ""), ("1", "后来的有效文本"),
        ("", ""), ("", "重复的空白编号"), (" \t", "有效文本"),
        ("2", " \t"), ("3", "香味非常好闻"), ("3", "其他重复文本"),
    ]
    cleaned, report = data_check(csv_bytes(rows))
    assert cleaned["feedback_id"].tolist() == ["3"]
    assert report["raw_sample_size"] == 8
    assert report["duplicate_id_count"] == 3
    assert report["empty_id_count"] == 2
    assert report["empty_text_count"] == 2
    assert report["valid_sample_size"] == 1
    assert report["raw_sample_size"] == sum(report[key] for key in (
        "duplicate_id_count", "empty_id_count", "empty_text_count", "valid_sample_size"
    ))


def test_duplicate_id_keeps_original_first_row():
    cleaned, report = data_check(csv_bytes([("1", "第一条原始文本"), ("1", "第二条不同文本")]))
    assert cleaned["feedback_text"].tolist() == ["第一条原始文本"]
    assert report["duplicate_id_count"] == 1


def test_all_rows_removed():
    cleaned, report = data_check(csv_bytes([("", "有效文本"), ("1", "")]))
    assert cleaned.empty
    assert report["raw_sample_size"] == 2
    assert report["valid_sample_size"] == 0
    assert report["analysis_mode"] == "blocked"
    assert not report["can_proceed"]


@pytest.mark.parametrize("size", [200, 201, 251])
def test_valid_dataset_limit_and_warning(size):
    cleaned, report = data_check(csv_bytes([(str(i), f"反馈内容{i}") for i in range(size)]))
    assert report["raw_sample_size"] == size
    assert len(cleaned) == report["valid_sample_size"] == 200
    assert cleaned["feedback_id"].tolist() == [str(i) for i in range(200)]
    assert report["analysis_mode"] == "standard"
    if size > 200:
        assert (
            f"清洗后共发现 {size} 条有效反馈，本次实际处理 200 条，"
            f"另有 {size - 200} 条未处理；只取前 200 条可能受到原始排序影响。"
        ) in report["warnings"]
    else:
        assert not report["warnings"]


def test_limit_applies_after_full_cleaning_and_before_statistics():
    rows = [("duplicate", ""), ("duplicate", "后续重复记录"), ("", "空编号记录")]
    rows += [(str(i), f"有效反馈内容{i}") for i in range(200)]
    rows += [("200", "好"), ("201", "有效反馈内容0"), ("202", "")]
    rated_rows = [(key, text, "5" if key.isdigit() and int(key) < 200 else "bad")
                  for key, text in rows]
    cleaned, report = data_check(csv_bytes(
        rated_rows, headers=("feedback_id", "feedback_text", "rating")
    ))
    assert report["raw_sample_size"] == 206
    assert report["duplicate_id_count"] == 1
    assert report["empty_id_count"] == 1
    assert report["empty_text_count"] == 2
    assert len(cleaned) == report["valid_sample_size"] == 200
    assert cleaned["feedback_id"].tolist() == [str(i) for i in range(200)]
    assert report["duplicate_text_count"] == report["short_text_count"] == 0
    assert report["invalid_rating_count"] == 0
    assert report["rating_distribution"] == {"5": 200}
    assert any("202 条有效反馈" in warning and "2 条未处理" in warning
               for warning in report["warnings"])


def test_missing_text_cells_and_literal_na_null():
    cleaned, report = data_check(csv_bytes([
        ("1", None), ("2", ""), ("3", "NA"), ("4", "NULL"),
    ]))
    assert report["empty_text_count"] == 2
    assert cleaned["feedback_text"].tolist() == ["NA", "NULL"]


def test_statistics_only_include_retained_rows():
    cleaned, report = data_check(csv_bytes([
        ("1", "香味非常好闻", "5"), ("1", "好", "bad"),
        ("", "香味非常好闻", "bad"), ("2", "", "bad"),
    ], headers=("feedback_id", "feedback_text", "rating")))
    assert len(cleaned) == 1
    assert report["duplicate_text_count"] == 0
    assert report["short_text_count"] == 0
    assert report["invalid_rating_count"] == 0
    assert report["rating_distribution"] == {"5": 1}


def test_report_uses_new_contract_only():
    _, report = data_check(csv_bytes([]))
    assert set(report) == {
        "raw_sample_size", "valid_sample_size", "missing_fields", "empty_id_count",
        "empty_text_count", "duplicate_id_count", "duplicate_text_count",
        "short_text_count", "invalid_rating_count", "rating_distribution",
        "analysis_mode", "warnings", "errors", "can_proceed",
    }
