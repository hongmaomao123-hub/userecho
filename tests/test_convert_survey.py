from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from scripts.convert_survey import COLUMNS, convert_frame, convert_survey, split_respondents


def survey():
    return pd.DataFrame({
        '1、资格': ['是，买过', '否，没有', '是'],
        '2、类别': ['香水', '', '蜡烛'], '3、评价': ['第一款评价', '', '另一人评价'],
        '4、评分': ['5=非常满意', '', '3=一般'], '5、复购': ['会', '', '不会'],
        '6、渠道': ['门店', '', '京东'], '8、第二款': ['是', '(跳过)', '否'],
        '9、(1)类别': ['无火香薰', '', ''], '9、(2)评分': ['2', '', ''],
        '9、(3)渠道': ['淘宝', '', ''], '9、(6)评价': ['第二款评价', '', ''],
        '姓名': ['PRIVATE']*3, '电话': ['PRIVATE']*3,
        '来自IP': ['PRIVATE']*3, '提交答卷时间': ['PRIVATE']*3,
    })


def test_filter_long_format_ids_and_anonymous_allowlist():
    result = convert_frame(survey())
    assert list(result.columns) == COLUMNS
    assert result.feedback_id.tolist() == ['R001_P1', 'R001_P2', 'R003_P1']
    assert result.respondent_id.tolist() == ['R001', 'R001', 'R003']
    assert result.rating.tolist() == [5, 2, 3]
    assert result.iloc[1].channel == '淘宝' and result.iloc[1].product_type == '无火香薰'
    assert result.iloc[1].feedback_text == '第二款评价'
    assert 'PRIVATE' not in result.to_csv(index=False)


def test_split_is_repeatable_and_keeps_respondents_together():
    frame = convert_frame(survey())
    dev, evaluation = split_respondents(frame)
    again, _ = split_respondents(frame)
    pd.testing.assert_frame_equal(dev, again)
    assert set(dev.respondent_id).isdisjoint(evaluation.respondent_id)
    assert dev.respondent_id.nunique() == evaluation.respondent_id.nunique() == 1
    assert len(dev) + len(evaluation) == len(frame)


def test_odd_respondent_split_uses_floor_for_dev():
    frame = pd.DataFrame({'respondent_id': ['R001', 'R002', 'R003']})
    dev, evaluation = split_respondents(frame)
    assert len(dev) == 1 and len(evaluation) == 2


def test_excel_read_and_csv_write(tmp_path):
    source, dev, evaluation = [tmp_path / name for name in ['input.xlsx', 'dev.csv', 'holdout.csv']]
    survey().to_excel(source, index=False)
    with patch('scripts.convert_survey.pd.read_excel', wraps=pd.read_excel) as reader:
        sizes = convert_survey(source, dev, evaluation)
    reader.assert_called_once_with(source, engine='openpyxl', dtype=str, keep_default_na=False)
    assert sum(sizes) == 3
    assert list(pd.read_csv(dev).columns) == COLUMNS
    assert list(pd.read_csv(evaluation).columns) == COLUMNS
    with pytest.raises(ValueError, match='已存在'):
        convert_survey(source, dev, evaluation)


def test_missing_column_and_invalid_rating_fail():
    with pytest.raises(ValueError, match='列映射'):
        convert_frame(survey().drop(columns=['9、(6)评价']))
    frame = survey()
    frame.loc[0, '4、评分'] = '6'
    with pytest.raises(ValueError, match='评分'):
        convert_frame(frame)
