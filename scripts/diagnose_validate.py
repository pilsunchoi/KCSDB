"""
04_validate 실패 원인 추적

검증 1 (fact_trade ↔ fact_total 합계 불일치 36,241건): 패턴 분석
검증 8 (fact_trade 음수 19행): 19행 모두 출력
"""

import duckdb
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "processed" / "kcsdb.duckdb"
con = duckdb.connect(str(DB_PATH), read_only=True)


# ──────────────────────────────────────────────
# 검증 8 추적: 음수 19행
# ──────────────────────────────────────────────

print("=" * 70)
print("검증 8 추적: fact_trade 음수 19행")
print("=" * 70)
sql = """
    SELECT yyyymm, stat_cd, hs10, stat_kor_item,
           exp_dlr, imp_dlr, exp_wgt, imp_wgt, bal_payments
    FROM fact_trade
    WHERE exp_dlr < 0 OR imp_dlr < 0
       OR exp_wgt < 0 OR imp_wgt < 0
    ORDER BY yyyymm, stat_cd
"""
for row in con.execute(sql).fetchall():
    print(f"  {row[0]}/{row[1]}/{row[2]}: {row[3][:30]}")
    print(f"    exp_dlr={row[4]:>15,}, imp_dlr={row[5]:>15,}")
    print(f"    exp_wgt={row[6]:>15,}, imp_wgt={row[7]:>15,}")
    print(f"    bal={row[8]:,}")


# ──────────────────────────────────────────────
# 검증 1 추적: 불일치 36,241건의 패턴
# ──────────────────────────────────────────────

print("\n" + "=" * 70)
print("검증 1 추적: 불일치 36,241건 패턴 분석")
print("=" * 70)

# 1) 차이 크기 분포
print("\n[1] 수출 차이(trade_sum - total) 크기 분포")
sql = """
    WITH trade_sum AS (
        SELECT yyyymm, stat_cd,
               SUM(exp_dlr) AS sum_exp,
               SUM(imp_dlr) AS sum_imp
        FROM fact_trade
        GROUP BY yyyymm, stat_cd
    ),
    diffs AS (
        SELECT t.yyyymm, t.stat_cd,
               t.sum_exp - f.exp_dlr AS diff_exp,
               t.sum_imp - f.imp_dlr AS diff_imp,
               f.exp_dlr AS total_exp,
               f.imp_dlr AS total_imp
        FROM trade_sum t
        INNER JOIN fact_total f USING (yyyymm, stat_cd)
        WHERE t.sum_exp != f.exp_dlr OR t.sum_imp != f.imp_dlr
    )
    SELECT
        SUM(CASE WHEN diff_exp = 0 THEN 1 ELSE 0 END) AS exp_eq,
        SUM(CASE WHEN diff_exp > 0 THEN 1 ELSE 0 END) AS exp_pos,
        SUM(CASE WHEN diff_exp < 0 THEN 1 ELSE 0 END) AS exp_neg,
        SUM(CASE WHEN diff_imp = 0 THEN 1 ELSE 0 END) AS imp_eq,
        SUM(CASE WHEN diff_imp > 0 THEN 1 ELSE 0 END) AS imp_pos,
        SUM(CASE WHEN diff_imp < 0 THEN 1 ELSE 0 END) AS imp_neg
    FROM diffs
"""
result = con.execute(sql).fetchone()
print(f"  diff_exp: =0:{result[0]}, >0:{result[1]}, <0:{result[2]}")
print(f"  diff_imp: =0:{result[3]}, >0:{result[4]}, <0:{result[5]}")

# 2) 차이의 상대 크기 (총계 대비 %)
print("\n[2] 차이의 상대 크기 (수출 차이 / 총계 수출 × 100, 절대값)")
sql = """
    WITH trade_sum AS (
        SELECT yyyymm, stat_cd, SUM(exp_dlr) AS sum_exp
        FROM fact_trade GROUP BY yyyymm, stat_cd
    ),
    diffs AS (
        SELECT t.yyyymm, t.stat_cd,
               ABS(t.sum_exp - f.exp_dlr) AS abs_diff,
               f.exp_dlr AS total_exp
        FROM trade_sum t
        INNER JOIN fact_total f USING (yyyymm, stat_cd)
        WHERE t.sum_exp != f.exp_dlr
          AND f.exp_dlr > 0
    )
    SELECT
        SUM(CASE WHEN abs_diff::DOUBLE / total_exp < 0.0001 THEN 1 ELSE 0 END) AS lt_001pct,
        SUM(CASE WHEN abs_diff::DOUBLE / total_exp BETWEEN 0.0001 AND 0.001 THEN 1 ELSE 0 END) AS lt_01pct,
        SUM(CASE WHEN abs_diff::DOUBLE / total_exp BETWEEN 0.001 AND 0.01 THEN 1 ELSE 0 END) AS lt_1pct,
        SUM(CASE WHEN abs_diff::DOUBLE / total_exp BETWEEN 0.01 AND 0.1 THEN 1 ELSE 0 END) AS lt_10pct,
        SUM(CASE WHEN abs_diff::DOUBLE / total_exp >= 0.1 THEN 1 ELSE 0 END) AS gt_10pct
    FROM diffs
"""
result = con.execute(sql).fetchone()
print(f"  < 0.01%: {result[0]:,}")
print(f"  0.01~0.1%: {result[1]:,}")
print(f"  0.1~1%: {result[2]:,}")
print(f"  1~10%: {result[3]:,}")
print(f"  > 10%: {result[4]:,}")

# 3) 가장 차이가 큰 페어 10개
print("\n[3] 차이가 가장 큰 페어 10개 (절대값)")
sql = """
    WITH trade_sum AS (
        SELECT yyyymm, stat_cd, SUM(exp_dlr) AS sum_exp, SUM(imp_dlr) AS sum_imp
        FROM fact_trade GROUP BY yyyymm, stat_cd
    )
    SELECT t.yyyymm, t.stat_cd,
           t.sum_exp, f.exp_dlr, t.sum_exp - f.exp_dlr AS diff_exp,
           t.sum_imp, f.imp_dlr, t.sum_imp - f.imp_dlr AS diff_imp
    FROM trade_sum t
    INNER JOIN fact_total f USING (yyyymm, stat_cd)
    WHERE t.sum_exp != f.exp_dlr OR t.sum_imp != f.imp_dlr
    ORDER BY ABS(t.sum_exp - f.exp_dlr) + ABS(t.sum_imp - f.imp_dlr) DESC
    LIMIT 10
"""
print(f"  yyyymm/stat | trade_exp - total_exp = diff | trade_imp - total_imp = diff")
for row in con.execute(sql).fetchall():
    print(f"  {row[0]}/{row[1]}: "
          f"E:{row[2]:>13,} - {row[3]:>13,} = {row[4]:>+12,} | "
          f"I:{row[5]:>13,} - {row[6]:>13,} = {row[7]:>+12,}")

# 4) statKor='-' 행 (기타 분류) 가설 점검
# 한 페어의 거래 행 중 stat_kor_item='-'인 행이 있는지
print("\n[4] 'stat_kor_item=-' 행이 있는 페어 (기타 분류 가설)")
sql = """
    SELECT COUNT(DISTINCT (yyyymm, stat_cd))
    FROM fact_trade
    WHERE stat_kor_item = '-' OR stat_kor_item = ''
"""
n = con.execute(sql).fetchone()[0]
print(f"  stat_kor_item이 '-' 또는 빈 문자열인 거래 행이 있는 페어: {n}")

# 5) 한 불일치 페어의 raw 행 분포 보기 (가장 차이 큰 페어)
print("\n[5] 가장 차이 큰 페어의 거래 행 마지막 5건 (분류 함정 확인)")
sql_top = """
    WITH trade_sum AS (
        SELECT yyyymm, stat_cd, SUM(exp_dlr) AS sum_exp
        FROM fact_trade GROUP BY yyyymm, stat_cd
    )
    SELECT t.yyyymm, t.stat_cd
    FROM trade_sum t
    INNER JOIN fact_total f USING (yyyymm, stat_cd)
    WHERE t.sum_exp != f.exp_dlr
    ORDER BY ABS(t.sum_exp - f.exp_dlr) DESC
    LIMIT 1
"""
top_pair = con.execute(sql_top).fetchone()
print(f"  대상: {top_pair[0]}/{top_pair[1]}")
sql_detail = f"""
    SELECT hs10, stat_kor_item, exp_dlr, imp_dlr
    FROM fact_trade
    WHERE yyyymm = {top_pair[0]} AND stat_cd = '{top_pair[1]}'
    ORDER BY hs10 DESC
    LIMIT 5
"""
for row in con.execute(sql_detail).fetchall():
    print(f"    hs10={row[0]}, kor='{row[1]}', exp={row[2]:,}, imp={row[3]:,}")

con.close()
