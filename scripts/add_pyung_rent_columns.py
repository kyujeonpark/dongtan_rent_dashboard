# -*- coding: utf-8 -*-
"""
dedup Parquet/CSV에 전용면적(㎡) 기준 평당 월 임대료 컬럼을 추가합니다.

단위:
  - 전용면적: ㎡
  - 보증금·월세: 만 원

환산:
  - 보증금 **연 환산이율 5.0%** → 월 상당 = 연이율 ÷ 12
  - 보증금_월환산분_만원 = 보증금(만 원) × (0.05 / 12)
  - 월환산임대료_만원 = 월세가 + 보증금_월환산분_만원  (보증금 결측은 0으로 처리)

평:
  - 1평 = 3.305785 ㎡ (표준 환산)
  - 전용면적_평 = 전용면적 / 3.305785
  - 평당월임대료_만원 = 월환산임대료_만원 / 전용면적_평  (전용면적이 없거나 0이면 결측)

입력·출력 (덮어쓰기):
  - 2_processed/화성시_동탄구_상가데이터_임대료_dedup.parquet
  - 2_processed/화성시_동탄구_상가데이터_임대료_dedup.csv  (선택, --no-csv 로 생략)
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PARQUET_PATH = ROOT / "2_processed" / "화성시_동탄구_상가데이터_임대료_dedup.parquet"
CSV_PATH = ROOT / "2_processed" / "화성시_동탄구_상가데이터_임대료_dedup.csv"

# 1평당 제곱미터 (국내 일반 관행)
SQ_M_PER_PYEONG = 3.305785123966942
# 보증금을 월 임대료로 환산: 연 이율을 월로 나눔 (연 5% → 월 = 5%/12)
DEPOSIT_ANNUAL_RATE = 0.05
DEPOSIT_TO_MONTHLY_FACTOR = DEPOSIT_ANNUAL_RATE / 12.0


def add_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    deposit = pd.to_numeric(out["보증금"], errors="coerce").fillna(0.0)
    monthly = pd.to_numeric(out["월세가"], errors="coerce")
    area = pd.to_numeric(out["전용면적"], errors="coerce")

    out["보증금_월환산분_만원"] = deposit * DEPOSIT_TO_MONTHLY_FACTOR
    conv = monthly + out["보증금_월환산분_만원"]
    out["월환산임대료_만원"] = conv

    # 전용면적(㎡) → 평
    pyeong = area / SQ_M_PER_PYEONG
    out["전용면적_평"] = pyeong

    # 월세가 결측이면 월환산도 의미 없음 → 평당 미계산
    valid = (
        pyeong.notna()
        & (pyeong > 0)
        & conv.notna()
    )
    out["평당월임대료_만원"] = pd.NA
    out.loc[valid, "평당월임대료_만원"] = conv.loc[valid].astype(float) / pyeong.loc[valid]

    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="dedup에 평당 월 임대료 컬럼 추가")
    parser.add_argument("--no-csv", action="store_true", help="CSV는 갱신하지 않음")
    args = parser.parse_args()

    if not PARQUET_PATH.exists():
        raise SystemExit(f"Parquet 없음: {PARQUET_PATH}")

    df = pd.read_parquet(PARQUET_PATH)
    need = {"보증금", "월세가", "전용면적"}
    missing = need - set(df.columns)
    if missing:
        raise SystemExit(f"필수 컬럼 없음: {missing}")

    df["PNU코드"] = df["PNU코드"].astype(str).str.strip()
    df = add_columns(df)

    df.to_parquet(PARQUET_PATH, index=False, engine="pyarrow")

    n_pyung = df["평당월임대료_만원"].notna().sum()
    print(f"보증금 환산: 연 {DEPOSIT_ANNUAL_RATE * 100:.1f}% → 월 계수 {DEPOSIT_TO_MONTHLY_FACTOR:.10g}")
    print(f"행수: {len(df):,}")
    print(f"평당월임대료_만원 유효 행: {n_pyung:,}")
    print(f"저장 Parquet: {PARQUET_PATH}")

    if not args.no_csv:
        if CSV_PATH.exists():
            df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
            print(f"저장 CSV: {CSV_PATH}")
        else:
            print(f"(CSV 없음, 건너뜀: {CSV_PATH})")


if __name__ == "__main__":
    main()
