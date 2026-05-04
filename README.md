# 메소 분배 디스코드 봇 (옛메 경매장 수수료 반영)

`/분배` 슬래시 명령어로 **경매장 판매가에서 수수료를 빼고** 인원수에 맞춰 N등분 해주는 봇입니다.

## 사용 예시

```
/분배 몇명:4 분배금:1000000              ← 수수료율 생략 시 기본 3%
/분배 몇명:4 분배금:1000000 수수료율:5    ← 5% 수수료
/분배 몇명:3 분배금:1000000 수수료율:0    ← 거래소 X, 직거래 분배
```

→ 임베드 출력 (예: 100만 메소, 4명, 3%)
```
💰 메소 분배 결과
📦 경매장 판매가 : 1,000,000메소
💸 수수료 (3%)   : -30,000메소
💵 실수령        : 970,000메소

970,000메소를 4명으로 분배하면
1인당 242,500메소 입니다

(나누어 떨어지지 않을 경우) 나머지 N메소는 버림 처리되었어요.
```

## 계산 규칙

| 항목 | 식 |
|------|-----|
| 수수료 | `floor(분배금 × 수수료율 / 100)` |
| 실수령 | `분배금 − 수수료` |
| 1인당 | `실수령 ÷ 몇명` (버림) |
| 나머지 | 0 이 아닐 때만 안내 문구 추가 |

---

## 1. 디스코드 봇 만들기 (5분)

1. https://discord.com/developers/applications 접속 → **New Application** → 이름 입력 후 생성
2. 좌측 **Bot** 메뉴 → **Reset Token** → 토큰 복사 (이게 `DISCORD_BOT_TOKEN`)
3. 같은 페이지에서 **Privileged Gateway Intents**는 켤 필요 없음 (이 봇은 메시지 컨텐츠 안 읽음)
4. 좌측 **OAuth2 → URL Generator**
   - SCOPES: `bot`, `applications.commands`
   - BOT PERMISSIONS: `Send Messages`, `Embed Links` 정도면 충분
5. 생성된 URL을 브라우저에서 열어 원하는 서버에 봇 초대

## 2. 로컬에서 한 번 돌려보기 (선택)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows는 .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                # .env 열어서 토큰 붙여넣기
python main.py
```
콘솔에 `로그인 성공: ... (슬래시 명령어 1개 동기화 완료)` 가 뜨면 정상.
디스코드에서 `/분배` 입력했을 때 자동완성이 안 보이면 1~2분 기다리거나 디스코드 클라이언트를 한 번 재시작하세요.

---

## 3-A. Railway에 올리기 (추천)

1. 이 폴더를 GitHub 레포지토리에 푸시 (`.env`는 `.gitignore`에 들어있어서 안 올라감)
2. https://railway.app → **New Project → Deploy from GitHub repo** → 레포 선택
3. 배포 후 **Variables** 탭 → `DISCORD_BOT_TOKEN` 추가하고 토큰 값 입력
4. **Settings → Service → Start Command**가 비어있으면 `python main.py` 입력
5. Deployments 로그에서 `로그인 성공` 메시지 확인하면 끝

> Railway는 무료 크레딧이 매월 리셋됩니다. 단순 계산 봇이라 크레딧 거의 안 씀.

## 3-B. Replit에 올리기

1. https://replit.com → **Create Repl → Import from GitHub** (또는 직접 파일 업로드)
2. 좌측 **Secrets** (자물쇠 아이콘) → `DISCORD_BOT_TOKEN` 추가
3. **Run** 버튼 클릭 → 콘솔에서 정상 동작 확인
4. 24시간 켜두려면 Replit의 **Always On**(유료) 옵션 또는 별도 keep-alive 설정 필요

---

## 파일 구성

| 파일 | 설명 |
|------|------|
| `main.py` | 봇 본체. `/분배` 슬래시 명령어 한 개 |
| `requirements.txt` | discord.py, python-dotenv |
| `.env.example` | 환경변수 템플릿 (실제 `.env`는 본인이 만들어 토큰 입력) |
| `Procfile` | Railway/Heroku 호환 worker 실행 명령 |
| `runtime.txt` | Python 버전 고정 (3.11.9) |
| `.gitignore` | `.env`, 가상환경 등 제외 |

## 동작 규칙 메모

- **단위**: 입력·출력 모두 메소
- **수수료**: 옵션, 기본값 3%, 0~100 범위
- **버림 처리**: 수수료·1인당 모두 floor (소수점 절사)
- **나머지 안내**: 0이 아닐 때만 안내 문구 추가
- **입력 범위 제한**: 몇명 1~1,000,000 / 분배금 1~10조 / 수수료율 0~100 (디스코드 슬래시 옵션 자체에서 차단)
