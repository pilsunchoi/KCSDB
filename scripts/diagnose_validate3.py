"""
검증 1 추적 v3: 차이는 중량에서만 발생함이 확인됐으니 중량만 분석
"""

import duckdb
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "processed" / "kcsdb.duckdb"
con = duckdb.connect(str(DB_PATH), read_only=True)

con.execute("""
    CREATE TEMP TABLE wgt_diffs AS
    WITH ts AS (
        SELECT yyyymm, stat_cd,
               SUM(exp_wgt) AS sum_exp_wgt,
               SUM(imp_wgt) AS sum_imp_wgt
        FROM fact_trade
        GROUP BY yyyymm, stat_cd
    )
    SELECT t.yyyymm, t.stat_cd,
           t.sum_exp_wgt, f.exp_wgt AS total_exp_wgt,
           t.sum_exp_wgt - f.exp_wgt AS diff_exp,
           t.sum_imp_wgt, f.imp_wgt AS total_imp_wgt,
           t.sum_imp_wgt - f.imp_wgt AS diff_imp
    FROM ts t
    INNER JOIN fact_total f USING (yyyymm, stat_cd)
""")

# 부호 분포
print("=== 중량 차이 부호 분포 ===")
sql = """
    SELECT
        SUM(CASE WHEN diff_exp = 0 THEN 1 ELSE 0 END),
        SUM(CASE WHEN diff_exp > 0 THEN 1 ELSE 0 END),
        SUM(CASE WHEN diff_exp < 0 THEN 1 ELSE 0 END),
        SUM(CASE WHEN diff_imp = 0 THEN 1 ELSE 0 END),
        SUM(CASE WHEN diff_imp > 0 THEN 1 ELSE 0 END),
        SUM(CASE WHEN diff_imp < 0 THEN 1 ELSE 0 END)
    FROM wgt_diffs
"""
r = con.execute(sql).fetchone()
print(f"  diff_exp_wgt = 0:  {r[0]:>7,}    diff_imp_wgt = 0:  {r[3]:>7,}")
print(f"  diff_exp_wgt > 0:  {r[1]:>7,}    diff_imp_wgt > 0:  {r[4]:>7,}")
print(f"  diff_exp_wgt < 0:  {r[2]:>7,}    diff_imp_wgt < 0:  {r[5]:>7,}")

# 불일치 행수
n_mismatch = con.execute("""
    SELECT COUNT(*) FROM wgt_diffs
    WHERE diff_exp != 0 OR diff_imp != 0
""").fetchone()[0]
print(f"\n불일치 페어 수 (둘 중 하나라도): {n_mismatch:,}")

# 중량 차이 절대값 분포
print("\n=== |diff_exp_wgt| 크기 분포 (불일치만) ===")
sql = """
    SELECT
        SUM(CASE WHEN ABS(diff_exp) = 1 THEN 1 ELSE 0 END),
        SUM(CASE WHEN ABS(diff_exp) BETWEEN 2 AND 10 THEN 1 ELSE 0 END),
        SUM(CASE WHEN ABS(diff_exp) BETWEEN 11 AND 100 THEN 1 ELSE 0 END),
        SUM(CASE WHEN ABS(diff_exp) BETWEEN 101 AND 1000 THEN 1 ELSE 0 END),
        SUM(CASE WHEN ABS(diff_exp) BETWEEN 1001 AND 10000 THEN 1 ELSE 0 END),
        SUM(CASE WHEN ABS(diff_exp) > 10000 THEN 1 ELSE 0 END)
    FROM wgt_diffs WHERE diff_exp != 0
"""
r = con.execute(sql).fetchone()
labels = ["= 1", "2~10", "11~100", "101~1k", "1k~10k", "> 10k"]
for lab, val in zip(labels, r):
    print(f"  |diff_exp_wgt| {lab}:  {val:,}")

# 상대 차이 (총계 대비)
print("\n=== |diff_exp_wgt / total_exp_wgt| 상대 분포 (total>0) ===")
sql = """
    SELECT
        SUM(CASE WHEN ABS(diff_exp::DOUBLE / total_exp_wgt) < 0.0001 THEN 1 ELSE 0 END),
        SUM(CASE WHEN ABS(diff_exp::DOUBLE / total_exp_wgt) BETWEEN 0.0001 AND 0.001 THEN 1 ELSE 0 END),
        SUM(CASE WHEN ABS(diff_exp::DOUBLE / total_exp_wgt) BETWEEN 0.001 AND 0.01 THEN 1 ELSE 0 END),
        SUM(CASE WHEN ABS(diff_exp::DOUBLE / total_exp_wgt) >= 0.01 THEN 1 ELSE 0 END)
    FROM wgt_diffs
    WHERE diff_exp != 0 AND total_exp_wgt > 0
"""
r = con.execute(sql).fetchone()
print(f"  < 0.01%:    {r[0]:,}")
print(f"  0.01~0.1%:  {r[1]:,}")
print(f"  0.1~1%:     {r[2]:,}")
print(f"  >= 1%:      {r[3]:,}")

# 가장 차이 큰 페어 10개
print("\n=== |diff_exp_wgt|이 가장 큰 페어 10개 ===")
sql = """
    SELECT yyyymm, stat_cd, sum_exp_wgt, total_exp_wgt, diff_exp
    FROM wgt_diffs WHERE diff_exp != 0
    ORDER BY ABS(diff_exp) DESC LIMIT 10
"""
for row in con.execute(sql).fetchall():
    print(f"  {row[0]}/{row[1]}: trade_sum={row[2]:>13,}, total={row[3]:>13,}, diff={row[4]:>+10,}")

print("\n=== |diff_imp_wgt|이 가장 큰 페어 10개 ===")
sql = """
    SELECT yyyymm, stat_cd, sum_imp_wgt, total_imp_wgt, diff_imp
    FROM wgt_diffs WHERE diff_imp != 0
    ORDER BY ABS(diff_imp) DESC LIMIT 10
"""
for row in con.execute(sql).fetchall():
    print(f"  {row[0]}/{row[1]}: trade_sum={row[2]:>13,}, total={row[3]:>13,}, diff={row[4]:>+10,}")

con.close()
