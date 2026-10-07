# 반조-카주이 한글 패치

## 내려받기

### N64판
- 최신 **v0.9** — [릴리즈 v0.9](https://github.com/hospi0/banjo-kr-patch/releases/tag/v0.9)에서 `BanjoKazooie_KR_v0.9.zip`
- 대상: `Banjo-Kazooie (USA) (Rev 1).z64` (빅엔디언 .z64)
- 원본md5 `B11F476D4BC8E039355241E871DC08CF` → 패치md5 `15BFD39D55FEE9ECDD9AE8E923807519`
- ★확장팩(메모리 8MB) 필수 — 에뮬레이터는 Expansion Pak 을 켜 주세요.

### 엑스박스 360 XBLA판 (Xenia 전용)
- 최신 **v0.9** — [릴리즈 x360-v0.9](https://github.com/hospi0/banjo-kr-patch/releases/tag/x360-v0.9)에서 `BanjoKazooie_X360_KR_v0.9.zip`
- 사용법: 압축을 푼 폴더에 원본 LIVE 패키지 파일(타이틀 ID 58410954, 원본md5 `7B79170FA9D7847C8422934BC2A59E98`)을 넣고 「패치적용.bat」 실행 → `Banjo Kazooie KR\` 폴더에 한글판이 만들어짐(패키지를 따로 풀 필요 없음)
- 한글은 «일본어» 언어 자리에 들어감 → Xenia `config\Banjo-Kazooie.config.toml` 의 `[XConfig]` 에 `user_language = 2`
- **패키지판**: 같은 릴리즈의 `BanjoKazooie_X360_KR_v0.9_package.zip` — 원본 LIVE 패키지에 바로 적용해 한글 LIVE 패키지 파일 `Banjo Kazooie [KR]` 하나를 만듦(패치md5 `7A87E4A8AD3F4FCFC0FD057A2FF15164`) → Xenia 에서 그 파일을 엶. 내용은 폴더판과 같음(`tools/make_dist_x360_pkg.py`, 패키지 다시 쌓기 `tools/stfs.py`)

## 작업 저장소

- 인계·빌드 절차: **`docs/00_이어하기.md`** 부터.
- 번역 TSV: `work/text/fixed/bk_text_*.tsv` (원문·번역, 용어 교정 반영본) · 행별 교정 `work/text/fixes.tsv`
- N64: 교정 `python tools/apply_fixes.py` → 빌드 `python tools/build.py work/text/fixed work/BK_KR.z64` → 배포 묶음 `python tools/make_dist.py`
- 360: 빌드 `python tools/x360build.py work/text/fixed <출력폴더> --write` → 배포 묶음 `python tools/make_dist_x360.py`
  - 360 에서 바뀐 대사·360 전용 대사 `work/text/x360_kr.tsv` · 메뉴 `work/text/x360_ui.tsv` · xex 안 문자열 `work/text/x360_xex.tsv` · 엔딩 크레딧 `work/text/x360_credits.tsv`
- ROM·게임 파일·빌드 결과물은 들어 있지 않다.
