"""
03a_diagnose_dims.py (v2)
=========================

dim 테이블 설계를 위한 사실 확인 스크립트.

v2 변경: fact_total에 stat_kor 컬럼 없음을 발견하여 진단 2·3을 fact_trade 기준으로 변경.
        진단 1에 fact_total ⊃ fact_trade 차집합(전체 시기 거래 0건 국가) 추출 추가.

진단 1. 관세청 stat_cd vs 외교부 ISO2 차집합 + 전체 시기 거래 0건 국가 식별
진단 2. 같은 stat_cd에 다른 stat_kor 사례 (fact_trade 기준)
진단 3. 외교부 한글명 vs 관세청 stat_kor 차이 사례 (교집합 코드 대상)
진단 4. 같은 hs10에 다른 stat_kor_item 사례 (시기별 변동, 사안 C)

DuckDB 연결은 read_only로 한다.
"""

import duckdb
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DUCKDB_PATH = PROJECT_ROOT / "data" / "processed" / "kcsdb.duckdb"
MOFA_PATH = PROJECT_ROOT / "data" / "external" / "country_codes_mofa_20251222.csv"


def load_mofa() -> pd.DataFrame:
    df = pd.read_csv(MOFA_PATH, keep_default_na=False, encoding="utf-8")
    df = df.rename(columns={
        "국제표준화기구_2자리": "iso2",
        "국제표준화기구_3자리": "iso3",
        "국제표준화기구_숫자": "iso_num",
        "대륙명_공통 대륙코드": "continent_en",
        "대륙명_행정표준코드": "continent_admin",
        "대륙명_외교부 직제": "continent_mofa",
        "영문명": "name_en",
        "한글명": "name_ko",
    })
    return df


def show_table_schemas(con):
    """테이블 컬럼 구조 확인 — 핸드오버에 fact_total 스키마가 누락되어 있어 추가."""
    print("=" * 72)
    print("[사전] 테이블 컬럼 구조")
    print("=" * 72)
    for tbl in ["fact_trade", "fact_total", "meta_calls"]:
        cols = con.execute(f"DESCRIBE {tbl}").fetchdf()
        col_list = ", ".join(f"{r['column_name']}({r['column_type']})"
                             for _, r in cols.iterrows())
        print(f"  {tbl}: {col_list}")
    print()


def diag_1_country_diff(con, mofa_df):
    """진단 1: 관세청 stat_cd vs 외교부 ISO2 차집합 + 전체 시기 거래 0건 국가."""
    print("=" * 72)
    print("[진단 1] 관세청 stat_cd vs 외교부 ISO2 차집합")
    print("=" * 72)

    kcs_trade = set(con.execute(
        "SELECT DISTINCT stat_cd FROM fact_trade"
    ).fetchdf()["stat_cd"].tolist())
    kcs_total = set(con.execute(
        "SELECT DISTINCT stat_cd FROM fact_total"
    ).fetchdf()["stat_cd"].tolist())
    kcs_meta = set(con.execute(
        "SELECT DISTINCT stat_cd FROM meta_calls"
    ).fetchdf()["stat_cd"].tolist())
    mofa_codes = set(mofa_df["iso2"].tolist())

    print(f"  fact_trade stat_cd 고유 수: {len(kcs_trade)}")
    print(f"  fact_total stat_cd 고유 수: {len(kcs_total)}")
    print(f"  meta_calls stat_cd 고유 수: {len(kcs_meta)}")
    print(f"  외교부 ISO2 고유 수:        {len(mofa_codes)}")
    print()

    only_mofa = mofa_codes - kcs_meta
    only_kcs = kcs_meta - mofa_codes
    print(f"  외교부에만 있는 코드 ({len(only_mofa)}개):")
    if only_mofa:
        for code in sorted(only_mofa):
            name = mofa_df[mofa_df["iso2"] == code]["name_ko"].iloc[0]
            print(f"    {code}: {name}")
    else:
        print("    (없음)")
    print()
    print(f"  관세청에만 있는 코드 ({len(only_kcs)}개):")
    if only_kcs:
        for code in sorted(only_kcs):
            print(f"    {code}")
    else:
        print("    (없음)")
    print()

    call_failed = kcs_meta - kcs_total
    print(f"  호출했으나 fact_total에 없는 코드 ({len(call_failed)}개, "
          f"호출 자체 영구 실패):")
    if call_failed:
        for code in sorted(call_failed):
            n_fail = con.execute(
                "SELECT COUNT(*) FROM meta_calls WHERE stat_cd = ? AND NOT success",
                [code]
            ).fetchone()[0]
            n_total = con.execute(
                "SELECT COUNT(*) FROM meta_calls WHERE stat_cd = ?",
                [code]
            ).fetchone()[0]
            print(f"    {code}: 실패 {n_fail}/{n_total}회")
    else:
        print("    (없음)")
    print()

    zero_trade = kcs_total - kcs_trade
    print(f"  전체 시기 거래 0건 국가 ({len(zero_trade)}개):")
    if zero_trade:
        for code in sorted(zero_trade):
            mofa_name_series = mofa_df[mofa_df["iso2"] == code]["name_ko"]
            mofa_name = mofa_name_series.iloc[0] if len(mofa_name_series) > 0 else "(외교부 미수록)"
            n_pairs = con.execute(
                "SELECT COUNT(*) FROM fact_total WHERE stat_cd = ?",
                [code]
            ).fetchone()[0]
            print(f"    {code} ({mofa_name}): fact_total {n_pairs}개 페어 (모두 0값)")
    else:
        print("    (없음)")
    print()


def diag_2_kcs_kor_variants(con):
    """진단 2: 같은 stat_cd에 다른 stat_kor 사례 (fact_trade 기준)."""
    print("=" * 72)
    print("[진단 2] 같은 stat_cd에 다른 stat_kor 사례 (fact_trade 기준)")
    print("=" * 72)

    df = con.execute("""
        SELECT stat_cd,
               COUNT(DISTINCT stat_kor) AS n_variants,
               STRING_AGG(DISTINCT stat_kor, ' | ') AS variants
        FROM fact_trade
        WHERE stat_kor IS NOT NULL AND stat_kor != ''
        GROUP BY stat_cd
        HAVING COUNT(DISTINCT stat_kor) > 1
        ORDER BY n_variants DESC, stat_cd
    """).fetchdf()

    print(f"  변동 있는 stat_cd: {len(df)}개")
    if len(df) > 0:
        print()
        with pd.option_context("display.max_colwidth", 80,
                               "display.width", 120):
            print(df.to_string(index=False))
    print()


def diag_3_name_diff(con, mofa_df):
    """진단 3: 외교부 한글명 vs 관세청 stat_kor 차이 사례 (fact_trade 기준)."""
    print("=" * 72)
    print("[진단 3] 외교부 한글명 vs 관세청 stat_kor 차이 사례")
    print("=" * 72)

    kcs_df = con.execute("""
        WITH freq AS (
            SELECT stat_cd, stat_kor, COUNT(*) AS n
            FROM fact_trade
            WHERE stat_kor IS NOT NULL AND stat_kor != ''
            GROUP BY stat_cd, stat_kor
        )
        SELECT stat_cd, stat_kor
        FROM freq
        QUALIFY ROW_NUMBER() OVER (PARTITION BY stat_cd ORDER BY n DESC) = 1
    """).fetchdf()

    merged = kcs_df.merge(
        mofa_df[["iso2", "name_ko"]],
        left_on="stat_cd", right_on="iso2", how="inner"
    )
    diff = merged[merged["stat_kor"] != merged["name_ko"]]

    print(f"  교집합 코드 수:                    {len(merged)}")
    print(f"  외교부 한글명 = 관세청 stat_kor:   {len(merged) - len(diff)}")
    print(f"  차이 있는 코드:                    {len(diff)}")
    print()

    if len(diff) > 0:
        print("  차이 사례 (외교부 / 관세청):")
        for _, row in diff.iterrows():
            print(f"    {row['stat_cd']}: '{row['name_ko']}'  /  '{row['stat_kor']}'")
    print()


def diag_4_hs_kor_variants(con):
    """진단 4: 같은 hs10에 다른 stat_kor_item 사례."""
    print("=" * 72)
    print("[진단 4] 같은 hs10에 다른 stat_kor_item 사례 (사안 C)")
    print("=" * 72)

    total_hs10 = con.execute(
        "SELECT COUNT(DISTINCT hs10) FROM fact_trade"
    ).fetchone()[0]

    df = con.execute("""
        SELECT hs10, COUNT(DISTINCT stat_kor_item) AS n_variants
        FROM fact_trade
        WHERE stat_kor_item IS NOT NULL AND stat_kor_item != ''
        GROUP BY hs10
        HAVING COUNT(DISTINCT stat_kor_item) > 1
    """).fetchdf()

    print(f"  전체 hs10 고유 수:           {total_hs10:,}")
    print(f"  변동 있는 hs10:              {len(df):,}")
    if total_hs10 > 0:
        print(f"  비율:                         {len(df)/total_hs10*100:.2f}%")
    print()

    if len(df) > 0:
        sample = con.execute("""
            SELECT hs10,
                   COUNT(DISTINCT stat_kor_item) AS n,
                   STRING_AGG(DISTINCT stat_kor_item, ' | ') AS variants
            FROM fact_trade
            WHERE stat_kor_item IS NOT NULL AND stat_kor_item != ''
            GROUP BY hs10
            HAVING COUNT(DISTINCT stat_kor_item) > 1
            ORDER BY n DESC
            LIMIT 10
        """).fetchdf()
        print("  상위 10개 변동 사례:")
        with pd.option_context("display.max_colwidth", 80,
                               "display.width", 120):
            print(sample.to_string(index=False))
    print()


def main():
    print()
    print("KCSDB dim 설계 사전 진단 (v2)")
    print(f"  DB:    {DUCKDB_PATH}")
    print(f"  외교부: {MOFA_PATH}")
    print()

    if not DUCKDB_PATH.exists():
        raise FileNotFoundError(f"DuckDB 파일 없음: {DUCKDB_PATH}")
    if not MOFA_PATH.exists():
        raise FileNotFoundError(f"외교부 파일 없음: {MOFA_PATH}")

    mofa_df = load_mofa()
    print(f"외교부 자료 로딩: {len(mofa_df)}행, {len(mofa_df.columns)}컬럼")
    print()

    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        show_table_schemas(con)
        diag_1_country_diff(con, mofa_df)
        diag_2_kcs_kor_variants(con)
        diag_3_name_diff(con, mofa_df)
        diag_4_hs_kor_variants(con)
    finally:
        con.close()

    print("=" * 72)
    print("진단 완료. 위 결과를 03b_build_dims.py 작성 방침에 반영한다.")
    print("=" * 72)
    print()


if __name__ == "__main__":
    main()
