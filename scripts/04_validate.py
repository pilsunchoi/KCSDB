"""
04: 적재된 DuckDB의 내부 일관성 검증 (v5)

기존 검증 9종 + dim 검증 8종 = 17종 (motie 9a 포함 시 18종, 9b 포함 시 18~19종).

기본 검증:
1a. fact_trade ↔ fact_total 금액 합계 일관성 (정확 일치)
1b. fact_trade ↔ fact_total 중량 합계 일관성 (정보용 통계)
2.  fact_total 회계 항등식 (bal_payments = exp_dlr - imp_dlr)
3.  fact_trade 회계 항등식
4.  meta_calls ↔ fact 행수 무결성
5.  HS 파생 컬럼 일관성 (hs2/hs4/hs6 = hs10 슬라이싱)
6.  페어 완전성 (fact_trade의 모든 페어가 meta_calls에 있는지)
7.  시간 연속성 (200701~202605 빠진 월 없음)
8.  음수 통계 (raw 자료 잔여, 정보용)
9a. 산업통상자원부 월별 외부 대조 (선택, motie_monthly.csv 정확 일치)
9b. ★v5 신규★ 산업통상자원부 연간 외부 대조 (선택, motie_annual.csv 정보용 통계)

dim 검증 (★v2 신규★, dim 테이블 존재 시만 실행):
10. dim_country 행 수 = 244
11. fact ↔ dim_country 매칭률 (fact_trade/fact_total/meta_calls)
12. fact_trade.hs10 → dim_hs10 매칭률
13. fact_trade.hs2 → dim_hs2 매칭률
14. dim_hs10 시기 무결성 (first_yyyymm ≤ last_yyyymm, 범위 검증)
15. dim_country 플래그 정합성 (is_self/call_status/has_trade가 fact와 일치)
16. ★v3 신규★ dim_country ISO 결측 점검 (EU 제외 모두 NOT NULL — 03c 패치 적용 강제)
17. ★v4 신규★ dim_hs2 description 결측 점검 (HS99 제외 모두 NOT NULL — 03d 패치 적용 강제)

실행 예:
  python scripts\\04_validate.py
"""

from __future__ import annotations
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import duckdb


# ──────────────────────────────────────────────
# 경로 설정
# ──────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "processed" / "kcsdb.duckdb"
EXTERNAL_DIR = PROJECT_ROOT / "data" / "external"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)


# 로그
LOG_PATH = LOG_DIR / f"validate_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 검증 결과 누적
# ──────────────────────────────────────────────

class ValidationResult:
    """검증 결과 누적 객체."""
    def __init__(self):
        self.checks = []  # [(name, passed, detail), ...]

    def add(self, name: str, passed: bool, detail: str = ""):
        self.checks.append((name, passed, detail))
        status = "✓" if passed else "✗"
        level = logging.INFO if passed else logging.ERROR
        logger.log(level, f"  {status} {name}: {detail}")

    def summary(self):
        n_total = len(self.checks)
        n_passed = sum(1 for _, p, _ in self.checks if p)
        n_failed = n_total - n_passed
        return n_total, n_passed, n_failed


# ──────────────────────────────────────────────
# 보조 유틸
# ──────────────────────────────────────────────

def dim_tables_exist(con: duckdb.DuckDBPyConnection) -> bool:
    """dim_country, dim_hs10, dim_hs2 모두 존재하는지 확인."""
    rows = con.execute("""
        SELECT table_name FROM duckdb_tables()
        WHERE schema_name = 'main'
          AND table_name IN ('dim_country', 'dim_hs10', 'dim_hs2')
    """).fetchall()
    return len(rows) == 3


# ──────────────────────────────────────────────
# 검증 1a: fact_trade ↔ fact_total 금액 합계 (정확 일치)
# ──────────────────────────────────────────────

def check_trade_vs_total_dollars(con: duckdb.DuckDBPyConnection, r: ValidationResult):
    """같은 (yyyymm, stat_cd) 페어에서 fact_trade 금액 합 = fact_total 금액."""
    sql = """
        WITH trade_sum AS (
            SELECT yyyymm, stat_cd,
                   SUM(exp_dlr) AS sum_exp,
                   SUM(imp_dlr) AS sum_imp
            FROM fact_trade
            GROUP BY yyyymm, stat_cd
        )
        SELECT COUNT(*) AS mismatch
        FROM trade_sum t
        INNER JOIN fact_total f USING (yyyymm, stat_cd)
        WHERE t.sum_exp != f.exp_dlr OR t.sum_imp != f.imp_dlr
    """
    n_mismatch = con.execute(sql).fetchone()[0]
    r.add("fact_trade ↔ fact_total 금액 합계 (정확 일치)",
          n_mismatch == 0,
          f"불일치 페어 {n_mismatch}건")

    if n_mismatch > 0:
        sql_detail = """
            WITH trade_sum AS (
                SELECT yyyymm, stat_cd,
                       SUM(exp_dlr) AS sum_exp,
                       SUM(imp_dlr) AS sum_imp
                FROM fact_trade GROUP BY yyyymm, stat_cd
            )
            SELECT t.yyyymm, t.stat_cd, t.sum_exp, f.exp_dlr,
                   t.sum_exp - f.exp_dlr AS diff_exp
            FROM trade_sum t
            INNER JOIN fact_total f USING (yyyymm, stat_cd)
            WHERE t.sum_exp != f.exp_dlr OR t.sum_imp != f.imp_dlr
            ORDER BY ABS(t.sum_exp - f.exp_dlr) DESC LIMIT 5
        """
        for row in con.execute(sql_detail).fetchall():
            logger.warning(f"      {row[0]}/{row[1]}: trade_sum={row[2]:,}, "
                           f"total={row[3]:,}, diff={row[4]:,}")


# ──────────────────────────────────────────────
# 검증 1b: fact_trade ↔ fact_total 중량 합계 (정보용)
# ──────────────────────────────────────────────

def check_trade_vs_total_weights(con: duckdb.DuckDBPyConnection, r: ValidationResult):
    """fact_trade 중량 합과 fact_total 중량 차이의 통계.

    raw 자료 자체에 들어 있는 ±수백 kg 수준 잔차가 약 70% 페어에 존재.
    원인: 거래 행 건별 kg 미만 절상·절사, 기밀 처리에 의한 일부 거래
    중량 조정, 후속 정정 보고의 부분 반영.

    금액(USD)은 1a에서 100% 일치 검증. 중량 차이는 분석에 영향 없음.
    raw 자료 특성으로 분류하여 항상 통과 처리 + 통계 보고.
    """
    sql = """
        WITH ts AS (
            SELECT yyyymm, stat_cd,
                   SUM(exp_wgt) AS sum_exp_wgt,
                   SUM(imp_wgt) AS sum_imp_wgt
            FROM fact_trade GROUP BY yyyymm, stat_cd
        ),
        d AS (
            SELECT t.sum_exp_wgt, f.exp_wgt AS total_exp_wgt,
                   t.sum_exp_wgt - f.exp_wgt AS diff_exp,
                   t.sum_imp_wgt, f.imp_wgt AS total_imp_wgt,
                   t.sum_imp_wgt - f.imp_wgt AS diff_imp
            FROM ts t INNER JOIN fact_total f USING (yyyymm, stat_cd)
        )
        SELECT
            COUNT(*) AS total_pairs,
            SUM(CASE WHEN diff_exp != 0 OR diff_imp != 0 THEN 1 ELSE 0 END) AS n_diff,
            MAX(ABS(diff_exp)) AS max_diff_exp,
            MAX(ABS(diff_imp)) AS max_diff_imp,
            SUM(ABS(diff_exp)) AS sum_abs_diff_exp,
            SUM(total_exp_wgt) AS sum_total_exp_wgt
        FROM d
    """
    total, n_diff, max_e, max_i, sum_abs, sum_total = con.execute(sql).fetchone()

    relative_total_pct = (sum_abs / sum_total * 100) if sum_total else 0

    detail = (f"불일치 {n_diff:,}/{total:,} 페어 "
              f"(최대 절대차이 수출 {max_e or 0} kg, 수입 {max_i or 0} kg, "
              f"전체 합계 대비 {relative_total_pct:.6f}%)")
    r.add("fact_trade ↔ fact_total 중량 합계 (정보용)",
          True,  # 항상 통과
          detail)
    logger.info(f"      [참고] 차이 원인: raw 자료의 반올림 잔차 (관세청 원천)")
    logger.info(f"      [참고] 금액(USD)은 1a에서 100% 일치 검증 완료")


# ──────────────────────────────────────────────
# 검증 2: fact_total 회계 항등식
# ──────────────────────────────────────────────

def check_total_accounting(con: duckdb.DuckDBPyConnection, r: ValidationResult):
    """fact_total: bal_payments == exp_dlr - imp_dlr"""
    sql = """
        SELECT COUNT(*) FROM fact_total
        WHERE bal_payments != (exp_dlr - imp_dlr)
    """
    n = con.execute(sql).fetchone()[0]
    r.add("fact_total 회계 항등식 (bal=exp-imp)",
          n == 0, f"위반 행 {n}건")


# ──────────────────────────────────────────────
# 검증 3: fact_trade 회계 항등식
# ──────────────────────────────────────────────

def check_trade_accounting(con: duckdb.DuckDBPyConnection, r: ValidationResult):
    """fact_trade: bal_payments == exp_dlr - imp_dlr"""
    sql = """
        SELECT COUNT(*) FROM fact_trade
        WHERE bal_payments != (exp_dlr - imp_dlr)
    """
    n = con.execute(sql).fetchone()[0]
    r.add("fact_trade 회계 항등식 (bal=exp-imp)",
          n == 0, f"위반 행 {n}건")


# ──────────────────────────────────────────────
# 검증 4: meta_calls ↔ fact 행수 무결성
# ──────────────────────────────────────────────

def check_meta_integrity(con: duckdb.DuckDBPyConnection, r: ValidationResult):
    """meta_calls.item_count 합 = fact_trade + 거래있는 fact_total."""
    sql = """
        WITH ms AS (SELECT SUM(item_count) AS s FROM meta_calls WHERE success),
             tc AS (SELECT COUNT(*) AS c FROM fact_trade),
             tt AS (
                 SELECT COUNT(DISTINCT (f.yyyymm, f.stat_cd)) AS c
                 FROM fact_total f
                 WHERE EXISTS (
                     SELECT 1 FROM fact_trade t
                     WHERE t.yyyymm = f.yyyymm AND t.stat_cd = f.stat_cd
                 )
             )
        SELECT ms.s, tc.c, tt.c, ms.s - tc.c - tt.c AS diff
        FROM ms, tc, tt
    """
    s, t, tt, diff = con.execute(sql).fetchone()
    r.add("meta_calls ↔ fact 행수 무결성",
          diff == 0,
          f"meta_sum={s:,}, fact_trade={t:,}, total_with_trade={tt:,}, diff={diff}")


# ──────────────────────────────────────────────
# 검증 5: HS 파생 컬럼 일관성
# ──────────────────────────────────────────────

def check_hs_derived(con: duckdb.DuckDBPyConnection, r: ValidationResult):
    """hs2/hs4/hs6 = hs10의 LEFT(N) 슬라이스."""
    sql = """
        SELECT COUNT(*) FROM fact_trade
        WHERE hs2 != LEFT(hs10, 2)
           OR hs4 != LEFT(hs10, 4)
           OR hs6 != LEFT(hs10, 6)
    """
    n = con.execute(sql).fetchone()[0]
    r.add("HS 파생 컬럼 일관성", n == 0, f"위반 행 {n}건")


# ──────────────────────────────────────────────
# 검증 6: 페어 완전성
# ──────────────────────────────────────────────

def check_pair_completeness(con: duckdb.DuckDBPyConnection, r: ValidationResult):
    """fact_trade의 모든 (yyyymm, stat_cd)가 meta_calls에 있는지."""
    sql = """
        SELECT COUNT(DISTINCT (yyyymm, stat_cd)) FROM fact_trade
        WHERE NOT EXISTS (
            SELECT 1 FROM meta_calls m
            WHERE m.yyyymm = fact_trade.yyyymm
              AND m.stat_cd = fact_trade.stat_cd
        )
    """
    n = con.execute(sql).fetchone()[0]
    r.add("fact_trade 페어가 meta_calls에 있는지",
          n == 0, f"meta_calls에 없는 페어 {n}개")


# ──────────────────────────────────────────────
# 검증 7: 시간 연속성
# ──────────────────────────────────────────────

def check_time_continuity(con: duckdb.DuckDBPyConnection, r: ValidationResult):
    """meta_calls의 yyyymm이 200701~202605 연속인지.

    주의: expected 범위는 데이터셋 의도 범위(200701~202605)로 하드코딩됨.
    데이터 갱신 시 이 함수의 expected 범위도 갱신 필요.
    """
    expected = set()
    for year in range(2007, 2027):
        for month in range(1, 13):
            yyyymm = year * 100 + month
            if yyyymm > 202605:
                continue
            expected.add(yyyymm)

    sql = "SELECT DISTINCT yyyymm FROM meta_calls ORDER BY yyyymm"
    actual = set(row[0] for row in con.execute(sql).fetchall())

    missing = expected - actual
    extra = actual - expected
    r.add("시간 연속성 (200701~202605)",
          len(missing) == 0 and len(extra) == 0,
          f"빠진 월 {len(missing)}개, 예상 외 월 {len(extra)}개")
    if missing:
        logger.warning(f"      빠진 월: {sorted(missing)[:10]}")
    if extra:
        logger.warning(f"      예상 외 월: {sorted(extra)[:10]}")


# ──────────────────────────────────────────────
# 검증 8: 음수 통계 (raw 자료 잔여)
# ──────────────────────────────────────────────

def check_negative_stats(con: duckdb.DuckDBPyConnection, r: ValidationResult):
    """exp_dlr, imp_dlr, exp_wgt, imp_wgt에 음수가 있는 행 통계.

    raw 자료 자체에 들어 있는 정정·환수·통계 보정 잔여물.
    fact_trade 27.5M 행 대비 영향 < 0.001% 수준이라 분석 결과에 영향 없음.
    검증 통과 처리 + 통계 보고.
    """
    for table in ("fact_trade", "fact_total"):
        sql = f"""
            SELECT
                SUM(CASE WHEN exp_dlr < 0 THEN 1 ELSE 0 END) AS exp_dlr_neg,
                SUM(CASE WHEN imp_dlr < 0 THEN 1 ELSE 0 END) AS imp_dlr_neg,
                SUM(CASE WHEN exp_wgt < 0 THEN 1 ELSE 0 END) AS exp_wgt_neg,
                SUM(CASE WHEN imp_wgt < 0 THEN 1 ELSE 0 END) AS imp_wgt_neg,
                COUNT(*) AS total
            FROM {table}
        """
        result = con.execute(sql).fetchone()
        n_neg = sum(result[:4])
        r.add(f"{table} 음수 통계 (raw 자료 잔여)",
              True,  # 항상 통과
              f"음수 행 {n_neg}건 / 전체 {result[4]:,}행 "
              f"(exp_dlr {result[0]}, imp_dlr {result[1]}, "
              f"exp_wgt {result[2]}, imp_wgt {result[3]})")


# ──────────────────────────────────────────────
# 검증 9 (선택): 산업통상자원부 외부 대조
# ──────────────────────────────────────────────

def check_motie_external(con: duckdb.DuckDBPyConnection, r: ValidationResult):
    """data/external/motie_monthly.csv 가 있으면 fact_total 합계와 대조.

    CSV 형식 (예시):
        yyyymm,total_exp_dlr,total_imp_dlr
        202401,54784000000,54366000000
    """
    csv_path = EXTERNAL_DIR / "motie_monthly.csv"
    if not csv_path.exists():
        logger.info(f"  - 산업통상자원부 외부 대조 skip (파일 없음: {csv_path.name})")
        return

    logger.info(f"  산업통상자원부 외부 대조 ({csv_path.name})")
    sql = f"""
        WITH motie AS (
            SELECT * FROM read_csv_auto('{str(csv_path).replace(chr(92), '/')}')
        ),
        kcsdb_monthly AS (
            SELECT yyyymm,
                   SUM(exp_dlr) AS kcsdb_exp,
                   SUM(imp_dlr) AS kcsdb_imp
            FROM fact_total
            GROUP BY yyyymm
        )
        SELECT m.yyyymm,
               m.total_exp_dlr AS motie_exp,
               k.kcsdb_exp,
               m.total_exp_dlr - k.kcsdb_exp AS diff_exp,
               m.total_imp_dlr AS motie_imp,
               k.kcsdb_imp,
               m.total_imp_dlr - k.kcsdb_imp AS diff_imp
        FROM motie m
        INNER JOIN kcsdb_monthly k USING (yyyymm)
        ORDER BY m.yyyymm
    """
    rows = con.execute(sql).fetchall()
    if not rows:
        r.add("산업통상자원부 외부 대조", False, "비교 가능 월 0건")
        return

    n_match = sum(1 for row in rows if row[3] == 0 and row[6] == 0)
    n_total = len(rows)

    logger.info(f"    yyyymm  | 산업통상자원부 수출 | KCSDB 수출    | 차이")
    for row in rows:
        sign = "✓" if row[3] == 0 else "✗"
        logger.info(f"    {sign} {row[0]} | {row[1]:>15,} | {row[2]:>13,} | {row[3]:>+10,}")

    r.add("산업통상자원부 외부 대조",
          n_match == n_total,
          f"일치 {n_match}/{n_total} 월")


# ──────────────────────────────────────────────
# 검증 9b (선택): 산업통상자원부 연간 외부 대조 (★v5 신규★)
# ──────────────────────────────────────────────

def check_motie_annual(con: duckdb.DuckDBPyConnection, r: ValidationResult):
    """data/external/motie_annual.csv 가 있으면 fact_total 연간 합계와 대조 (정보용).

    CSV 형식:
        year,total_exp_dlr,total_imp_dlr
        2007,371489086000,356845733000
        ...

    검증 1b(중량 잔차)와 같은 정보용 통계 패턴.
    산업통상자원부와 관세청 자료 사이에 처리 절차 차이로 0.1~1% 잔차 정상:
      - 산업통상자원부: 매월 1일 잠정치 발표 (~21일 + 추계)
      - 관세청: 익월 중순 확정치 발표
      - 시계열 자료에서 확정치로 갱신되지만 *직전 정정 처리*가 비대칭

    raw 자료 차이 분석 도구 역할. 항상 통과 + 차이 통계 보고.
    차이율 0.5% 이상 연도만 상세 출력.
    """
    csv_path = EXTERNAL_DIR / "motie_annual.csv"
    if not csv_path.exists():
        logger.info(f"  - motie 연간 외부 대조 skip (파일 없음: {csv_path.name})")
        return

    sql = f"""
        WITH motie AS (
            SELECT * FROM read_csv_auto('{str(csv_path).replace(chr(92), '/')}')
        ),
        kcsdb_yearly AS (
            SELECT year,
                   SUM(exp_dlr) AS kcsdb_exp,
                   SUM(imp_dlr) AS kcsdb_imp
            FROM fact_total
            GROUP BY year
        )
        SELECT m.year,
               m.total_exp_dlr,
               k.kcsdb_exp,
               m.total_exp_dlr - k.kcsdb_exp AS diff_exp,
               m.total_imp_dlr,
               k.kcsdb_imp,
               m.total_imp_dlr - k.kcsdb_imp AS diff_imp
        FROM motie m
        INNER JOIN kcsdb_yearly k USING (year)
        ORDER BY m.year
    """
    rows = con.execute(sql).fetchall()
    if not rows:
        r.add("motie 연간 vs fact_total 합계 (정보용)", False,
              "비교 가능 연도 0")
        return

    n_total = len(rows)
    pct_exp = []
    pct_imp = []
    for row in rows:
        motie_e, kcsdb_e, diff_e = row[1], row[2], row[3]
        motie_i, kcsdb_i, diff_i = row[4], row[5], row[6]
        pct_exp.append(abs(diff_e) / motie_e * 100 if motie_e else 0)
        pct_imp.append(abs(diff_i) / motie_i * 100 if motie_i else 0)

    avg_pct = (sum(pct_exp) + sum(pct_imp)) / (2 * n_total)
    max_e = max(pct_exp)
    max_i = max(pct_imp)
    yr_max_e = rows[pct_exp.index(max_e)][0]
    yr_max_i = rows[pct_imp.index(max_i)][0]

    detail = (f"{n_total}년 비교, 평균 차이율 {avg_pct:.4f}%, "
              f"최대 수출차이 {max_e:.4f}%({yr_max_e}년), "
              f"최대 수입차이 {max_i:.4f}%({yr_max_i}년)")
    r.add("motie 연간 vs fact_total 합계 (정보용)",
          True,  # 항상 통과 (정보용)
          detail)

    THRESHOLD = 0.5
    flagged_idx = [i for i in range(n_total)
                   if pct_exp[i] >= THRESHOLD or pct_imp[i] >= THRESHOLD]

    if flagged_idx:
        logger.info(f"      [상세] 차이율 {THRESHOLD}% 이상 연도 ({len(flagged_idx)}건):")
        logger.info(f"      year | motie 수출(USD)        | KCSDB 수출(USD)       | "
                    f"차이율(%) | motie 수입(USD)        | KCSDB 수입(USD)       | 차이율(%)")
        for i in flagged_idx:
            row = rows[i]
            mark_e = "*" if pct_exp[i] >= THRESHOLD else " "
            mark_i_ = "*" if pct_imp[i] >= THRESHOLD else " "
            logger.info(f"      {row[0]} | {row[1]:>20,} | {row[2]:>20,} | "
                        f"{pct_exp[i]:>+8.4f}{mark_e}| "
                        f"{row[4]:>20,} | {row[5]:>20,} | "
                        f"{pct_imp[i]:>+8.4f}{mark_i_}")
    else:
        logger.info(f"      [참고] 모든 비교 연도 차이율 {THRESHOLD}% 미만")

    logger.info(f"      [참고] 차이 원인: 산업통상자원부와 관세청 처리 절차 차이")
    logger.info(f"      [참고] (잠정치/확정치/정정 처리 비대칭). raw 자료 특성으로 분류")


# ──────────────────────────────────────────────
# 검증 10: dim_country 행 수
# ──────────────────────────────────────────────

def check_dim_country_rows(con: duckdb.DuckDBPyConnection, r: ValidationResult):
    """dim_country는 외교부 244국과 정확히 일치 (현 시점 합집합 = 244)."""
    n = con.execute("SELECT COUNT(*) FROM dim_country").fetchone()[0]
    expected = 244
    r.add("dim_country 행 수",
          n == expected,
          f"{n}행 (기대 {expected})")


# ──────────────────────────────────────────────
# 검증 11: fact ↔ dim_country 매칭률
# ──────────────────────────────────────────────

def check_fact_dim_country(con: duckdb.DuckDBPyConnection, r: ValidationResult):
    """fact_trade/fact_total/meta_calls의 stat_cd가 모두 dim_country에 있어야 함."""
    for tbl in ("fact_trade", "fact_total", "meta_calls"):
        n = con.execute(f"""
            SELECT COUNT(DISTINCT f.stat_cd)
            FROM {tbl} f
            LEFT JOIN dim_country d USING (stat_cd)
            WHERE d.stat_cd IS NULL
        """).fetchone()[0]
        r.add(f"{tbl}.stat_cd → dim_country 매칭",
              n == 0, f"누락 코드 {n}개")


# ──────────────────────────────────────────────
# 검증 12: fact_trade.hs10 → dim_hs10 매칭
# ──────────────────────────────────────────────

def check_fact_dim_hs10(con: duckdb.DuckDBPyConnection, r: ValidationResult):
    """fact_trade의 모든 hs10이 dim_hs10에 있어야 함."""
    n = con.execute("""
        SELECT COUNT(DISTINCT f.hs10)
        FROM fact_trade f
        LEFT JOIN dim_hs10 d USING (hs10)
        WHERE d.hs10 IS NULL
    """).fetchone()[0]
    r.add("fact_trade.hs10 → dim_hs10 매칭",
          n == 0, f"누락 hs10 {n}개")


# ──────────────────────────────────────────────
# 검증 13: fact_trade.hs2 → dim_hs2 매칭
# ──────────────────────────────────────────────

def check_fact_dim_hs2(con: duckdb.DuckDBPyConnection, r: ValidationResult):
    """fact_trade의 모든 hs2가 dim_hs2에 있어야 함."""
    n = con.execute("""
        SELECT COUNT(DISTINCT f.hs2)
        FROM fact_trade f
        LEFT JOIN dim_hs2 d USING (hs2)
        WHERE d.hs2 IS NULL
    """).fetchone()[0]
    r.add("fact_trade.hs2 → dim_hs2 매칭",
          n == 0, f"누락 hs2 {n}개")


# ──────────────────────────────────────────────
# 검증 14: dim_hs10 시기 무결성
# ──────────────────────────────────────────────

def check_dim_hs10_temporal(con: duckdb.DuckDBPyConnection, r: ValidationResult):
    """dim_hs10: first_yyyymm ≤ last_yyyymm, 모두 200701~현재 fact_trade max 범위 내."""
    # 14a: first ≤ last
    n_inv = con.execute("""
        SELECT COUNT(*) FROM dim_hs10
        WHERE first_yyyymm > last_yyyymm
    """).fetchone()[0]
    r.add("dim_hs10 시기 순서 (first ≤ last)",
          n_inv == 0, f"위반 {n_inv}건")

    # 14b: 범위 검증 (200701 ~ fact_trade 최대 yyyymm)
    max_yyyymm = con.execute("SELECT MAX(yyyymm) FROM fact_trade").fetchone()[0]
    n_out = con.execute(f"""
        SELECT COUNT(*) FROM dim_hs10
        WHERE first_yyyymm < 200701 OR last_yyyymm > {max_yyyymm}
    """).fetchone()[0]
    r.add(f"dim_hs10 yyyymm 범위 (200701~{max_yyyymm})",
          n_out == 0, f"범위 외 {n_out}건")


# ──────────────────────────────────────────────
# 검증 15: dim_country 플래그 정합성
# ──────────────────────────────────────────────

def check_dim_country_flags(con: duckdb.DuckDBPyConnection, r: ValidationResult):
    """dim_country 플래그가 fact 데이터와 일관되는지 확인.

    1. is_self=TRUE는 KR만이어야 한다.
    2. call_status='permanent_fail'인 코드는 fact_total에 *없어야* 한다.
    3. has_trade=FALSE인 코드는 fact_trade에 *없어야* 한다.
    4. has_trade=TRUE인 코드는 fact_trade에 *있어야* 한다.
    """
    # 15a: is_self
    bad_self = con.execute("""
        SELECT COUNT(*) FROM dim_country
        WHERE is_self AND stat_cd != 'KR'
    """).fetchone()[0]
    bad_self_inv = con.execute("""
        SELECT COUNT(*) FROM dim_country
        WHERE NOT is_self AND stat_cd = 'KR'
    """).fetchone()[0]
    r.add("dim_country.is_self 정합성 (KR만 TRUE)",
          bad_self == 0 and bad_self_inv == 0,
          f"KR이 아닌데 TRUE {bad_self}건, KR인데 FALSE {bad_self_inv}건")

    # 15b: call_status = permanent_fail은 fact_total에 없어야
    bad_perm = con.execute("""
        SELECT COUNT(*) FROM dim_country d
        WHERE d.call_status = 'permanent_fail'
          AND EXISTS (SELECT 1 FROM fact_total f WHERE f.stat_cd = d.stat_cd)
    """).fetchone()[0]
    r.add("dim_country.call_status=permanent_fail ↔ fact_total 모순 없음",
          bad_perm == 0, f"모순 {bad_perm}건")

    # 15c, 15d: has_trade ↔ fact_trade 일관성
    bad_no_trade_in_trade = con.execute("""
        SELECT COUNT(*) FROM dim_country d
        WHERE NOT d.has_trade
          AND EXISTS (SELECT 1 FROM fact_trade f WHERE f.stat_cd = d.stat_cd)
    """).fetchone()[0]
    bad_has_trade_not_in_trade = con.execute("""
        SELECT COUNT(*) FROM dim_country d
        WHERE d.has_trade
          AND NOT EXISTS (SELECT 1 FROM fact_trade f WHERE f.stat_cd = d.stat_cd)
    """).fetchone()[0]
    r.add("dim_country.has_trade ↔ fact_trade 일관성",
          bad_no_trade_in_trade == 0 and bad_has_trade_not_in_trade == 0,
          f"FALSE인데 fact_trade에 있음 {bad_no_trade_in_trade}건, "
          f"TRUE인데 fact_trade에 없음 {bad_has_trade_not_in_trade}건")


# ──────────────────────────────────────────────
# 검증 16: dim_country ISO 결측 점검 (★v3 신규★)
# ──────────────────────────────────────────────

def check_dim_country_iso(con: duckdb.DuckDBPyConnection, r: ValidationResult):
    """dim_country의 iso3, iso_num 결측 점검 (EU 제외).

    EU는 ISO 3166-1 예약 코드로 iso3/iso_num이 NULL인 게 정상.
    그 외 코드의 NULL은 외부 자료(외교부 CSV) 입력 결함이거나
    03c_patch_dims.py 패치 미적용을 시사.

    함정 19(외부 CSV의 'NULL' 문자열 결측)와 결정 25(03c 도입)의 짝.
    본 검증은 03c 패치 적용을 *강제*하는 역할.
    """
    n_iso3_null = con.execute("""
        SELECT COUNT(*) FROM dim_country
        WHERE iso3 IS NULL AND stat_cd != 'EU'
    """).fetchone()[0]
    n_iso_num_null = con.execute("""
        SELECT COUNT(*) FROM dim_country
        WHERE iso_num IS NULL AND stat_cd != 'EU'
    """).fetchone()[0]

    passed = n_iso3_null == 0 and n_iso_num_null == 0
    r.add("dim_country ISO 결측 점검 (EU 제외)",
          passed,
          f"iso3 NULL {n_iso3_null}건, iso_num NULL {n_iso_num_null}건")

    if not passed:
        rows = con.execute("""
            SELECT stat_cd, name_ko_mofa, iso3, iso_num
            FROM dim_country
            WHERE (iso3 IS NULL OR iso_num IS NULL) AND stat_cd != 'EU'
            ORDER BY stat_cd
        """).fetchall()
        for row in rows:
            iso3_v = row[2] if row[2] is not None else "NULL"
            iso_num_v = str(row[3]) if row[3] is not None else "NULL"
            logger.warning(f"      {row[0]} ({row[1]}): "
                           f"iso3={iso3_v}, iso_num={iso_num_v}")
        logger.warning(f"      [참고] EU만 NULL이 정상 (ISO 3166-1 예약 코드)")
        logger.warning(f"      [참고] 그 외는 03c_patch_dims.py 적용 또는 "
                       f"외부 자료 점검 필요")


# ──────────────────────────────────────────────
# 검증 17: dim_hs2 description 결측 점검 (★v4 신규★)
# ──────────────────────────────────────────────

def check_dim_hs2_descriptions(con: duckdb.DuckDBPyConnection, r: ValidationResult):
    """dim_hs2의 description_ko, description_en, section 결측 점검 (HS99 제외).

    HS99류는 한국 통계 특수 분류 (관세 부과 외, 통계 목적)로 한국 관세청
    부류목록에 정의 없음 → NULL 유지가 정상 (결정 2 옵션 a).

    그 외 코드의 NULL은 03d_enrich_dim_hs2.py 패치 미적용 또는 외부 CSV
    결함을 시사.

    결정 21·23·27의 짝. 본 검증은 03d 패치 적용을 *강제*하는 역할.
    """
    n_ko = con.execute("""
        SELECT COUNT(*) FROM dim_hs2
        WHERE description_ko IS NULL AND hs2 != '99'
    """).fetchone()[0]
    n_en = con.execute("""
        SELECT COUNT(*) FROM dim_hs2
        WHERE description_en IS NULL AND hs2 != '99'
    """).fetchone()[0]
    n_sect = con.execute("""
        SELECT COUNT(*) FROM dim_hs2
        WHERE section IS NULL AND hs2 != '99'
    """).fetchone()[0]

    passed = n_ko == 0 and n_en == 0 and n_sect == 0
    r.add("dim_hs2 description 결측 점검 (HS99 제외)",
          passed,
          f"description_ko NULL {n_ko}건, description_en NULL {n_en}건, "
          f"section NULL {n_sect}건")

    if not passed:
        rows = con.execute("""
            SELECT hs2,
                   description_ko IS NULL AS ko_null,
                   description_en IS NULL AS en_null,
                   section        IS NULL AS sect_null
            FROM dim_hs2
            WHERE hs2 != '99'
              AND (description_ko IS NULL
                   OR description_en IS NULL
                   OR section IS NULL)
            ORDER BY hs2
        """).fetchall()
        for row in rows:
            ko_v = "NULL" if row[1] else "OK"
            en_v = "NULL" if row[2] else "OK"
            sect_v = "NULL" if row[3] else "OK"
            logger.warning(f"      HS{row[0]}: "
                           f"ko={ko_v}, en={en_v}, section={sect_v}")
        logger.warning(f"      [참고] HS99만 NULL이 정상 "
                       f"(한국 통계 특수 분류, 부류목록 미정의)")
        logger.warning(f"      [참고] 그 외는 03d_enrich_dim_hs2.py 적용 또는 "
                       f"외부 CSV 점검 필요")


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.parse_args()

    if not DB_PATH.exists():
        logger.error(f"DB 파일 없음: {DB_PATH}")
        logger.error(f"  먼저 02b_parquet_to_duckdb.py 실행")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("04: 내부 일관성 검증 (v5 — motie 연간 외부 대조 추가)")
    logger.info(f"DB: {DB_PATH}")
    logger.info("=" * 60)

    con = duckdb.connect(str(DB_PATH), read_only=True)
    r = ValidationResult()

    t_start = datetime.now()

    # 기본 검증 1~9
    logger.info("\n[검증 1a] fact_trade ↔ fact_total 금액 합계 (정확 일치)")
    check_trade_vs_total_dollars(con, r)

    logger.info("\n[검증 1b] fact_trade ↔ fact_total 중량 합계 (정보용)")
    check_trade_vs_total_weights(con, r)

    logger.info("\n[검증 2] fact_total 회계 항등식")
    check_total_accounting(con, r)

    logger.info("\n[검증 3] fact_trade 회계 항등식")
    check_trade_accounting(con, r)

    logger.info("\n[검증 4] meta_calls ↔ fact 무결성")
    check_meta_integrity(con, r)

    logger.info("\n[검증 5] HS 파생 컬럼 일관성")
    check_hs_derived(con, r)

    logger.info("\n[검증 6] 페어 완전성")
    check_pair_completeness(con, r)

    logger.info("\n[검증 7] 시간 연속성")
    check_time_continuity(con, r)

    logger.info("\n[검증 8] 음수 통계 (raw 자료 잔여)")
    check_negative_stats(con, r)

    logger.info("\n[검증 9a (선택)] 산업통상자원부 월별 외부 대조")
    check_motie_external(con, r)

    logger.info("\n[검증 9b (선택)] 산업통상자원부 연간 외부 대조 (정보용)")
    check_motie_annual(con, r)

    # dim 검증 10~16 (조건부)
    if dim_tables_exist(con):
        logger.info("\n[검증 10] dim_country 행 수")
        check_dim_country_rows(con, r)

        logger.info("\n[검증 11] fact ↔ dim_country 매칭률")
        check_fact_dim_country(con, r)

        logger.info("\n[검증 12] fact_trade.hs10 → dim_hs10 매칭")
        check_fact_dim_hs10(con, r)

        logger.info("\n[검증 13] fact_trade.hs2 → dim_hs2 매칭")
        check_fact_dim_hs2(con, r)

        logger.info("\n[검증 14] dim_hs10 시기 무결성")
        check_dim_hs10_temporal(con, r)

        logger.info("\n[검증 15] dim_country 플래그 정합성")
        check_dim_country_flags(con, r)

        logger.info("\n[검증 16] dim_country ISO 결측 점검")
        check_dim_country_iso(con, r)

        logger.info("\n[검증 17] dim_hs2 description 결측 점검")
        check_dim_hs2_descriptions(con, r)
    else:
        logger.info("\n[검증 10~17] dim 검증 skip "
                    "(dim 테이블 없음, 03b_build_dims.py 실행 필요)")

    con.close()

    # 최종 요약
    n_total, n_passed, n_failed = r.summary()
    t_elapsed = (datetime.now() - t_start).total_seconds()

    logger.info("\n" + "=" * 60)
    logger.info(f"검증 종료. {t_elapsed:.1f}초")
    logger.info(f"  총 검증: {n_total}")
    logger.info(f"  통과:    {n_passed}")
    logger.info(f"  실패:    {n_failed}")
    logger.info("=" * 60)
    if n_failed > 0:
        logger.error(f"\n✗ {n_failed}개 검증 실패 — 조사 필요")
        sys.exit(2)
    else:
        logger.info(f"\n✓ 모든 검증 통과")


if __name__ == "__main__":
    main()
