# -*- coding: utf-8 -*-
"""
화성시 동탄구 상가 임대료 탐색 대시보드.

실행 (프로젝트 루트에서):
  python -m streamlit run dashboard/app.py

필요 패키지: streamlit, pandas, pyarrow, plotly, folium, streamlit-folium, numpy
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

ROOT = Path(__file__).resolve().parents[1]
PATH_TS = ROOT / "2_processed" / "rent_pnu_quarter_1f_upper.parquet"
PATH_SP = ROOT / "2_processed" / "pnu_spatial_attributes.parquet"
PATH_EMD_GEOJSON = ROOT / "2_processed" / "dongtan_emd_boundary.geojson"
PATH_LANDUSE_GEOJSON = ROOT / "2_processed" / "hwaseong_landuse_uq111.geojson"

# 차트·UI 통일 폰트 (CDN 로드)
FONT_FAMILY = "NanumSquare, sans-serif"

# 지도 위 건물(PNU) 점 공통 색 — 용도 구분은 폴리곤 레이어에서 표현
BUILDING_MARKER_COLOR = "#2563eb"

# 법정동 여러 개 선택 시 순서대로 할당 (Plotly 기본 팔레트와 실제 동 매칭 혼동 방지)
DONG_LINE_COLORS = ["#2563eb", "#ea580c", "#dc2626", "#059669", "#7c3aed", "#ca8a04", "#0891b2", "#db2777"]


def inject_nanumsquare_styles() -> None:
    """Streamlit 전역 UI에 나눔스퀘어 적용."""
    st.markdown(
        f"""
        <style>
        @import url('https://cdn.jsdelivr.net/gh/moonspam/NanumSquare@2.0/nanumsquare.css');
        html, body, input, textarea, button {{
            font-family: {FONT_FAMILY} !important;
        }}
        .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"], section[data-testid="stSidebar"] {{
            font-family: {FONT_FAMILY} !important;
        }}
        .stMarkdown, .stCaption, label, [data-testid="stMetricValue"], .dataframe {{
            font-family: {FONT_FAMILY} !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data
def load_merged() -> pd.DataFrame:
    if not PATH_TS.exists():
        raise FileNotFoundError(f"없음: {PATH_TS}")
    ts = pd.read_parquet(PATH_TS)
    if PATH_SP.exists():
        sp = pd.read_parquet(PATH_SP)
        keep = [
            "PNU코드",
            "읍면동_원본",
            "법정동명",
            "행정동명",
            "행정동코드",
            "용도지역_ALIAS",
            "용도지역_MNUM",
        ]
        keep = [c for c in keep if c in sp.columns]
        ts = ts.merge(sp[keep], on="PNU코드", how="left")
    else:
        st.warning("`pnu_spatial_attributes.parquet` 없음 → 행정동·법정동·용도 필터 비활성. `scripts/join_pnu_spatial_attributes.py` 실행.")
        ts["행정동명"] = pd.NA
        ts["법정동명"] = pd.NA
        ts["용도지역_ALIAS"] = pd.NA
    ts["용도표시"] = (
        ts["용도지역_ALIAS"]
        .fillna("")
        .astype(str)
        .str.strip()
        .replace("", "(용도명 없음)")
    )
    return ts


@st.cache_data(show_spinner=False)
def load_dongtan_emd_boundary_geojson() -> dict | None:
    """미리 생성한 동탄 법정동 경계 GeoJSON 로드."""
    if not PATH_EMD_GEOJSON.exists():
        return None
    try:
        return json.loads(PATH_EMD_GEOJSON.read_text(encoding="utf-8"))
    except Exception:
        return None


@st.cache_data(show_spinner=False)
def load_hwaseong_landuse_geojson() -> dict | None:
    """국토계획 도시지역 UQ111(화성 41590) GeoJSON — 지적도 스타일 채색용."""
    if not PATH_LANDUSE_GEOJSON.exists():
        return None
    try:
        return json.loads(PATH_LANDUSE_GEOJSON.read_text(encoding="utf-8"))
    except Exception:
        return None


def landuse_polygon_style(alias: str | None) -> dict:
    """
    ALIAS(용도지역명) 키워드로 면 채색 — 실제 지적/도시계획도와 다를 수 있음(UQ111 참고용).
    순서: '준주거'를 '주거'보다 먼저 검사 (문자열 포함 관계).
    """
    a = (alias or "").strip()
    outline = "#475569"
    # 상업계
    if "상업" in a:
        fill = "#fecaca"
    elif "준주거" in a:
        fill = "#fde68a"
    elif "녹지" in a:
        fill = "#86efac"
    elif any(k in a for k in ("공업", "산업", "유통")):
        fill = "#cbd5e1"
    elif "공원" in a:
        fill = "#a7f3d0"
    elif "보전" in a or "개발제한" in a:
        fill = "#d6d3d1"
    elif "주거" in a:
        fill = "#bbf7d0"
    elif any(k in a for k in ("벌터", "농림", "농업")):
        fill = "#e7e5e4"
    else:
        fill = "#e5e7eb"
    return {
        "fillColor": fill,
        "color": outline,
        "weight": 0.6,
        "fillOpacity": 0.4,
        "opacity": 0.88,
    }


def q_sort_key(x: str) -> int:
    """'2024Q1' 분기 문자열 정렬용."""
    try:
        y, q = str(x).upper().split("Q")
        return int(y) * 10 + int(q)
    except Exception:
        return 0


def weighted_avg(group: pd.DataFrame, val_col: str) -> float:
    """분기·층 단위 가중 평균 (가중치 n_listings)."""
    g = group.dropna(subset=[val_col])
    if g.empty:
        return np.nan
    w = g["n_listings"].clip(lower=1).astype(float)
    return float(np.average(g[val_col].astype(float), weights=w))


def quarterly_xy(df_fb: pd.DataFrame, val_col: str) -> tuple[list[str], list[float], list[int]]:
    """
    분기 순 정렬된 x·y와, 해당 분기·동(또는 필터) 안에서의 매물 건수 합계.
    가중평균이 급변할 때 분기별 표본 규모를 호버로 확인하기 위함.
    """
    if df_fb.empty:
        return [], [], []
    xs: list[str] = []
    ys: list[float] = []
    ns: list[int] = []
    for yq in sorted(df_fb["year_quarter"].astype(str).unique(), key=q_sort_key):
        g = df_fb[df_fb["year_quarter"].astype(str) == yq]
        if g.empty:
            continue
        v = weighted_avg(g, val_col)
        if np.isnan(v):
            continue
        xs.append(yq)
        ys.append(v)
        ns.append(int(g["n_listings"].fillna(0).astype(np.int64).sum()))
    return xs, ys, ns


def plot_floor_by_dong(
    dff: pd.DataFrame,
    floor_band: str,
    title: str,
    emd_pick: list[str],
    val_col: str,
    height: int = 420,
) -> None:
    """법정동 미선택 시 '전체' 1선; 선택 시 동별로 범례·라인 추가."""
    sub = dff[dff["floor_band"] == floor_band].copy()
    st.markdown(f"##### {title}")
    if sub.empty:
        st.info("조건에 맞는 데이터가 없습니다.")
        return

    fig = go.Figure()
    if emd_pick:
        for i, dong in enumerate(emd_pick):
            part = sub[sub["법정동명"].astype(str) == dong]
            xs, ys, ns = quarterly_xy(part, val_col)
            if not xs:
                continue
            color = DONG_LINE_COLORS[i % len(DONG_LINE_COLORS)]
            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=ys,
                    mode="lines+markers",
                    name=dong,
                    line=dict(color=color),
                    marker=dict(color=color),
                    customdata=ns,
                    hovertemplate=(
                        f"<b>{dong}</b><br>"
                        "분기=%{x}<br>"
                        + val_col
                        + "=%{y:.2f}<br>"
                        "해당 분기 매물 건수 합=%{customdata}<extra></extra>"
                    ),
                )
            )
    else:
        xs, ys, ns = quarterly_xy(sub, val_col)
        if xs:
            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=ys,
                    mode="lines+markers",
                    name="전체",
                    customdata=ns,
                    hovertemplate=(
                        "분기=%{x}<br>"
                        + val_col
                        + "=%{y:.2f}<br>"
                        "해당 분기 매물 건수 합=%{customdata}<extra></extra>"
                    ),
                )
            )

    if not fig.data:
        st.info("표시할 분기 데이터가 없습니다.")
        return

    lay = dict(
        margin=dict(l=10, r=10, t=24, b=10),
        yaxis_title="만 원/평",
        xaxis_title="분기",
        hovermode="x unified",
        height=height,
        font=dict(family="NanumSquare", size=12),
        legend=dict(font=dict(family="NanumSquare", size=11)),
    )
    if emd_pick:
        lay["legend_title_text"] = "법정동"
    fig.update_layout(**lay)
    st.plotly_chart(fig, use_container_width=True)


def rent_summary_pool(dff: pd.DataFrame) -> tuple[float, float, int]:
    """
    필터 적용 행 기준 평당(만 원/평) 요약.
    - 평균: 셀의 평균값을 매물 건수(n_listings)로 가중 평균.
    - 중위: 셀의 중위값을 매물 건수만큼 반복한 분포의 중앙값(규모가 크면 가중치 스케일링).
    """
    if dff.empty:
        return float("nan"), float("nan"), 0
    d = dff.dropna(subset=["평당월임대료_평균", "평당월임대료_중위", "n_listings"]).copy()
    d = d[d["n_listings"].fillna(0) > 0]
    if d.empty:
        return float("nan"), float("nan"), 0
    w = d["n_listings"].clip(lower=1).astype(float)
    mean_v = float(np.average(d["평당월임대료_평균"].astype(float), weights=w))
    v = d["평당월임대료_중위"].astype(float).values
    wi = d["n_listings"].fillna(0).clip(lower=0).astype(np.int64).values
    tw = int(wi.sum())
    if tw <= 0:
        return mean_v, float("nan"), 0
    max_total = 2_000_000
    if tw > max_total:
        scale = max_total / tw
        wi = np.maximum((wi * scale).astype(np.int64), np.where(wi > 0, 1, 0).astype(np.int64))
    pool = np.repeat(v, wi)
    med_v = float(np.median(pool)) if len(pool) else float("nan")
    return mean_v, med_v, tw


def build_folium_map(df_pnu: pd.DataFrame):
    import folium

    center_lat, center_lon = 37.2, 127.1
    zoom = 11
    if not df_pnu.empty:
        center_lat = float(df_pnu["Y좌표"].median())
        center_lon = float(df_pnu["X좌표"].median())
        zoom = 13

    m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom, tiles="cartodbpositron")

    # 1) 바닥 레이어: 도시계획 용도(UQ111) 면 채색 — 지적도처럼 배경에 용도 구역 표시
    lu_geo = load_hwaseong_landuse_geojson()
    if lu_geo:
        folium.GeoJson(
            lu_geo,
            name="도시계획 용도(UQ111 · 참고)",
            style_function=lambda feat: landuse_polygon_style(feat["properties"].get("ALIAS")),
            tooltip=folium.GeoJsonTooltip(
                fields=["ALIAS", "MNUM"],
                aliases=["용도(ALIAS):", "관리번호:"],
                sticky=False,
                localize=False,
            ),
        ).add_to(m)

    # 2) 동탄 법정동 경계
    emd_geo = load_dongtan_emd_boundary_geojson()
    if emd_geo:
        folium.GeoJson(
            emd_geo,
            name="법정동 경계(동탄)",
            style_function=lambda _feat: {
                "fillColor": "#60a5fa",
                "color": "#1e40af",
                "weight": 1.5,
                "fillOpacity": 0.07,
                "opacity": 0.95,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["EMD_NM"],
                aliases=["법정동명:"],
                sticky=False,
                localize=False,
            ),
        ).add_to(m)

    # 3) 줌 레벨에 따라 군집 ↔ 개별 점 전환 (MarkerCluster); 건물 색은 단일색
    pnu_unique = df_pnu.drop_duplicates(subset=["PNU코드"]).copy()
    cluster = MarkerCluster(name="건물 위치(PNU)")
    cluster.add_to(m)

    for _, r in pnu_unique.iterrows():
        tip = (
            f"{r.get('PNU코드','')}<br/>"
            f"법정동 {r.get('법정동명','') or '-'}<br/>"
            f"행정동 {r.get('행정동명','') or '-'}<br/>"
            f"{r.get('용도표시','')}"
        )
        folium.CircleMarker(
            location=[float(r["Y좌표"]), float(r["X좌표"])],
            radius=5,
            popup=folium.Popup(tip, max_width=320),
            color=BUILDING_MARKER_COLOR,
            fill_color=BUILDING_MARKER_COLOR,
            fill=True,
            fill_opacity=0.65,
            weight=1,
        ).add_to(cluster)

    folium.LayerControl().add_to(m)
    return m


def main() -> None:
    st.set_page_config(page_title="동탄구 상가 임대료", layout="wide")
    inject_nanumsquare_styles()
    st.title("화성시 동탄구 상가 임대료 탐색")
    st.caption("단위: 평당 월 임대료(만 원/평), 보증금 연 5%÷12 환산 반영")

    try:
        df = load_merged()
    except FileNotFoundError as e:
        st.error(str(e))
        return

    # --- 사이드바 필터
    with st.sidebar:
        st.header("필터")
        quarters = sorted(df["year_quarter"].astype(str).unique(), key=q_sort_key)
        q_pick = st.multiselect("분기 (비우면 전체)", options=quarters, default=[])

        emd_vals = sorted(x for x in df["법정동명"].dropna().unique() if str(x).strip())
        emd_pick = st.multiselect("법정동 (비우면 전체)", options=emd_vals, default=[])

        adm_vals = sorted(x for x in df["행정동명"].dropna().unique() if str(x).strip())
        adm_pick = st.multiselect("행정동 (비우면 전체)", options=adm_vals, default=[])

        lu_vals = sorted(df["용도표시"].unique())
        lu_pick = st.multiselect("용도 구분(ALIAS)", options=lu_vals, default=[])

        metric_label = st.radio("추이 그래프 지표", options=["평균(가중)", "중위(가중)"], horizontal=True)

    dff = df.copy()
    if q_pick:
        dff = dff[dff["year_quarter"].astype(str).isin(q_pick)]
    if emd_pick:
        dff = dff[dff["법정동명"].isin(emd_pick)]
    if adm_pick:
        dff = dff[dff["행정동명"].isin(adm_pick)]
    if lu_pick:
        dff = dff[dff["용도표시"].isin(lu_pick)]

    val_col = "평당월임대료_평균" if metric_label.startswith("평균") else "평당월임대료_중위"

    show_cols = [
        "PNU코드",
        "year_quarter",
        "floor_band",
        "평당월임대료_평균",
        "평당월임대료_중위",
        "n_listings",
        "법정동명",
        "행정동명",
        "용도표시",
        "주소_통합",
    ]
    show_cols = [c for c in show_cols if c in dff.columns]

    col_map, col_charts = st.columns([1.15, 1.0], gap="medium")

    with col_map:
        st.markdown("##### 지도")
        pnu_map_src = dff.drop_duplicates(subset=["PNU코드"])
        st.caption(
            f"필터 적용 PNU {len(pnu_map_src):,}개 · 배경 면색은 국토계획 도시지역 UQ111(화성) 참고용이며 실제 지적·행위제한과 다를 수 있습니다. "
            "점은 동일 색, 줌에 따라 군집됩니다."
        )
        m = build_folium_map(pnu_map_src)
        st_folium(m, width=None, height=580, returned_objects=[])

    with col_charts:
        st.caption(
            "법정동을 여러 개 선택하면 동마다 선·범례가 추가됩니다. 비우면 「전체」 한 줄입니다."
        )
        # 와이어프레임: 우측 위 → 3층 이상, 우측 아래 → 1층
        plot_floor_by_dong(dff, "3F_PLUS", "3층 이상 그래프", emd_pick, val_col, height=268)
        plot_floor_by_dong(dff, "1F", "1층 그래프", emd_pick, val_col, height=268)

    st.divider()
    mean_py, med_py, n_pool = rent_summary_pool(dff)
    st.markdown("##### 임대료 요약 (필터 적용 · 평당 월 임대, 만 원/평)")
    s1, s2, s3 = st.columns(3)
    s1.metric(
        "평균 (가중)",
        "—" if np.isnan(mean_py) else f"{mean_py:,.2f}",
        help="각 시계열 셀의 평균값을 매물 건수(n_listings)로 가중한 값",
    )
    s2.metric(
        "중위 (매물건수 반영)",
        "—" if np.isnan(med_py) else f"{med_py:,.2f}",
        help="각 셀 중위값을 매물 건수만큼 반복한 분포의 중앙값(대략적)",
    )
    s3.metric("가중 매물 건수 합", "—" if n_pool == 0 else f"{n_pool:,}")

    st.divider()
    st.markdown("##### 표")
    tbl = dff[show_cols].copy()
    if not tbl.empty and "year_quarter" in tbl.columns:
        tbl["_ord"] = tbl["year_quarter"].astype(str).map(q_sort_key)
        sort_by = ["_ord", "floor_band"]
        if "법정동명" in tbl.columns:
            sort_by.append("법정동명")
        tbl = tbl.sort_values(sort_by, ascending=True).drop(columns=["_ord"])

    st.dataframe(tbl.head(1500), use_container_width=True, hide_index=True)

    with st.expander("친구에게 화면 공유하려면?"):
        st.markdown(
            """
Streamlit 앱은 **단일 HTML 파일로 저장해 보내는 방식**과 맞지 않습니다.  
**로컬 주소(`localhost`)** 는 본인 PC 안에서만 열립니다.

**가능한 방법**
- 같은 와이파이에서 **PC IP:포트** 로 접속 (방화벽 허용 필요)
- **ngrok**, **Cloudflare Tunnel** 등으로 임시 공개 URL
- **Streamlit Community Cloud** 등에 배포 — 저장소 루트의 `DEPLOY.md` 에 단계별 안내가 있습니다.

정적인 지도·그래프만 HTML로 뽑을 때는 Plotly/Folium 각각 `write_html` 이 가능하지만, 이 대시보드 전체는 서버가 필요합니다.
            """
        )

    st.divider()
    st.markdown("##### 요약")
    c1, c2, c3 = st.columns(3)
    c1.metric("필터 후 시계열 행 수", f"{len(dff):,}")
    c2.metric("고유 PNU 수", f"{dff['PNU코드'].nunique():,}")
    c3.metric("포함 분기 수", f"{dff['year_quarter'].nunique():,}")


if __name__ == "__main__":
    main()
