# 반조-카주이 (N64) 한글화

## 내려받기
- 최신 **v0.9** — [릴리즈](https://github.com/hospi0/banjo-kr-patch/releases/latest)에서 `BanjoKazooie_KR_v0.9.zip`
- 대상: `Banjo-Kazooie (USA) (Rev 1).z64` (빅엔디언 .z64)
- 원본md5 `B11F476D4BC8E039355241E871DC08CF` → 패치md5 `15BFD39D55FEE9ECDD9AE8E923807519`
- ★확장팩(메모리 8MB) 필수 — 에뮬레이터는 Expansion Pak 을 켜 주세요.

## 작업 저장소

- 인계·빌드 절차: **`docs/00_이어하기.md`** 부터.
- 번역 TSV: `work/text/fixed/bk_text_*.tsv` (원문·번역, 용어 교정 반영본) · 행별 교정 `work/text/fixes.tsv`
- 교정 `python tools/apply_fixes.py` → 빌드 `python tools/build.py work/text/fixed work/BK_KR.z64` → 배포 묶음 `python tools/make_dist.py`
- ROM·빌드 결과물은 들어 있지 않다.
