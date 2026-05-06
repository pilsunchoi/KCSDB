"""
02b 무결성 차이 4 원인 추적

가설: 일부 (월, 국가) 페어의 fact_total 행이 모든 금액·중량 0이면서도
실제 거래는 있었던 경우.

다음을 확인:
1. fact_total에서 모든 금액·중량 0인 페어 (=거래 0건으로 분류된)
   가운데 fact_trade에 같은 (yyyymm, stat_cd) 행이 있는 것
2. 즉 거래 행은 있는데 총계가 0으로 기록된 페어
"""

import duckdb
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "processed" / "kcsdb.duckdb"

con = duckdb.connect(str(DB_PATH), read_only=True)

# 1. fact_total에서 거래 0건으로 분류된 페어 중 fact_trade에 같은 페어가 있는 것
print("=== 가설 1: 총계는 0인데 거래 행이 있는 페어 ===")
sql = """
    SELECT t.yyyymm, t.stat_cd, COUNT(*) AS trade_rows,
           SUM(t.exp_dlr) AS sum_exp, SUM(t.imp_dlr) AS sum_imp,
           SUM(t.exp_wgt) AS sum_exp_wgt, SUM(t.imp_wgt) AS sum_imp_wgt
    FROM fact_trade t
    INNER JOIN fact_total f
       ON t.yyyymm = f.yyyymm AND t.stat_cd = f.stat_cd
    WHERE f.exp_dlr = 0 AND f.imp_dlr = 0 
      AND f.exp_wgt = 0 AND f.imp_wgt = 0
    GROUP BY t.yyyymm, t.stat_cd
    ORDER BY t.yyyymm, t.stat_cd
"""
result = con.execute(sql).fetchall()
print(f"  해당 페어 수: {len(result)}")
if result:
    print(f"  상세:")
    for row in result:
        print(f"    {row[0]}/{row[1]}: 거래 행 {row[2]}, sum_exp={row[3]}, sum_imp={row[4]}, sum_exp_wgt={row[5]}, sum_imp_wgt={row[6]}")

# 2. fact_total에서 거래 0건 페어 중 status JSON의 item_count는 어떻게 기록됐는지
print("\n=== 위 페어들의 meta_calls 레코드 ===")
if result:
    pairs = [(r[0], r[1]) for r in result]
    placeholders = ",".join([f"({p[0]}, '{p[1]}')" for p in pairs])
    sql = f"""
        SELECT yyyymm, stat_cd, success, result_code, item_count, response_bytes
        FROM meta_calls
        WHERE (yyyymm, stat_cd) IN ({placeholders})
        ORDER BY yyyymm, stat_cd
    """
    for row in con.execute(sql).fetchall():
        print(f"  {row[0]}/{row[1]}: success={row[2]}, code={row[3]}, item_count={row[4]}, bytes={row[5]}")

# 3. 2026년 월별 분포 (시간 범위 끝 진단)
print("\n=== 2026년 월별 분포 ===")
sql = """
    SELECT yyyymm,
           COUNT(*) AS pairs,
           SUM(success::INT) AS success_pairs,
           SUM(item_count) AS items_total
    FROM meta_calls
    WHERE yyyymm >= 202601
    GROUP BY yyyymm
    ORDER BY yyyymm
"""
for row in con.execute(sql).fetchall():
    print(f"  {row[0]}: 페어 {row[1]}, 성공 {row[2]}, item합 {row[3]}")

# 4. 2026.04 응답 샘플 (item_count 분포)
print("\n=== 2026.04 응답 샘플 (item_count 분포) ===")
sql = """
    SELECT item_count, COUNT(*) AS pair_count
    FROM meta_calls
    WHERE yyyymm = 202604 AND success
    GROUP BY item_count
    ORDER BY item_count
    LIMIT 20
"""
for row in con.execute(sql).fetchall():
    print(f"  item_count={row[0]}: 페어 {row[1]}개")

con.close()
