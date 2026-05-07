# -*- coding: utf-8 -*-
"""
dedup Parquet의 PNU별 대표 좌표(WGS84)에 대해 공간 조인으로 속성을 붙입니다.

  - 법정동: 경기 법정동경계 (EPSG:5186), 시군구 필터 기본값 화성시 41590
  - 행정동: 전국 행정동경계에서 같은 시군구 접두로 필터 후 조인 (EPSG:5186)
  - 용도(국토계획 도시지역 UQ111, EPSG:5174 → 5186 변환), 시군구 41590 필터

출력: 2_processed/pnu_spatial_attributes.parquet (+ .csv)
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
DEDUP_PARQUET = ROOT / "2_processed" / "화성시_동탄구_상가데이터_임대료_dedup.parquet"

SHP_LEGAL = ROOT / "1_raw" / "법정동경계" / "LSMD_ADM_SECT_UMD_경기" / "LSMD_ADM_SECT_UMD_41_202604.shp"
SHP_ADM = ROOT / "1_raw" / "행정동경계" / "BND_ADM_DONG_PG" / "BND_ADM_DONG_PG.shp"
SHP_LANDUSE = (
    ROOT
    / "1_raw"
    / "국토계획도시지역"
    / "LSMD_CONT_UQ111_5174_경기"
    / "LSMD_CONT_UQ111_5174_41_202604.shp"
)

OUT_PARQUET = ROOT / "2_processed" / "pnu_spatial_attributes.parquet"
OUT_CSV = ROOT / "2_processed" / "pnu_spatial_attributes.csv"

WORK_CRS = "EPSG:5186"  # 행정·법정 shp 기준
# 경기 법정동 DBF는 CP949/EUC-KR — 미지정 시 latin1로 깨짐(모지바케)
SHP_LEGAL_ENCODING = "cp949"


def first_non_null(s: pd.Series) -> object:
    u = s.dropna()
    if u.empty:
        return pd.NA
    v = u.iloc[0]
    if isinstance(v, str):
        v = v.strip()
        return v if v else pd.NA
    return v


def load_pnu_points(parquet_path: Path) -> gpd.GeoDataFrame:
    df = pd.read_parquet(parquet_path, columns=["PNU코드", "X좌표", "Y좌표", "읍면동"])
    df["PNU코드"] = df["PNU코드"].astype(str).str.strip()
    agg = (
        df.groupby("PNU코드", as_index=False)
        .agg(X좌표=("X좌표", "median"), Y좌표=("Y좌표", "median"), 읍면동_원본=("읍면동", first_non_null))
    )
    agg = agg.dropna(subset=["X좌표", "Y좌표"])
    gdf = gpd.GeoDataFrame(
        agg,
        geometry=gpd.points_from_xy(agg["X좌표"], agg["Y좌표"]),
        crs="EPSG:4326",
    )
    return gdf.to_crs(WORK_CRS)


def sjoin_one_to_one(
    points: gpd.GeoDataFrame,
    polys: gpd.GeoDataFrame,
    poly_cols: list[str],
    prefix: str,
) -> pd.DataFrame:
    """points: PNU코드 + geometry. 반환: PNU코드 + poly_cols (중복 PNU는 첫 매칭만)."""
    use = polys[poly_cols + ["geometry"]].copy()
    j = gpd.sjoin(points[["PNU코드", "geometry"]], use, how="left", predicate="within")
    j = j.drop(columns=["index_right"], errors="ignore")
    # 동일 폴리곤 중복 등 방지
    j = j.drop_duplicates(subset=["PNU코드"], keep="first")
    rename = {c: f"{prefix}{c}" for c in poly_cols}
    return j.drop(columns=["geometry"]).rename(columns=rename)


def sjoin_landuse(points: gpd.GeoDataFrame, land_gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    lu = land_gdf.to_crs(WORK_CRS)
    cols = ["ALIAS", "MNUM", "REMARK", "NTFDATE", "COL_ADM_SE"]
    cols = [c for c in cols if c in lu.columns]
    use = lu[cols + ["geometry"]].copy()
    j = gpd.sjoin(points[["PNU코드", "geometry"]], use, how="left", predicate="within")
    j = j.drop(columns=["index_right"], errors="ignore")
    j = j.drop_duplicates(subset=["PNU코드"], keep="first")
    out = j.drop(columns=["geometry"])
    out = out.rename(
        columns={
            "ALIAS": "용도지역_ALIAS",
            "MNUM": "용도지역_MNUM",
            "REMARK": "용도지역_REMARK",
            "NTFDATE": "용도지역_고시일자",
            "COL_ADM_SE": "용도_시군구코드",
        }
    )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="PNU 좌표에 행정·법정·용도지역 공간 조인")
    parser.add_argument(
        "--sigungu",
        default="41590",
        help="시군구코드(5자리). 기본 화성시 41590",
    )
    parser.add_argument("--no-csv", action="store_true")
    parser.add_argument(
        "--adm-buffer-m",
        type=float,
        default=3000.0,
        help="행정동 후보 추출 시 포인트 범위 확장(미터, EPSG:5186)",
    )
    args = parser.parse_args()
    sigungu = str(args.sigungu).strip()

    for p in (DEDUP_PARQUET, SHP_LEGAL, SHP_ADM, SHP_LANDUSE):
        if not p.exists():
            raise SystemExit(f"파일 없음: {p}")

    pts = load_pnu_points(DEDUP_PARQUET)
    print(f"PNU 고유 지점 수: {len(pts):,}")

    legal = gpd.read_file(SHP_LEGAL, encoding=SHP_LEGAL_ENCODING)
    legal_hw = legal[legal["COL_ADM_SE"].astype(str) == sigungu].copy()
    print(f"법정동 폴리곤(시군구 {sigungu}): {len(legal_hw):,}")

    adm = gpd.read_file(SHP_ADM)
    # 행정동 ADM_CD 체계는 시군구 5자리 접두와 일치하지 않을 수 있음 → 포인트 범위(버퍼)로 후보 축소
    minx, miny, maxx, maxy = pts.total_bounds
    margin_m = float(args.adm_buffer_m)
    search_poly = box(minx - margin_m, miny - margin_m, maxx + margin_m, maxy + margin_m)
    adm_hw = adm[adm.geometry.intersects(search_poly)].copy()
    print(
        f"행정동 폴리곤(연구지역 버퍼 {margin_m:.0f}m 교차): {len(adm_hw):,}"
    )

    land = gpd.read_file(SHP_LANDUSE)
    land_hw = land[land["COL_ADM_SE"].astype(str) == sigungu].copy()
    print(f"용도지역 UQ111 폴리곤(시군구 {sigungu}): {len(land_hw):,}")

    base = pts[["PNU코드", "X좌표", "Y좌표", "읍면동_원본"]].copy()

    leg_tbl = sjoin_one_to_one(pts, legal_hw, ["EMD_CD", "EMD_NM", "COL_ADM_SE"], "법정동_")
    leg_tbl = leg_tbl.rename(
        columns={
            "법정동_EMD_CD": "법정동코드",
            "법정동_EMD_NM": "법정동명",
            "법정동_COL_ADM_SE": "법정동_시군구코드",
        }
    )

    adm_tbl = sjoin_one_to_one(pts, adm_hw, ["ADM_CD", "ADM_NM", "BASE_DATE"], "행정동_")
    adm_tbl = adm_tbl.rename(
        columns={
            "행정동_ADM_CD": "행정동코드",
            "행정동_ADM_NM": "행정동명",
            "행정동_BASE_DATE": "행정동_기준일자",
        }
    )

    lu_tbl = sjoin_landuse(pts, land_hw)

    out = base.merge(leg_tbl, on="PNU코드", how="left")
    out = out.merge(adm_tbl, on="PNU코드", how="left")
    out = out.merge(lu_tbl, on="PNU코드", how="left")

    def blank_series(c: str) -> pd.Series:
        return out[c].isna() | (out[c].astype(str).str.strip() == "")

    for col, label in [
        ("법정동명", "법정동 미매칭"),
        ("행정동명", "행정동 미매칭"),
    ]:
        miss = blank_series(col)
        n = int(miss.sum())
        print(f"{label}: {n:,} ({100 * n / len(out):.2f}%)")

    lu_miss = blank_series("용도지역_MNUM")
    n_lu = int(lu_miss.sum())
    print(f"용도 폴리곤 미매칭(MNUM 없음): {n_lu:,} ({100 * n_lu / len(out):.2f}%)")

    alias_blank = (~lu_miss) & blank_series("용도지역_ALIAS")
    na = int(alias_blank.sum())
    print(f"용도 폴리곤은 있으나 ALIAS 공란: {na:,} ({100 * na / len(out):.2f}%)")

    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT_PARQUET, index=False, engine="pyarrow")
    print(f"저장: {OUT_PARQUET}")
    if not args.no_csv:
        out.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
        print(f"저장: {OUT_CSV}")


if __name__ == "__main__":
    main()
