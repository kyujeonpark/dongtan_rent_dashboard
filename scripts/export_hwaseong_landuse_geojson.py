# -*- coding: utf-8 -*-
"""
국토계획 도시지역 UQ111(화성 41590) 폴리곤을 WGS84 GeoJSON으로 내보냅니다.
대시보드에서 geopandas 없이 Folium 오버레이로 사용합니다.

실행: python scripts/export_hwaseong_landuse_geojson.py
출력: 2_processed/hwaseong_landuse_uq111.geojson
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHP = (
    ROOT
    / "1_raw"
    / "국토계획도시지역"
    / "LSMD_CONT_UQ111_5174_경기"
    / "LSMD_CONT_UQ111_5174_41_202604.shp"
)
OUT = ROOT / "2_processed" / "hwaseong_landuse_uq111.geojson"
SIGUNGU = "41590"


def main() -> None:
    import geopandas as gpd

    if not SHP.exists():
        raise SystemExit(f"shp 없음: {SHP}")
    gdf = gpd.read_file(SHP, encoding="cp949")
    gdf = gdf[gdf["COL_ADM_SE"].astype(str) == SIGUNGU].copy()
    cols = [c for c in ("ALIAS", "MNUM", "REMARK", "NTFDATE", "COL_ADM_SE", "geometry") if c in gdf.columns]
    gdf = gdf[cols]
    gdf = gdf.to_crs(4326)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(gdf.to_json(), encoding="utf-8")
    print(f"features: {len(gdf):,}")
    print(f"저장: {OUT}")


if __name__ == "__main__":
    main()
