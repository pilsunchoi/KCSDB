
"""
2024년 raw 파일 진단:
- 각 파일의 item 수, year='총계'인 행 수, hsCd='-'인 행 수를 세서
- status JSON과 비교
- 161행 차이의 원인 추적
"""
import gzip, json, re
from pathlib import Path
import xml.etree.ElementTree as ET

PROJECT_ROOT = Path(r"C:\Projects\KCSDB")
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "2024"
STATUS_PATH = PROJECT_ROOT / "data" / "raw" / ".progress" / "status_2024.json"

with open(STATUS_PATH, "r", encoding="utf-8") as f:
    status = json.load(f)

multi_total = []  # 총계 행이 2개 이상인 파일
no_total = []     # 총계 행이 0개인 파일 (resultCode 00인데)
mismatch = []     # status item_count와 실제 item 수가 다른 파일

count = 0
total_items = 0
total_trades = 0
total_totals = 0

for fp in sorted(RAW_DIR.glob("*.xml.gz")):
    count += 1
    with gzip.open(fp, "rb") as f:
        tree = ET.parse(f)
    root = tree.getroot()
    rc = root.findtext(".//resultCode")
    items = root.findall(".//item")

    n_total_rows = sum(1 for it in items if it.findtext("year") == "총계")
    n_trade_rows = len(items) - n_total_rows

    total_items += len(items)
    total_trades += n_trade_rows
    total_totals += n_total_rows

    # status와 비교
    key = fp.stem.replace(".xml", "")
    s = status.get(key, {})
    s_count = s.get("item_count", 0)
    s_success = s.get("success", False)

    if s_success and rc == "00":
        if n_total_rows == 0 and len(items) > 0:
            no_total.append((fp.name, len(items)))
        if n_total_rows > 1:
            multi_total.append((fp.name, n_total_rows))
        if s_count != len(items):
            mismatch.append((fp.name, s_count, len(items)))

print(f"=== 2024년 raw 진단 ===")
print(f"파일 수: {count}")
print(f"item 총합: {total_items:,}")
print(f"  거래 행: {total_trades:,}")
print(f"  총계 행: {total_totals:,}")
print()
print(f"총계 행 2개 이상인 파일: {len(multi_total)}")
for fn, n in multi_total[:10]:
    print(f"  {fn}: {n}개")
print()
print(f"총계 행 0개인 파일 (rc=00, items>0): {len(no_total)}")
for fn, n in no_total[:5]:
    print(f"  {fn}: items={n}")
print()
print(f"status.item_count != 실제 items 수: {len(mismatch)}")
for fn, s, a in mismatch[:5]:
    print(f"  {fn}: status={s}, actual={a}")
