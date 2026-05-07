# -*- coding: utf-8 -*-
"""
이미 만든 dedup CSV에서 Parquet만 생성합니다 (원본 엑셀을 다시 읽지 않음).

사용: python csv_to_parquet_rent_dedup.py
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "2_processed" / "화성시_동탄구_상가데이터_임대료_dedup.csv"
PARQUET_PATH = ROOT / "2_processed" / "화성시_동탄구_상가데이터_임대료_dedup.parquet"


def main() -> None:
    if not CSV_PATH.exists():
        raise SystemExit(f"CSV가 없습니다: {CSV_PATH}")

    df = pd.read_csv(CSV_PATH, dtype={"PNU코드": str}, low_memory=False)
    df.to_parquet(PARQUET_PATH, index=False, engine="pyarrow")
    print(f"행수: {len(df):,}")
    print(f"저장: {PARQUET_PATH}")


if __name__ == "__main__":
    main()
