"""
Q3 확정용 추가 시험: cntyCd 생략 시 동작
==============================================

목적
----
Step 4(00_test_api.py)에서 cntyCd 생략 + hsSgn 지정 → 0건 결과를 받았으나,
이게 cntyCd 생략 때문인지 hsSgn=8517120000 자체가 0건이어서인지 분리되지 않았음.

본 스크립트는:
1. cntyCd, hsSgn 둘 다 생략하여 *모든* 한 달치 데이터를 받음
2. 응답에서 발견되는 statCd 의 종류와 형식을 분석
3. 국가 분해가 되는지(=국가별 행이 다수) 또는 통합 합계만 오는지 확인

실행
----
    cd C:\\Projects\\KCSDB
    conda activate kcsdb
    python scripts/00b_test_no_cntycd.py
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from collections import Counter
import xml.etree.ElementTree as ET

import requests
from dotenv import load_dotenv


# ============================================================
# 1. 환경 설정 (00_test_api.py 와 동일 패턴)
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEST_OUT_DIR = PROJECT_ROOT / "data" / "raw" / "test"
TEST_OUT_DIR.mkdir(parents=True, exist_ok=True)

ENV_PATH = PROJECT_ROOT / "config" / "api_key.env"
if not ENV_PATH.exists():
    print(f"[FATAL] {ENV_PATH} 없음")
    sys.exit(1)

load_dotenv(ENV_PATH)
API_KEY = os.getenv("DATA_GO_KR_API_KEY")
if not API_KEY or API_KEY.startswith("여기에"):
    print("[FATAL] 인증키 미설정")
    sys.exit(1)

print(f"[OK] 인증키 로드: {API_KEY[:4]}...{API_KEY[-4:]} (length={len(API_KEY)})")
print()


# ============================================================
# 2. 호출
# ============================================================

# HTTPS 사용 (Q7 결과)
URL = "https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList"

# 단 하나의 호출: cntyCd, hsSgn 둘 다 생략
# 단순 검증 목적이므로 timeout 넉넉히 (전세계 한 달치는 응답 매우 클 수 있음)
params = {
    "serviceKey": API_KEY,
    "strtYymm": "202401",
    "endYymm": "202401",
}

print("=" * 70)
print("  Q3 시험: cntyCd 와 hsSgn 모두 생략한 한 달치 호출")
print("=" * 70)
print(f"  URL: {URL}")
print(f"  Params: {{'strtYymm': '202401', 'endYymm': '202401'}}")
print(f"  (호출 시작... 응답이 클 경우 수십 초 걸릴 수 있음)")

try:
    response = requests.get(URL, params=params, timeout=300)  # 5분 타임아웃
except requests.exceptions.RequestException as e:
    print(f"  [ERROR] 요청 실패: {e}")
    sys.exit(1)

print(f"  Status: {response.status_code}")
print(f"  Response size: {len(response.content):,} bytes ({len(response.content) / 1024 / 1024:.2f} MB)")

# raw 저장
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
out_path = TEST_OUT_DIR / f"{timestamp}_step9_no_country_no_hs.xml"
out_path.write_bytes(response.content)
print(f"  Saved: {out_path.relative_to(PROJECT_ROOT)}")
print()


# ============================================================
# 3. 응답 분석
# ============================================================

try:
    root = ET.fromstring(response.content)
except ET.ParseError as e:
    print(f"  [ERROR] XML 파싱 실패: {e}")
    print(f"  Response preview: {response.text[:500]}")
    sys.exit(1)

# 결과 코드
result_codes = [e.text for e in root.iter("resultCode")]
result_msgs = [e.text for e in root.iter("resultMsg")]
print(f"  resultCode: {result_codes}, resultMsg: {result_msgs}")

# 모든 item 수집
items = list(root.iter("item"))
print(f"  Total <item> count: {len(items):,}")
print()

if not items:
    print("[WARNING] item 0건. 호출이 실제로 데이터를 반환하지 않음.")
    sys.exit(0)


# ============================================================
# 4. statCd 분석 (Q3 + Q4 보강)
# ============================================================

print("-" * 70)
print("  statCd 분석")
print("-" * 70)

statcds = []
years = []
hs_lengths = []   # hsCd 자릿수
hs_padded = 0     # 끝 4자리가 0000 인 경우 (HS6 padding)

for item in items:
    stat = item.findtext("statCd", default="")
    year = item.findtext("year", default="")
    hs = item.findtext("hsCd", default="")

    statcds.append(stat)
    years.append(year)
    if hs and hs != "-":
        hs_lengths.append(len(hs))
        if hs.endswith("0000"):
            hs_padded += 1

statcd_counter = Counter(statcds)
print(f"  Unique statCd values: {len(statcd_counter)}")
print(f"  Top 20 statCd by frequency:")
for code, count in statcd_counter.most_common(20):
    print(f"    {code!r:>10} : {count:>6,}")

# 코드 길이 분포
length_counter = Counter(len(c) for c in statcd_counter.keys())
print(f"\n  statCd length distribution (unique codes):")
for length, count in sorted(length_counter.items()):
    print(f"    {length}-char : {count}")

# 특수 케이스 검색
print(f"\n  특수 statCd 검색:")
special_cases = {
    "GB": "영국 (ISO2)",
    "UK": "영국 (대체)",
    "TW": "대만 (ISO2)",
    "TA": "대만 (대체)",
    "HK": "홍콩",
    "MO": "마카오",
    "PR": "푸에르토리코",
    "KP": "북한",
}
for code, label in special_cases.items():
    found = code in statcd_counter
    cnt = statcd_counter.get(code, 0)
    marker = "✓" if found else "✗"
    print(f"    [{marker}] {code} ({label}) : {cnt}")


# ============================================================
# 5. year / hsCd 분석
# ============================================================

print()
print("-" * 70)
print("  year 필드 분석")
print("-" * 70)
year_counter = Counter(years)
print(f"  Unique year values: {len(year_counter)}")
for y, c in year_counter.most_common(10):
    print(f"    {y!r:>12} : {c:>6,}")

print()
print("-" * 70)
print("  hsCd 분석")
print("-" * 70)
print(f"  Items with non-empty hsCd: {len(hs_lengths):,}")
hs_length_counter = Counter(hs_lengths)
print(f"  hsCd length distribution:")
for length, count in sorted(hs_length_counter.items()):
    print(f"    {length}-char : {count:,}")
print(f"  hsCd ending in '0000' (likely HS6-level): {hs_padded:,}")
print(f"  hsCd not ending in '0000' (true HS10): {len(hs_lengths) - hs_padded:,}")


# ============================================================
# 6. 첫 행 / 총계 행 / 끝 행 샘플
# ============================================================

print()
print("-" * 70)
print("  샘플 행")
print("-" * 70)

def print_item(item, label):
    print(f"  {label}:")
    for child in item:
        text = (child.text or "").strip()
        if len(text) > 60:
            text = text[:60] + "..."
        print(f"    <{child.tag}>: {text}")

print_item(items[0], "First item")
print()
if len(items) > 1:
    print_item(items[1], "Second item")
print()
if len(items) > 100:
    print_item(items[100], "Item #100 (mid-sample)")
print()
print_item(items[-1], "Last item")


# ============================================================
# 7. 결론 자동 도출
# ============================================================

print()
print("=" * 70)
print("  자동 진단")
print("=" * 70)

unique_country_count = len([c for c in statcd_counter if c not in ("-", "")])
total_items = len(items)

print(f"  총 item 수: {total_items:,}")
print(f"  고유 국가 코드 수 (총계 '-' 제외): {unique_country_count}")

if unique_country_count > 50:
    print(f"  → 국가 분해됨. cntyCd 생략 시 모든 국가 데이터 반환됨. ✓")
elif unique_country_count > 1:
    print(f"  → 일부 국가만 반환. 부분적 분해.")
else:
    print(f"  → 국가 분해 안 됨. 통합 합계만 반환.")

print()
print(f"  → 본격 수집 전략 결정에 반영하여 docs/02_api_spec_analysis.md 갱신 예정.")
