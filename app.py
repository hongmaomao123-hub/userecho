"""Chinese upload, classification and deterministic topic-analysis interface."""

import hashlib

import pandas as pd
import streamlit as st

from userecho.steps.data_check import data_check
from userecho.steps.classify import classify
from userecho.steps.analyze import analyze, display_table, load_impact


st.set_page_config(page_title="UserEcho 用户反馈检查", page_icon="💬", layout="wide")
st.title("UserEcho 用户反馈检查")
st.caption("上传 CSV，查看清洗后的前 10 行与数据检查结果。点击开始分析后进行分类与主题统计。")
goal_label = st.selectbox("分析目标", ["满意度分析", "主要抱怨", "复购相关"])
goal = {"满意度分析": "satisfaction", "主要抱怨": "complaints", "复购相关": "repurchase"}[goal_label]
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


    if report["can_proceed"]:
        upload_key = hashlib.sha256(upload.getvalue()).hexdigest()
        if st.session_state.get("classification_upload") != upload_key:
            st.session_state.pop("classification_result", None)
            st.session_state["classification_upload"] = upload_key
        st.caption("影响分 I 使用项目负责人批准的业务规则。")
        if report["analysis_mode"] == "summary_only":
            st.info("样本量不足，仅展示主题统计")
        if st.button("开始分析", type="primary", disabled=report["analysis_mode"] == "summary_only"):
            try:
                load_impact(goal)
                with st.spinner("正在分类反馈…"):
                    st.session_state["classification_result"] = classify(cleaned_df)
            except ValueError as exc:
                st.error(str(exc))
        result = st.session_state.get("classification_result")
        if result is not None:
            for error in result.errors:
                st.error(error)
            st.write(f"成功分类 {len(result.classifications)} 条；待人工复核 {len(result.review_items)} 条；未处理 {len(result.unprocessed)} 条。")
            st.caption(f"API 调用 {result.call_count} 次；已记录 tokens {result.total_tokens}；耗时 {result.elapsed_seconds:.2f} 秒。")
            if not result.usage_complete:
                st.warning("部分调用缺少 token 用量，显示的是已知用量。")
            if len(result.classifications) < report["valid_sample_size"]:
                st.warning("分类尚未覆盖全部有效反馈；比例仍以本次处理反馈数为分母，结果仅反映已成功分类部分。")
            if result.review_items:
                st.subheader("分类人工复核清单")
                st.dataframe(pd.DataFrame(result.review_items).rename(columns={"feedback_id":"反馈 ID", "reason":"复核原因"}), hide_index=True)
            if result.unprocessed:
                st.subheader("未处理反馈")
                st.dataframe(pd.DataFrame(result.unprocessed).rename(columns={"feedback_id":"反馈 ID", "reason":"未处理原因"}), hide_index=True)
            try:
                analysis = analyze(result.classifications, report["valid_sample_size"], goal)
                st.subheader("主题统计")
                st.dataframe(display_table(analysis), hide_index=True)
                if not analysis.empty:
                    for title, subset in [
                        ("优先级排序", analysis[analysis["priority"].notna()]),
                        ("风险警报", analysis[analysis["risk_alert"]]),
                        ("证据不足清单", analysis[analysis["insufficient_evidence"]]),
                        ("主题人工复核清单", analysis[analysis["review_required"]]),
                    ]:
                        st.subheader(title)
                        if subset.empty:
                            st.info("暂无符合条件的主题。")
                        else:
                            if title == "风险警报":
                                st.warning("仅用于反馈识别，需人工核实")
                            st.dataframe(display_table(subset), hide_index=True)
            except ValueError as exc:
                st.error(str(exc))
    else:
        st.session_state.pop("classification_result", None)
        st.session_state.pop("classification_upload", None)
else:
    st.session_state.pop("classification_result", None)
    st.session_state.pop("classification_upload", None)

st.caption("本工具不提供医疗诊断或健康建议。")
