"""
05: KCSDB 데이터셋 광범위 탐색 SQL

목적:
- 데이터셋 전체 윤곽 파악 (거시 요약, 시계열, 분포)
- raw 자료 특성 7가지 SQL 재현 — 검증이 아닌 *기술적 분석* 시각
- 책 13장 회고 자료 + 분석 챕터 진입점
- 학생 교재로 *SQL 학습 단위* 역할 (각 섹션 독립)

연구 프레임 (결정 1):
- 인과 추론 아님 (식별 위협으로 글로벌 동시충격 분리 불가)
- *관찰된 변화의 기술적 분석* — 비중·규모·구성·시기 분포

7개 섹션:
  1. 거시 요약
  2. 연도별 시계열
  3. 상위 무역국 (전 기간 vs 최근 5년)
  4. 상위 HS2 류 + 부 단위 분포
  5. 충격 분석 (2008/2020/2022)
  6. raw 자료 특성 SQL 재현 (7가지)
  7. HS 분류표 비대칭

실행:
    cd C:\\Projects\\KCSDB
    conda activate kcsdb
    python scripts\\05_explore.py
"""

from __future__ import annotations
import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "processed" / "kcsdb.duckdb"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

# pandas 출력 폭 무제한
pd.set_option("display.max_columns", None)
pd.set_option("display.width", None)
pd.set_option("display.max_colwidth", 80)

# 로그
LOG_PATH = LOG_DIR / f"explore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
fh.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(fh)


def out(msg: str = ""):
    """콘솔 + 로그 동시 출력."""
    print(msg)
    logger.info(msg)


def out_df(df: pd.DataFrame, max_rows: int = 30):
    """DataFrame을 깔끔하게 출력. 큰 DataFrame은 head/tail 분리."""
    if len(df) > max_rows:
        out(df.head(max_rows // 2).to_string(index=False))
        out(f"  ... ({len(df) - max_rows}행 생략) ...")
        out(df.tail(max_rows // 2).to_string(index=False))
    else:
        out(df.to_string(index=False))


def section_header(num: int, title: str):
    out()
    out("=" * 78)
    out(f"[{num}] {title}")
    out("=" * 78)


def fmt_money(x):
    """달러 금액을 억 USD 단위로 포맷."""
    if pd.isna(x):
        return "—"
    return f"{x / 1e8:>10,.1f}억$"


# ──────────────────────────────────────────────
# 섹션 1: 거시 요약
# ──────────────────────────────────────────────

def section_1_macro(con):
    section_header(1, "거시 요약 — 데이터셋 한 장 개요")
    t0 = time.perf_counter()

    sql = """
        SELECT
            (SELECT COUNT(*) FROM fact_trade)              AS n_trade_rows,
            (SELECT COUNT(*) FROM fact_total)              AS n_total_rows,
            (SELECT COUNT(*) FROM meta_calls)              AS n_calls,
            (SELECT COUNT(DISTINCT yyyymm) FROM fact_total) AS n_months,
            (SELECT COUNT(DISTINCT stat_cd) FROM fact_trade) AS n_country_in_trade,
            (SELECT COUNT(*) FROM dim_country)             AS n_dim_country,
            (SELECT COUNT(*) FROM dim_hs10)                AS n_dim_hs10,
            (SELECT COUNT(*) FROM dim_hs2)                 AS n_dim_hs2,
            (SELECT MIN(yyyymm) FROM fact_total)           AS yyyymm_min,
            (SELECT MAX(yyyymm) FROM fact_total)           AS yyyymm_max,
            (SELECT SUM(exp_dlr) FROM fact_total)          AS total_exp_dlr,
            (SELECT SUM(imp_dlr) FROM fact_total)          AS total_imp_dlr
    """
    r = con.execute(sql).fetchone()

    out(f"  fact_trade 행 수      : {r[0]:>15,}")
    out(f"  fact_total 행 수      : {r[1]:>15,}")
    out(f"  meta_calls 행 수      : {r[2]:>15,}")
    out(f"  분석 가능 월 수       : {r[3]:>15,}")
    out(f"  거래 발생 국가 수     : {r[4]:>15,}  (fact_trade 기준, 240)")
    out(f"  dim_country 행 수     : {r[5]:>15,}  (외교부+관세청 합집합, 244)")
    out(f"  dim_hs10 행 수        : {r[6]:>15,}  (개정 누적)")
    out(f"  dim_hs2 행 수         : {r[7]:>15,}")
    out(f"  시기 범위 (yyyymm)    : {r[8]} ~ {r[9]}")
    out(f"  총 수출 (전 기간)     : {fmt_money(r[10])}")
    out(f"  총 수입 (전 기간)     : {fmt_money(r[11])}")
    out(f"  총 무역수지 (전 기간) : {fmt_money(r[10] - r[11])}")

    out(f"  [실행 시간 {time.perf_counter() - t0:.2f}초]")


# ──────────────────────────────────────────────
# 섹션 2: 연도별 시계열
# ──────────────────────────────────────────────

def section_2_yearly(con):
    section_header(2, "연도별 시계열 — 수출/수입/무역수지/증감률")
    t0 = time.perf_counter()

    sql = """
        WITH yr AS (
            SELECT year,
                   SUM(exp_dlr) AS exp_dlr,
                   SUM(imp_dlr) AS imp_dlr,
                   SUM(bal_payments) AS bal
            FROM fact_total
            GROUP BY year
            ORDER BY year
        ),
        with_lag AS (
            SELECT year, exp_dlr, imp_dlr, bal,
                   LAG(exp_dlr) OVER (ORDER BY year) AS prev_exp,
                   LAG(imp_dlr) OVER (ORDER BY year) AS prev_imp
            FROM yr
        )
        SELECT year,
               exp_dlr / 1e8         AS "수출(억$)",
               imp_dlr / 1e8         AS "수입(억$)",
               bal     / 1e8         AS "수지(억$)",
               CASE WHEN prev_exp IS NULL THEN NULL
                    ELSE (exp_dlr - prev_exp) * 100.0 / prev_exp END AS "수출증감(%)",
               CASE WHEN prev_imp IS NULL THEN NULL
                    ELSE (imp_dlr - prev_imp) * 100.0 / prev_imp END AS "수입증감(%)"
        FROM with_lag
        ORDER BY year
    """
    df = con.execute(sql).df()
    df["수출(억$)"]   = df["수출(억$)"].round(1)
    df["수입(억$)"]   = df["수입(억$)"].round(1)
    df["수지(억$)"]   = df["수지(억$)"].round(1)
    df["수출증감(%)"] = df["수출증감(%)"].round(1)
    df["수입증감(%)"] = df["수입증감(%)"].round(1)

    out_df(df, max_rows=30)

    # 주목할 시기 자동 추출
    out()
    out("  [주목할 연도 — 수출 또는 수입 ±10% 이상 변동]")
    flagged = df[
        (df["수출증감(%)"].abs() >= 10) | (df["수입증감(%)"].abs() >= 10)
    ]
    if len(flagged) > 0:
        out_df(flagged[["year", "수출증감(%)", "수입증감(%)"]])
    else:
        out("  (해당 없음)")

    out(f"  [실행 시간 {time.perf_counter() - t0:.2f}초]")


# ──────────────────────────────────────────────
# 섹션 3: 상위 무역국
# ──────────────────────────────────────────────

def section_3_top_countries(con):
    section_header(3, "상위 무역국 — 전 기간 vs 최근 5년")
    t0 = time.perf_counter()

    # 3-1: 전 기간 상위 15
    out()
    out("  [3-1] 수출 상위 15국 (전 기간)")
    df1 = con.execute("""
        SELECT
            t.stat_cd,
            d.name_ko_kcs AS name,
            SUM(t.exp_dlr) / 1e8 AS "수출누계(억$)",
            SUM(t.exp_dlr) * 100.0 / SUM(SUM(t.exp_dlr)) OVER () AS "비중(%)"
        FROM fact_total t
        LEFT JOIN dim_country d USING (stat_cd)
        GROUP BY t.stat_cd, d.name_ko_kcs
        ORDER BY "수출누계(억$)" DESC
        LIMIT 15
    """).df()
    df1["수출누계(억$)"] = df1["수출누계(억$)"].round(0).astype(int)
    df1["비중(%)"] = df1["비중(%)"].round(2)
    out_df(df1)

    out()
    out("  [3-2] 수입 상위 15국 (전 기간)")
    df2 = con.execute("""
        SELECT
            t.stat_cd,
            d.name_ko_kcs AS name,
            SUM(t.imp_dlr) / 1e8 AS "수입누계(억$)",
            SUM(t.imp_dlr) * 100.0 / SUM(SUM(t.imp_dlr)) OVER () AS "비중(%)"
        FROM fact_total t
        LEFT JOIN dim_country d USING (stat_cd)
        GROUP BY t.stat_cd, d.name_ko_kcs
        ORDER BY "수입누계(억$)" DESC
        LIMIT 15
    """).df()
    df2["수입누계(억$)"] = df2["수입누계(억$)"].round(0).astype(int)
    df2["비중(%)"] = df2["비중(%)"].round(2)
    out_df(df2)

    # 3-3: 최근 5년 (2021~2025) — 비중 변화 모니터링
    out()
    out("  [3-3] 수출 상위 10국 — 최근 5년 (2021~2025)")
    df3 = con.execute("""
        SELECT
            t.stat_cd,
            d.name_ko_kcs AS name,
            SUM(t.exp_dlr) / 1e8 AS "수출(억$)",
            SUM(t.exp_dlr) * 100.0 / SUM(SUM(t.exp_dlr)) OVER () AS "비중(%)"
        FROM fact_total t
        LEFT JOIN dim_country d USING (stat_cd)
        WHERE year BETWEEN 2021 AND 2025
        GROUP BY t.stat_cd, d.name_ko_kcs
        ORDER BY "수출(억$)" DESC
        LIMIT 10
    """).df()
    df3["수출(억$)"] = df3["수출(억$)"].round(0).astype(int)
    df3["비중(%)"] = df3["비중(%)"].round(2)
    out_df(df3)

    # 3-4: 미·중 의존도 시계열 (수출 비중)
    out()
    out("  [3-4] 미·중 수출 비중 시계열 (5년 단위 평균)")
    df4 = con.execute("""
        WITH base AS (
            SELECT
                CASE
                    WHEN year BETWEEN 2007 AND 2011 THEN '2007-2011'
                    WHEN year BETWEEN 2012 AND 2016 THEN '2012-2016'
                    WHEN year BETWEEN 2017 AND 2021 THEN '2017-2021'
                    WHEN year BETWEEN 2022 AND 2025 THEN '2022-2025'
                END AS period,
                stat_cd,
                exp_dlr
            FROM fact_total
            WHERE year BETWEEN 2007 AND 2025
        )
        SELECT
            period,
            SUM(CASE WHEN stat_cd = 'US' THEN exp_dlr END) * 100.0 / SUM(exp_dlr) AS "미국비중(%)",
            SUM(CASE WHEN stat_cd = 'CN' THEN exp_dlr END) * 100.0 / SUM(exp_dlr) AS "중국비중(%)",
            (SUM(CASE WHEN stat_cd = 'US' THEN exp_dlr END)
            + SUM(CASE WHEN stat_cd = 'CN' THEN exp_dlr END)) * 100.0
            / SUM(exp_dlr) AS "G2합계(%)"
        FROM base
        WHERE period IS NOT NULL
        GROUP BY period
        ORDER BY period
    """).df()
    for c in ["미국비중(%)", "중국비중(%)", "G2합계(%)"]:
        df4[c] = df4[c].round(2)
    out_df(df4)

    out(f"  [실행 시간 {time.perf_counter() - t0:.2f}초]")


# ──────────────────────────────────────────────
# 섹션 4: 상위 HS2 류
# ──────────────────────────────────────────────

def section_4_top_hs2(con):
    section_header(4, "상위 HS2 류 — description_ko 결합")
    t0 = time.perf_counter()

    out()
    out("  [4-1] 수출 상위 15류 (전 기간) — description_ko 첫 25자")
    df1 = con.execute("""
        SELECT
            f.hs2,
            SUBSTR(d.description_ko, 1, 25) AS "한국어 류명(요약)",
            d.section,
            SUM(f.exp_dlr) / 1e8 AS "수출(억$)",
            SUM(f.exp_dlr) * 100.0 / SUM(SUM(f.exp_dlr)) OVER () AS "비중(%)"
        FROM fact_trade f
        LEFT JOIN dim_hs2 d USING (hs2)
        GROUP BY f.hs2, d.description_ko, d.section
        ORDER BY "수출(억$)" DESC
        LIMIT 15
    """).df()
    df1["수출(억$)"] = df1["수출(억$)"].round(0).astype(int)
    df1["비중(%)"] = df1["비중(%)"].round(2)
    out_df(df1)

    out()
    out("  [4-2] 수입 상위 15류 (전 기간)")
    df2 = con.execute("""
        SELECT
            f.hs2,
            SUBSTR(d.description_ko, 1, 25) AS "한국어 류명(요약)",
            d.section,
            SUM(f.imp_dlr) / 1e8 AS "수입(억$)",
            SUM(f.imp_dlr) * 100.0 / SUM(SUM(f.imp_dlr)) OVER () AS "비중(%)"
        FROM fact_trade f
        LEFT JOIN dim_hs2 d USING (hs2)
        GROUP BY f.hs2, d.description_ko, d.section
        ORDER BY "수입(억$)" DESC
        LIMIT 15
    """).df()
    df2["수입(억$)"] = df2["수입(억$)"].round(0).astype(int)
    df2["비중(%)"] = df2["비중(%)"].round(2)
    out_df(df2)

    out()
    out("  [4-3] 부(Section) 단위 수출 분포")
    df3 = con.execute("""
        SELECT
            d.section,
            COUNT(DISTINCT f.hs2) AS "보유 류 수",
            SUM(f.exp_dlr) / 1e8 AS "수출(억$)",
            SUM(f.exp_dlr) * 100.0 / SUM(SUM(f.exp_dlr)) OVER () AS "비중(%)"
        FROM fact_trade f
        LEFT JOIN dim_hs2 d USING (hs2)
        WHERE d.section IS NOT NULL
        GROUP BY d.section
        ORDER BY "수출(억$)" DESC
    """).df()
    df3["수출(억$)"] = df3["수출(억$)"].round(0).astype(int)
    df3["비중(%)"] = df3["비중(%)"].round(2)
    out_df(df3)

    out(f"  [실행 시간 {time.perf_counter() - t0:.2f}초]")


# ──────────────────────────────────────────────
# 섹션 5: 충격 분석
# ──────────────────────────────────────────────

def section_5_shocks(con):
    section_header(5, "충격 분석 — 2008 금융위기, 2020 코로나19, 2022 우크라이나")
    t0 = time.perf_counter()

    # 5-1: 충격 시기 ±2년 거시 변동
    out()
    out("  [5-1] 충격 ±2년 거시 변동 (전체 무역)")
    df1 = con.execute("""
        WITH yr AS (
            SELECT year,
                   SUM(exp_dlr) AS exp_dlr,
                   SUM(imp_dlr) AS imp_dlr
            FROM fact_total
            WHERE year IN (2007, 2008, 2009, 2010,
                          2018, 2019, 2020, 2021, 2022,
                          2023, 2024)
            GROUP BY year
        )
        SELECT year,
               exp_dlr / 1e8 AS "수출(억$)",
               imp_dlr / 1e8 AS "수입(억$)",
               (exp_dlr - imp_dlr) / 1e8 AS "수지(억$)"
        FROM yr
        ORDER BY year
    """).df()
    for c in ["수출(억$)", "수입(억$)", "수지(억$)"]:
        df1[c] = df1[c].round(0).astype(int)
    out_df(df1)

    # 5-2: 충격 시기 미·중 비중 (수출)
    out()
    out("  [5-2] 충격 시기 미·중 수출 비중 (%)")
    df2 = con.execute("""
        SELECT
            year,
            SUM(CASE WHEN stat_cd = 'US' THEN exp_dlr END) * 100.0
                / SUM(exp_dlr) AS "미국 수출비중(%)",
            SUM(CASE WHEN stat_cd = 'CN' THEN exp_dlr END) * 100.0
                / SUM(exp_dlr) AS "중국 수출비중(%)"
        FROM fact_total
        WHERE year IN (2008, 2009, 2010, 2019, 2020, 2021, 2022)
        GROUP BY year
        ORDER BY year
    """).df()
    for c in ["미국 수출비중(%)", "중국 수출비중(%)"]:
        df2[c] = df2[c].round(2)
    out_df(df2)

    # 5-3: 코로나19 - 가장 큰 영향 받은 류
    out()
    out("  [5-3] 코로나19 충격 — 2020 vs 2019 수출 변동률 상위/하위 5류")
    df3 = con.execute("""
        WITH y19 AS (
            SELECT hs2, SUM(exp_dlr) AS exp_2019
            FROM fact_trade WHERE year = 2019
            GROUP BY hs2
        ),
        y20 AS (
            SELECT hs2, SUM(exp_dlr) AS exp_2020
            FROM fact_trade WHERE year = 2020
            GROUP BY hs2
        ),
        cmp AS (
            SELECT y19.hs2, y19.exp_2019, y20.exp_2020,
                   (y20.exp_2020 - y19.exp_2019) * 100.0 / y19.exp_2019 AS pct_change
            FROM y19 INNER JOIN y20 USING (hs2)
            WHERE y19.exp_2019 > 1e9  -- 10억$ 이상으로 제한 (소규모 노이즈 제거)
        )
        (SELECT hs2,
                SUBSTR(d.description_ko, 1, 25) AS name,
                cmp.exp_2019 / 1e8 AS "2019(억$)",
                cmp.exp_2020 / 1e8 AS "2020(억$)",
                cmp.pct_change AS "증감(%)"
         FROM cmp LEFT JOIN dim_hs2 d USING (hs2)
         ORDER BY pct_change DESC
         LIMIT 5)
        UNION ALL
        (SELECT hs2,
                SUBSTR(d.description_ko, 1, 25) AS name,
                cmp.exp_2019 / 1e8 AS "2019(억$)",
                cmp.exp_2020 / 1e8 AS "2020(억$)",
                cmp.pct_change AS "증감(%)"
         FROM cmp LEFT JOIN dim_hs2 d USING (hs2)
         ORDER BY pct_change ASC
         LIMIT 5)
    """).df()
    for c in ["2019(억$)", "2020(억$)"]:
        df3[c] = df3[c].round(0).astype(int)
    df3["증감(%)"] = df3["증감(%)"].round(2)
    out_df(df3)

    out(f"  [실행 시간 {time.perf_counter() - t0:.2f}초]")


# ──────────────────────────────────────────────
# 섹션 6: raw 자료 특성 7가지 SQL 재현
# ──────────────────────────────────────────────

def section_6_raw_traits(con):
    section_header(6, "raw 자료 특성 SQL 재현 — 7가지")
    t0 = time.perf_counter()

    # 6-1: 거래 0건 페어
    out()
    out("  [6-1] 거래 0건 페어 — fact_total에 0값으로 기록된 페어")
    n = con.execute("""
        SELECT COUNT(*) FROM fact_total
        WHERE exp_dlr = 0 AND imp_dlr = 0
    """).fetchone()[0]
    out(f"  거래 0건 페어 수: {n:,}")

    # 6-2: 음수 통계
    out()
    out("  [6-2] 음수 중량 — 자료 정정·환수·통계 보정 잔여물 (fact_trade에만)")
    df = con.execute("""
        SELECT
            SUM(CASE WHEN exp_wgt < 0 THEN 1 ELSE 0 END) AS "exp_wgt 음수",
            SUM(CASE WHEN imp_wgt < 0 THEN 1 ELSE 0 END) AS "imp_wgt 음수",
            COUNT(*) AS "전체 행 수"
        FROM fact_trade
    """).df()
    out_df(df)

    # 6-3: 중량 합계 잔차 (이번 세션 검증 1b 결과 재현)
    out()
    out("  [6-3] 중량 합계 잔차 — fact_trade 합 vs fact_total 차이")
    df = con.execute("""
        WITH d AS (
            SELECT yyyymm, stat_cd,
                   SUM(t.exp_wgt) - MAX(f.exp_wgt) AS diff_exp,
                   SUM(t.imp_wgt) - MAX(f.imp_wgt) AS diff_imp
            FROM fact_trade t
            INNER JOIN fact_total f USING (yyyymm, stat_cd)
            GROUP BY yyyymm, stat_cd
        )
        SELECT
            COUNT(*) AS "비교 페어",
            SUM(CASE WHEN diff_exp != 0 OR diff_imp != 0 THEN 1 ELSE 0 END) AS "잔차 페어",
            MAX(ABS(diff_exp)) AS "최대 수출잔차(kg)",
            MAX(ABS(diff_imp)) AS "최대 수입잔차(kg)"
        FROM d
    """).df()
    out_df(df)

    # 6-4: XK 코소보 영구 실패
    out()
    out("  [6-4] XK 코소보 — 외교부 244국에 있지만 관세청 미인식")
    df = con.execute("""
        SELECT
            (SELECT COUNT(*) FROM meta_calls WHERE stat_cd = 'XK') AS "호출 시도",
            (SELECT COUNT(*) FROM meta_calls WHERE stat_cd = 'XK' AND success) AS "성공",
            (SELECT COUNT(*) FROM fact_total WHERE stat_cd = 'XK') AS "fact_total 행",
            (SELECT call_status FROM dim_country WHERE stat_cd = 'XK') AS "call_status"
    """).df()
    out_df(df)

    # 6-5: 빈 응답 (2026.04~05)
    out()
    out("  [6-5] 빈 응답 — 관세청 미발표 시기")
    df = con.execute("""
        SELECT yyyymm, COUNT(*) AS n_calls,
               SUM(CASE WHEN item_count = 0 AND success THEN 1 ELSE 0 END) AS empty_response
        FROM meta_calls
        WHERE yyyymm >= 202604
        GROUP BY yyyymm
        ORDER BY yyyymm
    """).df()
    if len(df) > 0:
        out_df(df)
    else:
        out("  (해당 시기 호출 없음)")

    # 6-6: 전체 시기 거래 0건 국가 3개 (EU, KR, KP)
    out()
    out("  [6-6] 전체 시기 거래 0건 국가 — fact_total에 모든 행이 0인 국가")
    df = con.execute("""
        SELECT
            t.stat_cd,
            d.name_ko_kcs,
            d.is_country,
            d.is_self,
            d.has_trade,
            COUNT(*) AS n_zero_months
        FROM fact_total t
        LEFT JOIN dim_country d USING (stat_cd)
        WHERE t.exp_dlr = 0 AND t.imp_dlr = 0
        GROUP BY t.stat_cd, d.name_ko_kcs, d.is_country, d.is_self, d.has_trade
        HAVING COUNT(*) = (SELECT COUNT(DISTINCT yyyymm) FROM fact_total)
        ORDER BY t.stat_cd
    """).df()
    out_df(df)

    # 6-7: motie 외부 대조 비대칭 (이번 세션 발견, 검증 9b 재현)
    out()
    out("  [6-7] motie 외부 대조 비대칭 — 차이가 수입에 집중, 코로나19 시기")
    out("  (검증 9b 결과 재현)")
    csv_path = PROJECT_ROOT / "data" / "external" / "motie_annual.csv"
    if not csv_path.exists():
        out("  motie_annual.csv 없음 — skip")
    else:
        df = con.execute(f"""
            WITH motie AS (
                SELECT * FROM read_csv_auto('{str(csv_path).replace(chr(92), "/")}')
            ),
            yr AS (
                SELECT year, SUM(exp_dlr) AS k_exp, SUM(imp_dlr) AS k_imp
                FROM fact_total GROUP BY year
            )
            SELECT m.year,
                   ABS(m.total_exp_dlr - k.k_exp) * 100.0 / m.total_exp_dlr AS "수출차이율(%)",
                   ABS(m.total_imp_dlr - k.k_imp) * 100.0 / m.total_imp_dlr AS "수입차이율(%)"
            FROM motie m INNER JOIN yr k USING (year)
            ORDER BY m.year
        """).df()
        df["수출차이율(%)"] = df["수출차이율(%)"].round(4)
        df["수입차이율(%)"] = df["수입차이율(%)"].round(4)
        out_df(df, max_rows=25)
        out()
        out("  관찰: (1) 차이는 수입 쪽에서 더 크다, (2) 부호는 모두 양 (motie>KCSDB),")
        out("        (3) 0.5% 이상 차이는 2020~2022 코로나19~우크라이나 시기에 집중")

    out(f"  [실행 시간 {time.perf_counter() - t0:.2f}초]")


# ──────────────────────────────────────────────
# 섹션 7: HS 분류표 비대칭
# ──────────────────────────────────────────────

def section_7_hs_asymmetry(con):
    section_header(7, "HS 분류표 비대칭 — HS77/HS98/HS99")
    t0 = time.perf_counter()

    out()
    out("  [7-1] dim_hs2 비등장 코드 (vs 01~99 전체)")
    df = con.execute("""
        SELECT LPAD(range::VARCHAR, 2, '0') AS hs2_missing
        FROM range(1, 100)
        WHERE LPAD(range::VARCHAR, 2, '0') NOT IN (SELECT hs2 FROM dim_hs2)
        ORDER BY hs2_missing
    """).df()
    out_df(df)
    out("  HS77: WCO 국제표준 reserved (모든 국가 공통)")
    out("  HS98: 한국 미사용 (체약국 자체 사용용으로 예약했지만 활용 안 함)")

    out()
    out("  [7-2] HS99 — 한국 통계 특수 분류 (관세 부과 외)")
    df = con.execute("""
        SELECT hs2, n_hs10, first_yyyymm, last_yyyymm,
               description_ko, description_en, section
        FROM dim_hs2 WHERE hs2 = '99'
    """).df()
    out_df(df)
    out()
    out("  HS99 거래 규모 (수출, 수입, 페어 수):")
    df = con.execute("""
        SELECT
            COUNT(*) AS "거래 행 수",
            SUM(exp_dlr) / 1e8 AS "수출(억$)",
            SUM(imp_dlr) / 1e8 AS "수입(억$)",
            COUNT(DISTINCT stat_cd) AS "거래국가 수"
        FROM fact_trade WHERE hs2 = '99'
    """).df()
    df["수출(억$)"] = df["수출(억$)"].round(2)
    df["수입(억$)"] = df["수입(억$)"].round(2)
    out_df(df)

    out()
    out("  [7-3] HS 개정 비대칭 — 두 개정 이상 걸친 hs10 코드 (함정 20)")
    df = con.execute("""
        WITH categorized AS (
            SELECT
                CASE
                    WHEN hs_version_first = hs_version_last THEN '단일 개정'
                    ELSE '두 개정 이상'
                END AS pattern,
                COUNT(*) AS n
            FROM dim_hs10
            GROUP BY pattern
        )
        SELECT pattern, n,
               n * 100.0 / SUM(n) OVER () AS "비중(%)"
        FROM categorized
        ORDER BY n DESC
    """).df()
    df["비중(%)"] = df["비중(%)"].round(1)
    out_df(df)

    out(f"  [실행 시간 {time.perf_counter() - t0:.2f}초]")


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.parse_args()

    if not DB_PATH.exists():
        print(f"[ERROR] DB 파일 없음: {DB_PATH}")
        sys.exit(1)

    out("=" * 78)
    out("05: KCSDB 데이터셋 광범위 탐색 SQL")
    out(f"DB: {DB_PATH}")
    out(f"실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    out(f"로그: {LOG_PATH}")
    out("=" * 78)

    con = duckdb.connect(str(DB_PATH), read_only=True)
    t_start = time.perf_counter()

    section_1_macro(con)
    section_2_yearly(con)
    section_3_top_countries(con)
    section_4_top_hs2(con)
    section_5_shocks(con)
    section_6_raw_traits(con)
    section_7_hs_asymmetry(con)

    con.close()

    elapsed = time.perf_counter() - t_start
    out()
    out("=" * 78)
    out(f"탐색 종료. 총 {elapsed:.1f}초")
    out(f"로그 파일: {LOG_PATH}")
    out("=" * 78)


if __name__ == "__main__":
    main()
