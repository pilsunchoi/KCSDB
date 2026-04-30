# 학생용 교훈 정리

본 문서는 프로젝트 진행 중 발견된 함정과 우회법을 정리합니다.
학생들이 비슷한 작업을 할 때 시행착오를 줄이는 것이 목적입니다.

---

## 함정 1: 공공데이터포털의 두 인증키

발급 시 **Encoding 키**와 **Decoding 키** 두 가지가 보입니다. 어느 것을 써야 하는지 헷갈립니다.

**원칙**: Python `requests` 라이브러리 등 자동 인코딩 도구를 쓰면 **Decoding 키**.

**이유**: requests가 URL 파라미터를 자동 인코딩합니다.
- Decoding 키 → requests가 인코딩 → 1회 인코딩 → 정상
- Encoding 키 → requests가 또 인코딩 → 2회 인코딩(예: `%2B` → `%252B`) → 인증 실패

`curl` 등 자동 인코딩 안 하는 도구를 쓸 때만 Encoding 키가 적절합니다.

이 함정에서 빠져나오는 데 몇 시간씩 쓰는 사람이 많습니다.

---

## 함정 2: Anaconda base 환경 + venv 충돌

Anaconda 설치 PC에서 프롬프트에 `(base)` 가 표시된 상태로 venv를 만들면, venv가 활성화되지 않습니다.

**증상**:
- `python -m venv .venv` → 환경 폴더는 만들어짐
- `.venv\Scripts\Activate.ps1` → 프롬프트 그대로 `(base)`
- `pip` 명령이 Anaconda의 pip을 가리킴

**원인**: base 환경이 이미 활성화되어 있어 venv가 그 위에 덮이지 않음. 게다가 cmd에서 `Activate.ps1`은 PowerShell 전용이라 무시됨.

**해결**:
- Anaconda 사용자는 venv 대신 conda 환경 사용
  ```cmd
  conda deactivate
  conda create -n 환경이름 python=3.12 -y
  conda activate 환경이름
  ```
- 또는 base에서 빠져나온 후 venv의 cmd용 활성화 스크립트 사용
  ```cmd
  conda deactivate
  .venv\Scripts\activate.bat
  ```

**확인 방법**: `where python` 명령으로 실제 사용되는 Python 경로 확인.

---

## 함정 3: cmd vs PowerShell 차이

Windows에는 두 가지 셸이 있고, 활성화 스크립트가 다릅니다.

| 셸 | 프롬프트 형식 | venv 활성화 |
|---|---|---|
| cmd.exe | `C:\path>` | `.venv\Scripts\activate.bat` |
| PowerShell | `PS C:\path>` | `.venv\Scripts\Activate.ps1` |

conda 환경 활성화는 **둘 다에서 동일**하게 `conda activate 이름`.

PowerShell에서 `Activate.ps1` 실행 시 실행정책 오류가 나면 한 번:
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

---

## 함정 4: 인증키의 GitHub 노출

`.gitignore`에 인증키 파일이 등록되어 있어도, 다음 경우에 노출됩니다:

- `.gitignore` 등록 *전*에 이미 커밋된 경우 (히스토리에 남음)
- 인증키를 코드에 직접 하드코딩한 경우
- 설정 파일을 부주의하게 커밋한 경우

GitHub은 봇이 24시간 신규 커밋의 키를 스캔합니다. 노출 즉시 키가 도용될 수 있습니다.

**원칙**:
1. 인증키 파일은 항상 별도 디렉토리(`config/`)에 두고 `.gitignore`에 즉시 등록
2. 첫 푸시 후 GitHub 웹페이지에서 키 파일이 *없는지* 반드시 확인
3. 한 번이라도 노출되었다면 즉시 키 폐기 후 재발급

---

(이후 시범 호출 단계, 본격 수집 단계에서 발견되는 함정 추가 예정)
