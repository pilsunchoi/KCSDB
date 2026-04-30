# API 발급 및 환경 설정 절차

본 문서는 공공데이터포털 인증키 발급부터 로컬 환경 구축까지의 전 과정을 기록합니다.
학생들이 처음부터 따라할 수 있도록 작성합니다.

본 환경은 **Windows + Anaconda(conda)** 기준입니다.

---

## 1. 공공데이터포털 가입 및 인증키 발급

### 절차

1. **회원가입**: https://www.data.go.kr 접속 → 우측 상단 "회원가입"
2. **로그인** 후 메인 페이지에서 데이터 ID 검색

### 신청 대상 API

#### 1순위 (필수)
- **관세청_품목별 국가별 수출입실적(GW)**
  - URL: https://www.data.go.kr/data/15100475/openapi.do
  - 검색어: `15100475` 또는 `품목별 국가별 수출입실적`

#### 2순위 (보조·검증용)
- 관세청_월별_품목별_국가별 수출입실적 — `15116432`
- 관세청_국가별 수출입실적(GW) — `15101612`
- 관세청_품목별 수출입실적(GW) — `15101609`

### 신청 시 입력 사항

| 항목 | 권장 입력 |
|---|---|
| 인증유형 | 일반 인증키 (REST API) |
| 활용용도 | 연구/교육 |
| 활용목적 | "한국 무역구조 변화 연구를 위한 데이터셋 구축" |
| 약관 동의 | 필수 |

### 승인
- 개발계정: 자동승인 (즉시 또는 수 분)
- 승인 후 **마이페이지 → 인증키** 에서 확인

### 인증키 두 형태 — Decoding 키를 사용

발급 후 두 형태가 보입니다:
- **Encoding 키**: URL 인코딩된 형태 (`%2B`, `%3D` 등 포함)
- **Decoding 키**: 원본 형태 (`+`, `=` 등 포함)

**우리는 Decoding 키를 사용합니다.**

이유: Python `requests` 라이브러리는 URL 파라미터를 자동으로 인코딩합니다.
- Decoding 키 사용 시: requests가 자동으로 인코딩 → 정상 동작
- Encoding 키 사용 시: 이미 인코딩된 키를 다시 인코딩 → 이중 인코딩 발생 → 인증 실패

이건 공공데이터포털 사용자가 가장 흔히 빠지는 함정입니다.

---

## 2. 로컬 환경 구축 (Windows + Anaconda)

### 사전 요구사항

- [ ] Anaconda 또는 Miniconda 설치 (https://www.anaconda.com/download)
- [ ] Git 설치 (https://git-scm.com/download/win)
- [ ] VS Code 또는 다른 에디터
- [ ] GitHub 계정

### Anaconda 설치 확인 (cmd)

```cmd
conda --version
```

출력 예: `conda 24.x.x`

### 작업 폴더로 이동

본 가이드는 `C:\Projects\KCSDB` 를 가정합니다. 본인 환경에 맞게 조정하세요.

```cmd
cd C:\Projects\KCSDB
```

### 프로젝트 스켈레톤 압축 해제

AI가 제공한 `korea-trade-db.zip` 을 위 폴더에 풀면 다음 구조가 됩니다:

```
C:\Projects\KCSDB\
├── README.md
├── .gitignore
├── requirements.txt
├── config\
├── docs\
├── scripts\
├── data\
├── notebooks\
└── tests\
```

### conda 환경 생성

**중요**: 만약 프롬프트에 `(base)` 가 표시되어 있다면, Anaconda의 base 환경이 활성화된 상태입니다. 새 환경을 만들기 전에 base에서 빠져나옵니다:

```cmd
conda deactivate
```

새 환경 생성:

```cmd
conda create -n kcsdb python=3.12 -y
```

`-n kcsdb` : 환경 이름. 프로젝트명과 동일하게 지정.
`python=3.12` : Python 버전.
`-y` : 모든 확인 자동 yes.

### 환경 활성화

```cmd
conda activate kcsdb
```

활성화 확인 — 프롬프트가 다음과 같이 변해야 함:

```
(kcsdb) C:\Projects\KCSDB>
```

추가 확인:

```cmd
where python
where pip
```

출력 경로에 `envs\kcsdb` 가 포함되어야 함:
```
C:\Users\본인계정\anaconda3\envs\kcsdb\python.exe
C:\Users\본인계정\anaconda3\envs\kcsdb\Scripts\pip.exe
```

만약 `envs\kcsdb`가 안 보이고 그냥 `anaconda3\python.exe`만 나오면 활성화 실패. `conda activate kcsdb` 다시 실행.

### 패키지 설치

```cmd
pip install --upgrade pip
pip install -r requirements.txt
```

설치되는 주요 패키지:
- requests, lxml: API 호출 및 XML 파싱
- pandas, numpy: 데이터 처리
- duckdb, pyarrow: 저장 (DuckDB / Parquet)
- python-dotenv, pyyaml: 설정 관리
- tqdm: 진행률 표시
- pytest, jupyter: 개발/탐색

### 인증키 등록

`config\api_key.env.example` 파일을 `config\api_key.env` 로 복사:

```cmd
copy config\api_key.env.example config\api_key.env
```

VS Code 또는 메모장으로 `config\api_key.env` 열기:

```cmd
notepad config\api_key.env
```

내용을 다음과 같이 수정 (Decoding 키를 그대로 붙여넣기):

```
DATA_GO_KR_API_KEY=실제_발급받은_Decoding_키
```

**주의사항**:
- `=` 양쪽에 공백 넣지 말 것
- 키를 따옴표로 감싸지 말 것
- 키 앞뒤 공백 없도록
- 키가 `=`로 끝나는 경우(Base64 패딩) 그건 키의 일부

### 설정 파일 복사

```cmd
copy config\settings.yaml.example config\settings.yaml
```

(현 단계에서는 수정 불필요)

### Git 초기화

```cmd
git init
git add .
git commit -m "Initial project skeleton"
```

### GitHub 레포 연결

GitHub에서 새 공개 레포 생성 (예: `korea-trade-db`).

⚠️ 레포 생성 시 **README, .gitignore, License 초기화 옵션 모두 OFF**. 우리가 이미 만들어 둔 파일과 충돌함.

생성 후 안내되는 URL을 사용:

```cmd
git remote add origin https://github.com/YOUR_USERNAME/korea-trade-db.git
git branch -M main
git push -u origin main
```

### 첫 푸시 후 보안 점검 ★중요★

GitHub 웹페이지에서 본인 레포 접속하여:

- [ ] README.md 가 정상 표시되는가
- [ ] `config/api_key.env` 가 ★보이지 않는가★
- [ ] `data/raw/`, `data/interim/`, `data/processed/` 폴더가 ★보이지 않는가★

**만약 `api_key.env` 가 GitHub에 보인다면**:
1. 즉시 공공데이터포털에서 해당 키 폐기 또는 재발급
2. `.gitignore` 점검
3. Git 히스토리에서 제거 (BFG Repo-Cleaner 등 사용)
4. 강제 푸시로 재반영

GitHub은 봇이 24시간 키를 스캔합니다. 한 번이라도 노출된 키는 폐기가 정공법.

---

## 3. 작동 확인 (다음 단계 예고)

위 셋업 완료 후, AI와 함께 `scripts/00_test_api.py` 작성:
- 인증키 로드
- 최소 호출 (1년 1월, 미국, HS 1001999090)
- XML 응답 raw 저장 (디버깅용)
- XML → pandas DataFrame 변환
- 응답 구조 출력
- 미해결 질문 Q1–Q8 (`docs/02_api_spec_analysis.md`) 답변

---

## 사용자 기록 영역

본인이 작업하면서 발생한 문제·해결책을 여기 기록:

### 이슈: `(base)` 환경에서 venv 활성화 시도

처음에는 `python -m venv .venv` + `.venv\Scripts\Activate.ps1` 로 진행 시도.
프롬프트가 `(base)` 그대로 유지되며 `pip`이 Anaconda 경로를 가리킴.

**원인**: 두 가지 동시 발생
1. Anaconda base 환경이 활성화된 상태에서 venv 생성·활성화 시도 → venv가 base 위에 덮이지 않고 base가 그대로 남음
2. cmd에서 `Activate.ps1` (PowerShell 전용 스크립트) 실행 → 무시됨

**해결**: conda 환경 방식으로 전환
- `conda deactivate` → base 빠져나옴
- `conda create -n kcsdb` → 별도 환경 생성
- `conda activate kcsdb` → 활성화

이후 모든 패키지 설치가 `kcsdb` 환경으로 들어감.

### 학생들에게 강조할 점

1. **프롬프트의 `(env명)` 표시를 항상 확인**. `(base)` 와 `(kcsdb)` 는 다른 환경.
2. **cmd vs PowerShell 구분**. `Activate.ps1` 은 PowerShell 전용, `activate.bat` 은 cmd 전용. conda 명령은 둘 다에서 동작.
3. **`where python` 으로 실제 사용되는 Python 위치 확인** 가능.
4. **Anaconda 사용자는 conda 환경 사용을 권장**. venv와 conda를 섞으면 혼란.
