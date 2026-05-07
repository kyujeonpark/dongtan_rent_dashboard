# 동탄구 상가 임대료 대시보드 배포 안내

앱 진입점: `dashboard/app.py`  
필수 데이터(저장소에 포함): `2_processed/` 내 아래 네 파일

- `rent_pnu_quarter_1f_upper.parquet`
- `pnu_spatial_attributes.parquet`
- `dongtan_emd_boundary.geojson`
- `hwaseong_landuse_uq111.geojson`

의존성: 저장소 루트 `requirements.txt` 또는 `dashboard/requirements.txt`(내용 동일).

---

## Streamlit Community Cloud (무료·추천)

1. [GitHub](https://github.com)에 새 저장소를 만들고, 이 폴더를 푸시합니다.  
   - `.gitignore` 때문에 `1_raw`, CSV/XLSX·dedup 계열은 제외됩니다.
2. [share.streamlit.io](https://share.streamlit.io) 로그인 후 **New app** 을 누릅니다.
3. 저장소·브랜치를 고르고 설정합니다.
   - **Main file path**: `dashboard/app.py`
   - **Requirements file**: 루트면 `requirements.txt`, 또는 Advanced에서 `dashboard/requirements.txt`
4. **Deploy**. 빌드가 끝나면 공개 URL이 생성됩니다.

문제가 나면 Cloud 로그에서 `ModuleNotFoundError` 여부를 확인하고, `requirements.txt`에 패키지가 빠지지 않았는지 봅니다.

---

## 로컬에서 배포 전 확인

프로젝트 루트에서:

```bash
python -m pip install -r requirements.txt
python -m streamlit run dashboard/app.py
```

---

## 데이터만 바꿔 재배포할 때

집계 스크립트를 다시 돌린 뒤 위 네 개 파일만 갱신하고 Git에 커밋·푸시하면 Cloud가 자동으로 재배포합니다(App 설정에 따라 수동 Redeploy일 수 있음).
