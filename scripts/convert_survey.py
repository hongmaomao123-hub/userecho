"""Convert the textual Wenjuanxing Excel export into respondent-split CSVs."""

import argparse
from pathlib import Path
import random
import re

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
COLUMNS = ['feedback_id', 'respondent_id', 'feedback_text', 'rating', 'product_type', 'channel']


def find_column(frame: pd.DataFrame, question: int, subquestion: int | None = None) -> str:
    prefix = rf'^(?:Q)?{question}\s*[、.．：:]\s*'
    if subquestion is not None:
        prefix += rf'[（(]{subquestion}[）)]'
    matches = [col for col in frame.columns if re.match(prefix, str(col).strip(), re.I)]
    if len(matches) != 1:
        raise ValueError(f'问卷列映射不唯一或缺失：Q{question}，子题 {subquestion}。')
    return matches[0]


def parse_rating(value: str) -> int:
    match = re.fullmatch(r'([1-5])(?:\.0|\s*[=＝].*)?', str(value).strip())
    if not match:
        raise ValueError('发现非 1–5 分的评分，请核对原始 Excel。')
    return int(match.group(1))


def convert_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Use a strict output allowlist; never retain survey metadata or Q5."""
    q = {n: find_column(frame, n) for n in [1, 2, 3, 4, 6, 8]}
    second = {n: find_column(frame, 9, n) for n in [1, 2, 3, 6]}
    records = []
    for position, (_, row) in enumerate(frame.iterrows(), 1):
        eligibility = str(row[q[1]]).strip()
        if eligibility.startswith('否'):
            continue
        if not eligibility.startswith('是'):
            raise ValueError('Q1 存在无法识别的答案，未执行输出。')
        rid = f'R{position:03d}'
        products = [(1, row[q[3]], row[q[4]], row[q[2]], row[q[6]])]
        answer = str(row[q[8]]).strip()
        if answer.startswith('是'):
            products.append((2, row[second[6]], row[second[2]], row[second[1]], row[second[3]]))
        elif not answer.startswith('否'):
            raise ValueError('有效答卷的 Q8 存在无法识别的答案，未执行输出。')
        for number, text, rating, product_type, channel in products:
            if not str(text).strip() or str(text).strip() == '(跳过)':
                raise ValueError('有效产品评价为空，未执行输出。')
            records.append(dict(zip(COLUMNS, [f'{rid}_P{number}', rid, str(text).strip(),
                parse_rating(rating), str(product_type).strip(), str(channel).strip()])))
    return pd.DataFrame(records, columns=COLUMNS)


def split_respondents(frame: pd.DataFrame, seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame]:
    ids = frame['respondent_id'].drop_duplicates().tolist()
    random.Random(seed).shuffle(ids)
    # For odd counts, assign the extra respondent to eval; never split products.
    dev_ids = set(ids[:len(ids) // 2])
    mask = frame['respondent_id'].isin(dev_ids)
    return frame.loc[mask].reset_index(drop=True), frame.loc[~mask].reset_index(drop=True)


def convert_survey(source: Path, dev_path: Path, eval_path: Path) -> tuple[int, int]:
    if dev_path.resolve() == eval_path.resolve() or dev_path.exists() or eval_path.exists():
        raise ValueError('输出路径重复或文件已存在；为防止覆盖，本次未写入。')
    raw = pd.read_excel(source, engine='openpyxl', dtype=str, keep_default_na=False)
    dev, evaluation = split_respondents(convert_frame(raw))
    for path, data in [(dev_path, dev), (eval_path, evaluation)]:
        path.parent.mkdir(parents=True, exist_ok=True)
        data.to_csv(path, index=False, encoding='utf-8-sig', mode='x')
    return len(dev), len(evaluation)


def main() -> None:
    parser = argparse.ArgumentParser(description='将问卷星文本 Excel 转换为匿名字段 CSV。')
    parser.add_argument('--input', type=Path, default=ROOT / 'data/raw/survey_v1_raw.xlsx')
    parser.add_argument('--dev', type=Path, default=ROOT / 'data/dev/real_dev_20260927.csv')
    parser.add_argument('--eval', type=Path, default=ROOT / 'data/eval/real_eval_20260927.csv')
    args = parser.parse_args()
    dev_count, eval_count = convert_survey(args.input, args.dev, args.eval)
    print(f'转换完成：dev {dev_count} 行；eval {eval_count} 行。')


if __name__ == '__main__':
    main()
