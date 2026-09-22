"""Chinese CSV upload and data-quality interface for step one."""

import pandas as pd
import streamlit as st

from userecho.steps.data_check import data_check


st.set_page_config(page_title="UserEcho 用户反馈检查", page_icon="💬", layout="wide")
st.title("UserEcho 用户反馈检查")
st.caption("上传 CSV，查看清洗后的前 10 行与数据检查结果。当前仅提供数据检查。")
st.selectbox("分析目标", ["满意度分析", "主要抱怨", "复购相关"])
upload = st.file_uploader("上传用户反馈 CSV", type=["csv"])
st.caption("必填字段：feedback_id、feedback_text；支持 UTF-8 和 GB18030 编码。")

if upload is not None:
    cleaned_df, report = data_check(upload.getvalue())
    for error in report["errors"]:
        st.error(error)
    for warning in report["warnings"]:
        st.warning(warning)

    st.subheader("数据检查结果")
    left, right = st.columns(2)
    left.metric("原始反馈数", report["raw_sample_size"])
    right.metric("本次处理反馈数", report["valid_sample_size"])
    modes = {
        "blocked": "无法分析",
        "summary_only": "仅数据概览",
        "exploratory": "探索性分析",
        "standard": "标准分析",
    }
    st.write("分析模式：" + modes[report["analysis_mode"]])
    st.write("可继续：" + ("是" if report["can_proceed"] else "否"))
    st.write("缺少必填字段：" + ("、".join(report["missing_fields"]) or "无"))
    labels = {
        "duplicate_id_count": "排除的重复 ID 数",
        "empty_id_count": "排除的空 ID 数",
        "empty_text_count": "排除的空文本数",
        "duplicate_text_count": "保留的重复文本数",
        "short_text_count": "保留的短文本数",
        "invalid_rating_count": "无效评分数",
    }
    st.table(pd.DataFrame([
        {"检查项": label, "数量": report[key]} for key, label in labels.items()
    ]))
    st.caption("按去重 ID、排除空 ID、排除空文本的顺序计数；最多处理清洗后的前 200 条；文本和评分统计、本次处理反馈数均基于本次实际处理的数据。")
    st.subheader("评分分布")
    if report["rating_distribution"]:
        st.table(pd.DataFrame([
            {"评分": rating, "反馈数": count}
            for rating, count in report["rating_distribution"].items()
        ]))
    else:
        st.info("暂无有效评分。")
    st.subheader("清洗后数据预览（前 10 行）")
    preview_df = cleaned_df.head(10).copy()
    if "rating" in preview_df.columns:
        preview_df["rating"] = preview_df["rating"].map(
            lambda value: "—" if pd.isna(value) else format(float(value), "g")
        )
    st.dataframe(preview_df, hide_index=True)

st.caption("本工具不提供医疗诊断或健康建议。")
