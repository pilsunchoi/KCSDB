"""
03b_build_dims.py
=================

DuckDB에 dim 테이블 3개를 생성한다.

03a_diagnose_dims.py 진단 결과를 기반으로 다음 사안이 모두 확정된 상태:
- A (코드 통합):  외교부 244 = 관세청 244, 모두 'both'. 단 컬럼은 유지.
- B (한국어 국명): 240개 중 85개 차이 → 양쪽 보존 (name_ko_mofa, name_ko_kcs)
- C (stat_kor 변동): 변동 0건 → 단일 컬럼
- D (HS 개정): yyyymm 기반 단순 도출 (2007/2012/2017/2022 발효일 1.1)
- E (dim 자릿수): dim_hs10 + dim_hs2
- F (대륙 보존): 3컬럼 모두 (continent_en/admin/mofa)
- G (특수 코드): EU/KR/KP 모두 포함 + 플래그 (is_country, is_self)
- H (dim_hs2): description_ko/section은 NULL (외부 자료 후속)
- I (hs_version): first/last 두 컬럼 보존

생성 테이블:
- dim_country (244행, EU·XK·KR·KP 포함 + 플래그)
- dim_hs10    (15,403행 + first/last yyyymm + hs_version)
- dim_hs2     (~98행, description_ko는 NULL)

검증:
- fact_trade.stat_cd → dim_country 매칭률
- fact_total.stat_cd → dim_country 매칭률
- meta_calls.stat_cd → dim_country 매칭률
- fact_trade.hs10    → dim_hs10 매칭률
- fact_trade.hs2     → dim_hs2 매칭률

이 스크립트는 DuckDB에 *쓰기*를 한다. 기존 dim 테이블이 있으면 DROP 후 재생성한다.
fact_trade, fact_total, meta_calls는 건드리지 않는다.
"""

import duckdb
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DUCKDB_PATH = PROJECT_ROOT / "data" / "processed" / "kcsdb.duckdb"
MOFA_PATH = PROJECT_ROOT / "data" / "external" / "country_codes_mofa_20251222.csv"


def _clean(v):
    """None / NaN / 'NULL' 문자열 / 빈 문자열을 모두 None으로 정리."""
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    if v == "NULL" or v == "":
        return None
    return v


def _safe_int(v):
    """None을 허용하는 안전한 int 변환."""
    v = _clean(v)
    if v is None:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def load_mofa() -> pd.DataFrame:
    """외교부 자료 로딩.

    결측 처리:
    - 함정 10: keep_default_na=False (NA=나미비아 보호)
    - ★신규 함정★: 'NULL' 문자열 결측 표시 (DB export 흔적)
    """
    df = pd.read_csv(MOFA_PATH, keep_default_na=False, encoding="utf-8")
    df = df.rename(columns={
        "국제표준화기구_2자리": "iso2",
        "국제표준화기구_3자리": "iso3",
        "국제표준화기구_숫자": "iso_num",
        "대륙명_공통 대륙코드": "continent_en",
        "대륙명_행정표준코드": "continent_admin",
        "대륙명_외교부 직제": "continent_mofa",
        "영문명": "name_en",
        "한글명": "name_ko_mofa",
    })

    # 'NULL' / '' 분포 진단 (책 13장 자료)
    null_cols = []
    for col in df.columns:
        n = int(((df[col] == "NULL") | (df[col] == "")).sum())
        if n > 0:
            null_cols.append((col, n))
    if null_cols:
        print("  외교부 자료 결측 분포 ('NULL' 또는 빈 문자열):")
        for col, n in null_cols:
            print(f"    {col}: {n}건")
        # 어느 국가가 어느 컬럼에서 결측인지 샘플 출력
        for col, _ in null_cols:
            samples = df[(df[col] == "NULL") | (df[col] == "")][
                ["iso2", "name_ko_mofa", col]
            ].head(5)
            if len(samples) > 0:
                print(f"    {col} 결측 사례:")
                for _, r in samples.iterrows():
                    print(f"      {r['iso2']} ({r['name_ko_mofa']})")
        print()

    # 'NULL' / '' → None 일괄 변환
    df = df.replace({"NULL": None, "": None})

    return df


def get_hs_version(yyyymm: int) -> str:
    """yyyymm을 HS 개정 버전 문자열로 도출.

    HS 개정 발효일 (한국 관세청 동일 적용):
      - HS2007: 2007.1.1 (본 데이터셋 시작점)
      - HS2012: 2012.1.1
      - HS2017: 2017.1.1
      - HS2022: 2022.1.1
    """
    if yyyymm >= 202201:
        return "HS2022"
    elif yyyymm >= 201701:
        return "HS2017"
    elif yyyymm >= 201201:
        return "HS2012"
    else:
        return "HS2007"


def build_dim_country(con, mofa_df):
    """dim_country 생성."""
    print("=" * 72)
    print("[1/3] dim_country 생성")
    print("=" * 72)

    # 관세청 응답 한국어 국명 (변동 0건이지만 안전 장치)
    kcs_kor = con.execute("""
        WITH freq AS (
            SELECT stat_cd, stat_kor, COUNT(*) AS n
            FROM fact_trade
            WHERE stat_kor IS NOT NULL AND stat_kor != ''
            GROUP BY stat_cd, stat_kor
        )
        SELECT stat_cd, stat_kor AS name_ko_kcs
        FROM freq
        QUALIFY ROW_NUMBER() OVER (PARTITION BY stat_cd ORDER BY n DESC) = 1
    """).fetchdf()
    kcs_kor_map = dict(zip(kcs_kor["stat_cd"], kcs_kor["name_ko_kcs"]))

    # 호출 영구 실패 코드 (XK)
    failed_set = set(con.execute("""
        SELECT DISTINCT stat_cd FROM meta_calls WHERE NOT success
        EXCEPT
        SELECT DISTINCT stat_cd FROM fact_total
    """).fetchdf()["stat_cd"].tolist())

    # 전체 시기 거래 0건 (EU, KP, KR)
    zero_trade_set = set(con.execute("""
        SELECT DISTINCT stat_cd FROM fact_total
        EXCEPT
        SELECT DISTINCT stat_cd FROM fact_trade
    """).fetchdf()["stat_cd"].tolist())

    # 코드 합집합
    mofa_set = set(mofa_df["iso2"].tolist())
    kcs_set = set(con.execute(
        "SELECT DISTINCT stat_cd FROM meta_calls"
    ).fetchdf()["stat_cd"].tolist())
    all_codes = sorted(mofa_set | kcs_set)

    # 외교부 자료를 dict로 변환 (빠른 조회)
    mofa_map = mofa_df.set_index("iso2").to_dict(orient="index")

    rows = []
    for code in all_codes:
        m = mofa_map.get(code, {})
        in_mofa = code in mofa_set
        in_kcs = code in kcs_set

        if in_mofa and in_kcs:
            source = "both"
        elif in_mofa:
            source = "mofa"
        else:
            source = "kcs"

        rows.append({
            "stat_cd": code,
            "iso3": _clean(m.get("iso3")),
            "iso_num": _safe_int(m.get("iso_num")),
            "name_ko_mofa": _clean(m.get("name_ko_mofa")),
            "name_ko_kcs": kcs_kor_map.get(code),
            "name_en": _clean(m.get("name_en")),
            "continent_en": _clean(m.get("continent_en")),
            "continent_admin": _clean(m.get("continent_admin")),
            "continent_mofa": _clean(m.get("continent_mofa")),
            "source": source,
            "is_country": code != "EU",
            "is_self": code == "KR",
            "call_status": "permanent_fail" if code in failed_set else "success",
            "has_trade": code not in (zero_trade_set | failed_set),
        })

    dim = pd.DataFrame(rows)

    con.execute("DROP TABLE IF EXISTS dim_country")
    con.register("dim_country_df", dim)
    con.execute("""
        CREATE TABLE dim_country AS
        SELECT
            stat_cd,
            iso3,
            CAST(iso_num AS INTEGER) AS iso_num,
            name_ko_mofa,
            name_ko_kcs,
            name_en,
            continent_en,
            continent_admin,
            continent_mofa,
            source,
            is_country,
            is_self,
            call_status,
            has_trade
        FROM dim_country_df
        ORDER BY stat_cd
    """)
    con.unregister("dim_country_df")

    n_rows = con.execute("SELECT COUNT(*) FROM dim_country").fetchone()[0]
    print(f"  생성 행 수: {n_rows}")
    print()

    print("  source 분포:")
    src = con.execute("""
        SELECT source, COUNT(*) AS n
        FROM dim_country
        GROUP BY source
        ORDER BY n DESC
    """).fetchdf()
    print(src.to_string(index=False))
    print()

    flags = con.execute("""
        SELECT
            SUM(CASE WHEN NOT is_country THEN 1 ELSE 0 END) AS not_country,
            SUM(CASE WHEN is_self THEN 1 ELSE 0 END) AS self_kr,
            SUM(CASE WHEN call_status = 'permanent_fail' THEN 1 ELSE 0 END) AS perm_fail,
            SUM(CASE WHEN NOT has_trade THEN 1 ELSE 0 END) AS no_trade
        FROM dim_country
    """).fetchone()
    print("  플래그 분포:")
    print(f"    is_country=FALSE:        {flags[0]} (EU)")
    print(f"    is_self=TRUE:            {flags[1]} (KR)")
    print(f"    call_status=perm_fail:   {flags[2]} (XK)")
    print(f"    has_trade=FALSE:         {flags[3]} (EU+KR+KP+XK)")
    print()


def build_dim_hs10(con):
    """dim_hs10 생성."""
    print("=" * 72)
    print("[2/3] dim_hs10 생성")
    print("=" * 72)

    # 진단 4에서 stat_kor_item 변동 0건 확인됨. MIN으로 단일값 추출.
    df = con.execute("""
        SELECT
            hs10,
            MIN(hs2) AS hs2,
            MIN(hs4) AS hs4,
            MIN(hs6) AS hs6,
            MIN(stat_kor_item) AS stat_kor_item,
            CAST(MIN(yyyymm) AS INTEGER) AS first_yyyymm,
            CAST(MAX(yyyymm) AS INTEGER) AS last_yyyymm,
            COUNT(DISTINCT stat_kor_item) AS n_kor_variants
        FROM fact_trade
        GROUP BY hs10
    """).fetchdf()

    n_total_hs10 = con.execute(
        "SELECT COUNT(DISTINCT hs10) FROM fact_trade"
    ).fetchone()[0]

    # 무결성 검증: 변동 있는 hs10 다시 확인
    n_with_variants = (df["n_kor_variants"] > 1).sum()
    if n_with_variants > 0:
        print(f"  경고: stat_kor_item 변동 있는 hs10 {n_with_variants}개 발견.")
        print("        진단 4 결과(0건)와 모순. dim 설계 재검토 필요.")
    if len(df) != n_total_hs10:
        print(f"  경고: GROUP BY 결과({len(df)}) ≠ DISTINCT hs10({n_total_hs10})")

    df["hs_version_first"] = df["first_yyyymm"].apply(get_hs_version)
    df["hs_version_last"] = df["last_yyyymm"].apply(get_hs_version)
    df = df.drop(columns=["n_kor_variants"]).sort_values("hs10").reset_index(drop=True)

    con.execute("DROP TABLE IF EXISTS dim_hs10")
    con.register("dim_hs10_df", df)
    con.execute("""
        CREATE TABLE dim_hs10 AS
        SELECT
            hs10, hs2, hs4, hs6, stat_kor_item,
            first_yyyymm, last_yyyymm,
            hs_version_first, hs_version_last
        FROM dim_hs10_df
        ORDER BY hs10
    """)
    con.unregister("dim_hs10_df")

    n_rows = con.execute("SELECT COUNT(*) FROM dim_hs10").fetchone()[0]
    print(f"  생성 행 수: {n_rows:,}")
    print()

    print("  first_yyyymm 기준 hs_version 분포:")
    hv = con.execute("""
        SELECT hs_version_first AS version, COUNT(*) AS n
        FROM dim_hs10
        GROUP BY hs_version_first
        ORDER BY hs_version_first
    """).fetchdf()
    print(hv.to_string(index=False))
    print()

    print("  hs_version_first ≠ hs_version_last (개정 사이를 걸친 hs10):")
    cross = con.execute("""
        SELECT hs_version_first, hs_version_last, COUNT(*) AS n
        FROM dim_hs10
        WHERE hs_version_first != hs_version_last
        GROUP BY hs_version_first, hs_version_last
        ORDER BY hs_version_first, hs_version_last
    """).fetchdf()
    if len(cross) > 0:
        print(cross.to_string(index=False))
    else:
        print("    (없음 — 모든 hs10이 단일 개정 내에서만 등장)")
    print()


def build_dim_hs2(con):
    """dim_hs2 생성. description_ko/section은 NULL (외부 자료 후속)."""
    print("=" * 72)
    print("[3/3] dim_hs2 생성")
    print("=" * 72)

    con.execute("DROP TABLE IF EXISTS dim_hs2")
    con.execute("""
        CREATE TABLE dim_hs2 AS
        SELECT
            hs2,
            COUNT(DISTINCT hs10) AS n_hs10,
            CAST(MIN(yyyymm) AS INTEGER) AS first_yyyymm,
            CAST(MAX(yyyymm) AS INTEGER) AS last_yyyymm,
            CAST(NULL AS VARCHAR) AS description_ko,
            CAST(NULL AS VARCHAR) AS section
        FROM fact_trade
        GROUP BY hs2
        ORDER BY hs2
    """)

    n_rows = con.execute("SELECT COUNT(*) FROM dim_hs2").fetchone()[0]
    print(f"  생성 행 수: {n_rows}")

    # 분포 일부만 확인
    sample = con.execute("""
        SELECT hs2, n_hs10, first_yyyymm, last_yyyymm
        FROM dim_hs2
        ORDER BY n_hs10 DESC
        LIMIT 5
    """).fetchdf()
    print("  hs10 개수 상위 5개 hs2:")
    print(sample.to_string(index=False))
    print()
    print("  주의: description_ko와 section은 모두 NULL.")
    print("       후속 작업으로 통계품목분류표 외부 자료 확보 후 채울 것.")
    print()


def validate_dims(con):
    """fact ↔ dim 매칭률 검증."""
    print("=" * 72)
    print("[검증] fact ↔ dim 매칭률")
    print("=" * 72)

    checks = []

    miss = con.execute("""
        SELECT COUNT(DISTINCT f.stat_cd)
        FROM fact_trade f
        LEFT JOIN dim_country d USING (stat_cd)
        WHERE d.stat_cd IS NULL
    """).fetchone()[0]
    print(f"  fact_trade.stat_cd → dim_country  : 누락 {miss}")
    checks.append(miss)

    miss = con.execute("""
        SELECT COUNT(DISTINCT f.stat_cd)
        FROM fact_total f
        LEFT JOIN dim_country d USING (stat_cd)
        WHERE d.stat_cd IS NULL
    """).fetchone()[0]
    print(f"  fact_total.stat_cd → dim_country  : 누락 {miss}")
    checks.append(miss)

    miss = con.execute("""
        SELECT COUNT(DISTINCT f.stat_cd)
        FROM meta_calls f
        LEFT JOIN dim_country d USING (stat_cd)
        WHERE d.stat_cd IS NULL
    """).fetchone()[0]
    print(f"  meta_calls.stat_cd → dim_country  : 누락 {miss}")
    checks.append(miss)

    miss = con.execute("""
        SELECT COUNT(DISTINCT f.hs10)
        FROM fact_trade f
        LEFT JOIN dim_hs10 d USING (hs10)
        WHERE d.hs10 IS NULL
    """).fetchone()[0]
    print(f"  fact_trade.hs10    → dim_hs10     : 누락 {miss}")
    checks.append(miss)

    miss = con.execute("""
        SELECT COUNT(DISTINCT f.hs2)
        FROM fact_trade f
        LEFT JOIN dim_hs2 d USING (hs2)
        WHERE d.hs2 IS NULL
    """).fetchone()[0]
    print(f"  fact_trade.hs2     → dim_hs2      : 누락 {miss}")
    checks.append(miss)
    print()

    if sum(checks) == 0:
        print("  ✓ 모든 매칭률 100%")
    else:
        print(f"  ✗ 매칭 누락 합계 {sum(checks)}. dim 설계 재검토 필요.")
    print()


def show_final_summary(con):
    """최종 요약."""
    print("=" * 72)
    print("[요약] DuckDB 테이블 구성")
    print("=" * 72)
    rows = con.execute("""
        SELECT table_name
        FROM duckdb_tables()
        WHERE schema_name = 'main'
        ORDER BY table_name
    """).fetchdf()
    for tbl in rows["table_name"].tolist():
        n = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"  {tbl}: {n:,} 행")
    print()


def main():
    print()
    print("KCSDB dim 테이블 생성 (03b)")
    print(f"  DB: {DUCKDB_PATH}")
    print()

    if not DUCKDB_PATH.exists():
        raise FileNotFoundError(f"DuckDB 파일 없음: {DUCKDB_PATH}")
    if not MOFA_PATH.exists():
        raise FileNotFoundError(f"외교부 파일 없음: {MOFA_PATH}")

    mofa_df = load_mofa()
    print(f"외교부 자료 로딩: {len(mofa_df)}행")
    print()

    con = duckdb.connect(str(DUCKDB_PATH))  # 쓰기 모드
    try:
        build_dim_country(con, mofa_df)
        build_dim_hs10(con)
        build_dim_hs2(con)
        validate_dims(con)
        show_final_summary(con)
    finally:
        con.close()

    print("=" * 72)
    print("dim 적재 완료.")
    print("=" * 72)
    print()


if __name__ == "__main__":
    main()
