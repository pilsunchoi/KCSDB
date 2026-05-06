"""
검증 1 (불일치 36,241건) 추적 - 수정본
"""

import duckdb
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "processed" / "kcsdb.duckdb"
con = duckdb.connect(str(DB_PATH), read_only=True)

# 먼저 임시 테이블로 차이를 만들어 두고 그걸로 분석
con.execute("""
    CREATE TEMP TABLE diffs AS
    WITH trade_sum AS (
        SELECT yyyymm, stat_cd,
               SUM(exp_dlr) AS sum_exp,
               SUM(imp_dlr) AS sum_imp,
               SUM(exp_wgt) AS sum_exp_wgt,
               SUM(imp_wgt) AS sum_imp_wgt
        FROM fact_trade
        GROUP BY yyyymm, stat_cd
    )
    SELECT t.yyyymm, t.stat_cd,
           t.sum_exp, f.exp_dlr AS total_exp, t.sum_exp - f.exp_dlr AS diff_exp,
           t.sum_imp, f.imp_dlr AS total_imp, t.sum_imp - f.imp_dlr AS diff_imp,
           t.sum_exp_wgt, f.exp_wgt AS total_exp_wgt, t.sum_exp_wgt - f.exp_wgt AS diff_exp_wgt,
           t.sum_imp_wgt, f.imp_wgt AS total_imp_wgt, t.sum_imp_wgt - f.imp_wgt AS diff_imp_wgt
    FROM trade_sum t
    INNER JOIN fact_total f USING (yyyymm, stat_cd)
""")

n_total = con.execute("SELECT COUNT(*) FROM diffs").fetchone()[0]
print(f"=== diff 임시 테이블 ===")
print(f"  거래 있는 페어 (양쪽 join): {n_total:,}")

# 1) diff_exp의 부호별 분포
print("\n[1] diff_exp 부호 분포")
sql = """
    SELECT
        SUM(CASE WHEN diff_exp = 0 THEN 1 ELSE 0 END) AS eq,
        SUM(CASE WHEN diff_exp > 0 THEN 1 ELSE 0 END) AS pos,
        SUM(CASE WHEN diff_exp < 0 THEN 1 ELSE 0 END) AS neg,
        COUNT(*) AS total
    FROM diffs
"""
result = con.execute(sql).fetchone()
print(f"  diff_exp = 0 (일치):     {result[0]:>7,}")
print(f"  diff_exp > 0 (trade > total): {result[1]:>7,}")
print(f"  diff_exp < 0 (trade < total): {result[2]:>7,}")
print(f"  합계:                    {result[3]:>7,}")

print("\n[2] diff_imp 부호 분포")
sql = """
    SELECT
        SUM(CASE WHEN diff_imp = 0 THEN 1 ELSE 0 END),
        SUM(CASE WHEN diff_imp > 0 THEN 1 ELSE 0 END),
        SUM(CASE WHEN diff_imp < 0 THEN 1 ELSE 0 END)
    FROM diffs
"""
result = con.execute(sql).fetchone()
print(f"  diff_imp = 0: {result[0]:>7,}")
print(f"  diff_imp > 0: {result[1]:>7,}")
print(f"  diff_imp < 0: {result[2]:>7,}")

# 2) 차이의 절대값 통계
print("\n[3] |diff_exp| 통계 (불일치 페어만)")
sql = """
    SELECT MIN(ABS(diff_exp)), MAX(ABS(diff_exp)),
           AVG(ABS(diff_exp)), MEDIAN(ABS(diff_exp))
    FROM diffs
    WHERE diff_exp != 0
"""
result = con.execute(sql).fetchone()
print(f"  min={result[0]}, max={result[1]:,}, avg={result[2]:.0f}, median={result[3]:.0f}")

# 3) 차이가 1 이내, 10 이내, 100 이내인 페어 (반올림 가설)
print("\n[4] |diff_exp| 크기 분포 (불일치 페어만)")
sql = """
    SELECT
        SUM(CASE WHEN ABS(diff_exp) = 1 THEN 1 ELSE 0 END) AS eq1,
        SUM(CASE WHEN ABS(diff_exp) BETWEEN 2 AND 10 THEN 1 ELSE 0 END) AS le10,
        SUM(CASE WHEN ABS(diff_exp) BETWEEN 11 AND 100 THEN 1 ELSE 0 END) AS le100,
        SUM(CASE WHEN ABS(diff_exp) BETWEEN 101 AND 1000 THEN 1 ELSE 0 END) AS le1k,
        SUM(CASE WHEN ABS(diff_exp) BETWEEN 1001 AND 10000 THEN 1 ELSE 0 END) AS le10k,
        SUM(CASE WHEN ABS(diff_exp) > 10000 THEN 1 ELSE 0 END) AS gt10k
    FROM diffs
    WHERE diff_exp != 0
"""
result = con.execute(sql).fetchone()
print(f"  |diff| = 1:        {result[0]:>7,}  (반올림 잔차일 가능성)")
print(f"  |diff| 2~10:       {result[1]:>7,}")
print(f"  |diff| 11~100:     {result[2]:>7,}")
print(f"  |diff| 101~1k:     {result[3]:>7,}")
print(f"  |diff| 1k~10k:     {result[4]:>7,}")
print(f"  |diff| > 10k:      {result[5]:>7,}")

# 4) 차이의 상대 크기 (총계 대비)
print("\n[5] 상대 차이 |diff/total| 분포 (total>0인 행)")
sql = """
    SELECT
        SUM(CASE WHEN ABS(diff_exp::DOUBLE / total_exp) < 0.0001 THEN 1 ELSE 0 END) AS lt001pct,
        SUM(CASE WHEN ABS(diff_exp::DOUBLE / total_exp) BETWEEN 0.0001 AND 0.001 THEN 1 ELSE 0 END) AS lt01pct,
        SUM(CASE WHEN ABS(diff_exp::DOUBLE / total_exp) BETWEEN 0.001 AND 0.01 THEN 1 ELSE 0 END) AS lt1pct,
        SUM(CASE WHEN ABS(diff_exp::DOUBLE / total_exp) >= 0.01 THEN 1 ELSE 0 END) AS gt1pct,
        COUNT(*) AS n
    FROM diffs
    WHERE diff_exp != 0 AND total_exp > 0
"""
result = con.execute(sql).fetchone()
print(f"  비교 가능 페어: {result[4]:,}")
print(f"  |diff/total| < 0.01%:    {result[0]:>7,}")
print(f"  0.01~0.1%:               {result[1]:>7,}")
print(f"  0.1~1%:                  {result[2]:>7,}")
print(f"  >= 1%:                   {result[3]:>7,}")

# 5) 가장 큰 차이 10건
print("\n[6] |diff_exp|가 가장 큰 페어 10개")
sql = """
    SELECT yyyymm, stat_cd, sum_exp, total_exp, diff_exp
    FROM diffs
    WHERE diff_exp != 0
    ORDER BY ABS(diff_exp) DESC
    LIMIT 10
"""
print(f"  yyyymm/stat |   sum_exp     |  total_exp    |   diff_exp")
for row in con.execute(sql).fetchall():
    print(f"  {row[0]}/{row[1]} | {row[2]:>13,} | {row[3]:>13,} | {row[4]:>+12,}")

# 6) statKor='-' 또는 stat_kor_item이 비어있는 거래 행 (기타 분류 가설)
print("\n[7] stat_kor_item 분포")
sql = """
    SELECT
        SUM(CASE WHEN stat_kor_item = '' THEN 1 ELSE 0 END) AS empty,
        SUM(CASE WHEN stat_kor_item = '-' THEN 1 ELSE 0 END) AS dash,
        SUM(CASE WHEN stat_kor_item = '기타' THEN 1 ELSE 0 END) AS gita,
        COUNT(*) AS total
    FROM fact_trade
"""
result = con.execute(sql).fetchone()
print(f"  stat_kor_item = '':   {result[0]:>10,}")
print(f"  stat_kor_item = '-':  {result[1]:>10,}")
print(f"  stat_kor_item = '기타':{result[2]:>10,}")
print(f"  전체 거래 행:         {result[3]:>10,}")

con.close()
