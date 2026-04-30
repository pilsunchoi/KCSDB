# API 명세 분석: 관세청_품목별 국가별 수출입실적(GW)

본 문서는 공공데이터포털 Swagger UI 명세 + 시범 호출 결과를 통합한 **최종 분석**입니다.

## 학생용 핵심 교훈

> **"API 명세서는 출발점이지 도착점이 아니다."**
>
> 명세서에는 누락·모호한 부분이 흔합니다. 본격 수집 코드를 짜기 전에:
> 1. 명세에서 명시된 것과 불명확한 것을 구분
> 2. 불명확한 부분을 답할 시범 호출을 설계
> 3. 시범 결과로 명세를 보완한 뒤 본격 수집

본 프로젝트에서 시범 호출이 발견한 명세-실제 불일치:
- 명세서에 "옵션"이라 표기된 hsSgn, cntyCd가 실제로는 "조건부 필수"
- 명세서에 페이지네이션 파라미터가 누락
- year 필드가 `2024.01` 같은 소수점 형식

---

## 1. 확정 정보

### Endpoint

```
http://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList    # HTTP
https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList   # HTTPS (권장)
```

### 응답 형식
- XML

### 요청 파라미터

| 영문명 | 자릿수 | 명세 표기 | **실제 동작** | 의미 |
|---|---|---|---|---|
| `serviceKey` | 100 | 필수 | 필수 | 인증키 |
| `strtYymm` | 6 | 필수 | 필수 | 시작년월 (YYYYMM) |
| `endYymm` | 6 | 필수 | 필수 | 종료년월 (YYYYMM) |
| `hsSgn` | 10 | 옵션 | **조건부 필수** | HS 코드 |
| `cntyCd` | 2 | 옵션 | **조건부 필수** | 국가코드 (ISO2) |

**조건부 필수**: hsSgn 과 cntyCd 중 **최소 하나는 반드시 지정**해야 함. 둘 다 생략 시 `resultCode 99` 거부:
> "품목코드 혹은 국가코드 중 1개 이상은 입력하셔야 합니다."

### 응답 필드

| 영문명 | 한국어 | 단위/형식 | 비고 |
|---|---|---|---|
| `resultCode` | 결과코드 | `00`=성공, `99`=오류 | header 안 |
| `resultMsg` | 결과메시지 | "정상서비스." 등 | header 안 |
| `year` | 기간 | `2024.01` 형식 | **소수점 — 문자열 처리** |
| `statCdCntnKor1` | 국가명 | 한국어 ("미국") | |
| `statCd` | 국가코드 | ISO2 (`US`) | |
| `statKor` | 품명 | 한국어 + 학명 | 매우 자세 |
| `hsCd` | HS코드 | 10자리 문자열 | 끝 4자리 `0000` = HS6 padding |
| `expWgt` | 수출중량 | kg | 순중량 |
| `expDlr` | 수출금액 | **USD** | 천USD 아님 |
| `impWgt` | 수입중량 | kg | |
| `impDlr` | 수입금액 | **USD** | |
| `balPayments` | 무역수지 | USD | expDlr - impDlr |

### 응답 구조 (XML)

```xml
<response>
  <header>
    <resultCode>00</resultCode>
    <resultMsg>정상서비스.</resultMsg>
  </header>
  <body>
    <items>
      <item>  <!-- 첫 번째: 총계 행 -->
        <year>총계</year>
        <hsCd>-</hsCd>
        <statCd>-</statCd>
        ...
      </item>
      <item>  <!-- 이후: HS10별 행 -->
        <year>2024.01</year>
        <hsCd>0105111000</hsCd>
        <statCd>US</statCd>
        ...
      </item>
      ...
    </items>
  </body>
</response>
```

**중요**: 모든 응답에 첫 행으로 **총계 행** 포함. `year=총계, hsCd=-, statCd=-`.

### 갱신 정보
- 매월 15일경 전월까지 자료 현행화
- 수출 FOB / 수입 CIF, USD

### 한도
- 개발계정: 일일 10,000건
- 운영계정: 활용사례 등록 시 증액

---

## 2. 시범 호출 답변 (Q1~Q8)

### Q1. 페이지네이션 — **미동작 ★결정적★**

`numOfRows`, `pageNo` 무시됨. 한 호출이 그 조건의 전체 결과를 반환.

### Q2. hsSgn 생략 시 — **HS10 풀 해상도**

모든 HS10 품목 포함. 끝 4자리 `0000` 인 행은 그 HS6 단위에서 더 세분화 안 된 품목.

### Q3. cntyCd 생략 시 — **거부됨**

cntyCd 생략하려면 hsSgn을 반드시 지정해야 함. **둘 다 생략 불가**.

### Q4. statCd 형식 — **ISO 알파-2**

관세청이 ISO 코드 표준 사용. `US`, `JP`, `CN` 등 2자리. 특수 케이스는 본격 수집 후 직접 검증.

### Q5. 금액 단위 — **USD 그대로 ★확정★**

검증: 2024.1 對미국 expDlr 합 = 10,250,440,138 ≈ 102.5억 USD = 산업통상자원부 발표치 일치.

### Q6. 한 달치 응답 크기

對미국 단일국가 한 달: 6,415건 / 1.76 MB.

전세계 추산: 한 달 평균 호출당 30KB~수 MB. 총 17년 데이터 추정 ~7천만 건, 압축 후 2~5 GB.

### Q7. HTTPS — **동작 ★확정★**

### Q8. year 형식 — **`2024.01` + `총계` 한글 ★확정★**

문자열 처리 필수.

---

## 3. 본격 수집 전략 (최종)

### 호출 단위: (월, 국가)

```python
params = {
    "serviceKey": API_KEY,
    "strtYymm": "YYYYMM",  # 한 달
    "endYymm": "YYYYMM",   # 같은 달
    "cntyCd": "XX",        # 단일 국가 (ISO2)
    # hsSgn 생략 → HS10 풀 해상도
}
```

### 시간 분할: 월별

연 단위 호출도 가능하지만 메모리·처리 부담. **월별 단일 호출 권장**.

### 국가 분할: 모든 ISO2 코드

전세계 약 230개 코드 모두 시도. 0건 응답은 정상 처리.

### 호출 수 추산

```
17년 × 12개월 × 230국 = 46,920 호출
```

일일 한도 10,000회 → 5일 분산 실행.

### 안정성 요건

장기 작업이므로:

1. **재시작 가능 (idempotent)**: 받은 (월,국가) 페어 skip
2. **체크포인트 로그**: 어느 페어까지 완료했는지 누적 기록
3. **지수 백오프 재시도**: 일시 오류, 5xx 응답
4. **rate limiting**: 일일 한도 도달 시 graceful exit
5. **로그**: 진행 상황, 실패 케이스 누적

### 데이터 저장

- **raw**: `data/raw/{YYYY}/{YYYYMM}_{CC}.xml.gz` — 압축 저장
- **interim**: `data/interim/{YYYYMM}.parquet` — 파싱·정규화된 월별 Parquet
- **processed**: `data/processed/trade.duckdb` — 최종 통합 DuckDB

### 추가 자료원

국가 코드 dim 테이블:
- 외교부 국가표준코드 (data.go.kr/data/15091117) — 공식 ISO + 한국어 명칭
- ISO 3166-1 표준 (`pycountry` 라이브러리)

---

## 4. 학생용 시범 호출 사례 정리

### Step 1~8 (00_test_api.py) 결과 요약

| Step | 조건 | 결과 | 학습 포인트 |
|---|---|---|---|
| 1 | hsSgn=8517120000, cntyCd=US | 0건 | 특정 HS10 코드는 데이터 없을 수 있음 |
| 2 | + pageNo, numOfRows | 0건 | 페이지네이션 파라미터 무시됨 |
| 3 | hsSgn 생략, cntyCd=US | 6,415건 | hsSgn 생략 시 HS10 풀 해상도 |
| 4 | hsSgn=8517120000, cntyCd 생략 | 0건 | hsSgn 단독 + 데이터 없음 |
| 5 | hsSgn 생략, numOfRows=1000 | 6,415건 | numOfRows 무시 (Step 3과 동일 결과) |
| 6 | HTTPS 호출 | 정상 | HTTPS 동작 |
| 7 | strtYymm=202401, endYymm=202412 | 0건 | 12개월 자체는 OK (hsSgn 때문에 0건) |
| 8 | strtYymm=202401, endYymm=202501 | 거부 | 13개월 명시적 거부 |

### Step 9 (00b_test_no_cntycd.py) 결과

| 조건 | 결과 | 학습 포인트 |
|---|---|---|
| hsSgn 생략, cntyCd 생략 | resultCode 99 거부 | 둘 중 하나는 반드시 필요 |

### 위 결과로 도출된 본격 수집의 핵심 원칙

1. hsSgn 생략 + cntyCd 단일 지정 + 월별 단일 호출
2. 응답 첫 행은 총계, 적재 시 별도 처리
3. year 필드 문자열 보존
4. HS10 = 끝 4자리 의미 있는 것만 진짜 HS10
5. 일일 10,000회 한도 관리하며 5~7일 분산 실행
