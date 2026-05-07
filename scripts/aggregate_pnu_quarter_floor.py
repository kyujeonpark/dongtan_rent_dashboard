# -*- coding: utf-8 -*-
"""
dedup Parquet 기준: 분기 × PNU × 층구분(1F / 3층 이상)별 **평당 월 임대료(만 원/평)** 평균·중위·건수 집계.

※ dedup에 `평당월임대료_만원` 컬럼이 있어야 합니다. 없으면 먼저:
   `python scripts/add_pyung_rent_columns.py`

층구분 규칙:
  - 현재층(층정보 앞부분)이 1이면 1F (문자열이 B로 시작하면 지하층으로 보고 제외)
  - 3 이상이면 3F_PLUS (upper)
  - 2층·미파싱·지하는 집계에서 제외

입력:  2_processed/화성시_동탄구_상가데이터_임대료_dedup.parquet
출력:  2_processed/rent_pnu_quarter_1f_upper.parquet
        2_processed/rent_pnu_quarter_1f_upper.csv (UTF-8 BOM, 열람용)

각 PNU에 대해 dedup 원본의 도시·구시군·읍면동·지번, X/Y좌표(중앙값), 건물명(대표 1건)을 붙여
지도 매핑·용도지역 스크리닝에 쓸 수 있게 합니다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
IN_PARQUET = ROOT / "2_processed" / "화성시_동탄구_상가데이터_임대료_dedup.parquet"
OUT_PARQUET = ROOT / "2_processed" / "rent_pnu_quarter_1f_upper.parquet"
OUT_CSV = ROOT / "2_processed" / "rent_pnu_quarter_1f_upper.csv"

# dedup에 있는 주소·좌표·표시용 건물명 (Parquet 스키마와 일치)
META_COLS = ["도시", "구시군", "읍면동", "지번", "X좌표", "Y좌표", "건물명"]


def first_non_null(series: pd.Series) -> object:
    """같은 PNU 내 여러 매물 중 해당 필드의 첫 비결측값."""
    s = series.dropna()
    if s.empty:
        return pd.NA
    v = s.iloc[0]
    if isinstance(v, str):
        v = v.strip()
        return v if v else pd.NA
    return v


def build_pnu_attributes(df: pd.DataFrame) -> pd.DataFrame:
    """PNU별 대표 주소·좌표·건물명 (좌표는 건물별 미세 편차 시 중앙값)."""
    g = df.groupby("PNU코드", as_index=False).agg(
        도시=("도시", first_non_null),
        구시군=("구시군", first_non_null),
        읍면동=("읍면동", first_non_null),
        지번=("지번", first_non_null),
        X좌표=("X좌표", "median"),
        Y좌표=("Y좌표", "median"),
        건물명=("건물명", first_non_null),
    )
    # 지도·검색용 한 줄 주소 (결측 제외 후 공백 결합)
    def join_addr(row: pd.Series) -> str:
        parts = []
        for c in ("도시", "구시군", "읍면동", "지번"):
            v = row[c]
            if pd.notna(v) and str(v).strip():
                parts.append(str(v).strip())
        return " ".join(parts) if parts else ""

    g["주소_통합"] = g.apply(join_addr, axis=1)
    return g


def parse_current_floor(raw: object) -> int | None:
    """
    층정보에서 '현재 층'만 추출.
    예: '3/7' -> 3, '1/12' -> 1, '15/20' -> 15, 'B1/20' -> None (지하 제외)
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip()
    if not s:
        return None
    head = s.split("/")[0].strip()
    if re.match(r"^[Bb]", head):
        return None
    try:
        # '1.0' 등 방어
        return int(float(head))
    except ValueError:
        return None


def floor_band(current: int | None) -> str | None:
    """1층 / 3층 이상만 사용. 2층·기타는 None."""
    if current is None:
        return None
    if current == 1:
        return "1F"
    if current >= 3:
        return "3F_PLUS"
    return None


def add_quarter_column(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """매물게시일(YYYYMMDD 정수 또는 문자열) -> year_quarter 'YYYYQX'. 파싱 실패 행은 제거."""
    out = df.copy()
    s = out["매물게시일"].astype(str).str.strip()
    dt = pd.to_datetime(s, format="%Y%m%d", errors="coerce")
    bad = int(dt.isna().sum())
    out = out.loc[dt.notna()].copy()
    dt_ok = dt[dt.notna()]
    y = dt_ok.dt.year.astype(int)
    q = dt_ok.dt.quarter.astype(int)
    out["year_quarter"] = y.astype(str) + "Q" + q.astype(str)
    return out, bad


def main() -> None:
    if not IN_PARQUET.exists():
        raise SystemExit(f"입력 Parquet 없음: {IN_PARQUET}")

    import pyarrow.parquet as pq

    cols_set = set(pq.read_schema(IN_PARQUET).names)
    if "평당월임대료_만원" not in cols_set:
        raise SystemExit(
            "입력에 `평당월임대료_만원` 컬럼이 없습니다. 먼저 실행하세요:\n"
            "  python scripts/add_pyung_rent_columns.py"
        )

    usecols = ["PNU코드", "매물게시일", "층정보", "평당월임대료_만원", *META_COLS]
    df = pd.read_parquet(IN_PARQUET, columns=usecols)

    df["PNU코드"] = df["PNU코드"].astype(str).str.strip()
    # PNU별 지도·주소 속성 (전체 매물 기준으로 대표값 추출)
    pnu_attr = build_pnu_attributes(df)

    df = df.dropna(subset=["PNU코드", "매물게시일", "평당월임대료_만원"])

    df, bad_dates = add_quarter_column(df)
    if bad_dates:
        print(f"경고: 매물게시일 파싱 실패 행수 = {bad_dates:,} (집계에서 제외됨)")

    df["_current_floor"] = df["층정보"].map(parse_current_floor)
    df["_floor_band"] = df["_current_floor"].map(floor_band)
    df = df.dropna(subset=["_floor_band"])

    # 평당 월 임대료(만 원/평): 월환산(보증금 연 5%÷12 + 월세) 후 전용면적 평으로 나눈 값
    g = (
        df.groupby(["PNU코드", "year_quarter", "_floor_band"], observed=True)["평당월임대료_만원"]
        .agg(
            평당월임대료_평균="mean",
            평당월임대료_중위="median",
            n_listings="count",
        )
        .reset_index()
        .rename(columns={"_floor_band": "floor_band"})
        .sort_values(["PNU코드", "year_quarter", "floor_band"])
    )

    g = g.merge(pnu_attr, on="PNU코드", how="left")

    # 열 순서: 식별·위치 → 시계열·층 → 통계
    head_cols = [
        "PNU코드",
        "도시",
        "구시군",
        "읍면동",
        "지번",
        "주소_통합",
        "X좌표",
        "Y좌표",
        "건물명",
        "year_quarter",
        "floor_band",
    ]
    tail_cols = ["평당월임대료_평균", "평당월임대료_중위", "n_listings"]
    g = g[[c for c in head_cols + tail_cols if c in g.columns]]

    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    g.to_parquet(OUT_PARQUET, index=False, engine="pyarrow")
    g.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    print(f"1F·3F+ 대상 매물 행수: {len(df):,} (일자·평당임대료·층구분 유효)")
    print(f"집계 행수 (PNU×분기×층구분): {len(g):,}")
    print(f"저장 Parquet: {OUT_PARQUET}")
    print(f"저장 CSV: {OUT_CSV}")


if __name__ == "__main__":
    main()
