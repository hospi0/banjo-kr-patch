# -*- coding: utf-8 -*-
r"""XBLA(엑스박스 360) 배포 묶음 — dist/BanjoKazooie_X360_KR_v0.9/
  (파일별 xdelta 4개 + xdelta.exe + readme.txt + 패치적용.bat)

  python tools/x360build.py work/text/fixed <출력폴더> --write   # 먼저 빌드
  python tools/make_dist_x360.py [출력폴더]                       # xdelta 생성 → 원본에 적용해 바이트 대조

대상 = LIVE 패키지를 풀어 둔 폴더(default.xex, RAWFiles\). Xenia 전용(암호화·서명 안 함), 언어는 일본어로.
규칙: 해시는 MD5 대문자 · 한국어 문서는 CP949(CRLF) · 버전은 v0.9 한 자리 · bat 의 if 블록 안 echo 에 괄호 금지.
"""
import hashlib, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)

VER = 'v0.9'
SRC_DIR = os.path.join(ROOT, 'work', 'x360', 'pkg')            # LIVE 패키지(F:\hospi\roms\xbox360 roms\Banjo Kazooie)를 푼 것
OUT_DIR = r'F:\hospi\roms\xbox360 roms\Banjo Kazooie KR'
FILES = ['default.xex', r'RAWFiles\db360.cmp', r'RAWFiles\db360.textures.cmp', r'RAWFiles\X360_strings.dat']
PKG = 'BanjoKazooie_X360_KR_' + VER
DIST = os.path.join(ROOT, 'dist', PKG)
XDELTA = r'C:\claude\utils\xdelta.exe'


def md5(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 22), b''):
            h.update(b)
    return h.hexdigest()


README = """반조-카주이 (엑스박스 360 XBLA) 한글 패치 {ver}
==========================================

엑스박스 라이브 아케이드판 Banjo-Kazooie (타이틀 ID 58410954) 용입니다.
Xenia 에뮬레이터 전용입니다(실기는 시험하지 않았습니다).

한글은 게임의 「일본어」 언어 자리에 들어갑니다.


[ 적용 방법 ]

1. LIVE 패키지 파일(Banjo Kazooie, 약 50MB)을 Velocity · Horizon · wxPirs 같은
   도구로 폴더에 풀어 둡니다. 폴더에 default.xex 와 RAWFiles 폴더가 있어야 합니다.
2. 이 패치 묶음을 통째로 그 폴더에 풀고 「패치적용.bat」 을 실행합니다.
3. 배치가 파일 4개의 원본 MD5 를 확인하고, 패치한 뒤 결과 MD5 까지 검사합니다.
   원본은 .bak 으로 남겨 둡니다.

원본md5 / 패치md5
{table}

4. Xenia 의 게임 설정 파일(config\\Banjo-Kazooie.config.toml)에서
   언어를 일본어로 바꿉니다.

   [XConfig]
   user_language = 2

5. Xenia 에서 그 폴더의 default.xex 를 엽니다.


[ 바뀌는 것 ]

■ 대사 전부(오프닝 데모·등장인물 대화), 그런티의 퀴즈
■ 360판에서 바뀐 버튼 설명(RT·LT·RB·LB·X·Y·스틱), 360 전용 대사
■ 타이틀·메뉴·설정·조작법·설명서·파일 선택·일시정지·순위표 메뉴
■ 시스템 메시지 상자(저장 실패 등), 엔딩 출연진 이름, 엔딩 크레딧 직함
■ 타이틀 로고는 영문 로고로 바뀝니다


[ 알려진 사항 ]

■ 엔딩 크레딧의 사람 이름은 영어 그대로입니다.
■ 세계에 들어갈 때 나오는 지역 이름 그림은 일본어 그대로입니다.
"""

BAT = r"""@echo off
setlocal
set PATCHDIR=%~dp0

echo.
echo  ==============================================
echo    Banjo-Kazooie ^(XBLA^) Korean Patch {ver}
echo  ==============================================
echo.

if not exist "default.xex" (
  echo  [!] default.xex 가 이 폴더에 없습니다.
  echo      LIVE 패키지를 푼 폴더에서 실행하세요.
  goto END
)
if not exist "%PATCHDIR%xdelta.exe" (
  echo  [!] xdelta.exe 가 없습니다. 패치 묶음을 그대로 풀고 실행하세요.
  goto END
)

{calls}
echo.
echo  [OK] 한글 패치 완료. 원본은 .bak 으로 남겨 두었습니다.
echo       Xenia 언어를 일본어(user_language = 2)로 바꾼 뒤 default.xex 를 여세요.
goto END

:APPLY
set NAME=%~1
set PATCH=%~2
set SRCMD5=%~3
set DSTMD5=%~4
echo  - %NAME%
if not exist "%NAME%" (
  echo  [!] "%NAME%" 파일이 없습니다.
  goto FAIL
)
set HASH=
for /f "skip=1 tokens=* delims=" %%H in ('certutil -hashfile "%NAME%" MD5') do (
  if not defined HASH set HASH=%%H
)
set HASH=%HASH: =%
if /I "%HASH%"=="%DSTMD5%" (
  echo    이미 패치된 파일입니다. 건너뜁니다.
  exit /b 0
)
if /I not "%HASH%"=="%SRCMD5%" (
  echo  [!] 원본 MD5 가 다릅니다. 필요 %SRCMD5% / 현재 %HASH%
  goto FAIL
)
"%PATCHDIR%xdelta.exe" -d -f -s "%NAME%" "%PATCHDIR%%PATCH%" "%NAME%.kr"
if errorlevel 1 (
  echo  [!] 패치에 실패했습니다.
  if exist "%NAME%.kr" del "%NAME%.kr"
  goto FAIL
)
set HASH2=
for /f "skip=1 tokens=* delims=" %%H in ('certutil -hashfile "%NAME%.kr" MD5') do (
  if not defined HASH2 set HASH2=%%H
)
set HASH2=%HASH2: =%
if /I not "%HASH2%"=="%DSTMD5%" (
  echo  [!] 결과 MD5 가 다릅니다. 원본은 그대로 둡니다.
  del "%NAME%.kr"
  goto FAIL
)
move /y "%NAME%" "%NAME%.bak" >nul
move /y "%NAME%.kr" "%NAME%" >nul
exit /b 0

:FAIL
echo.
echo  중단했습니다.
pause
exit

:END
echo.
pause
endlocal
"""


def write_cp949(path, text):
    data = text.replace('\r\n', '\n').replace('\n', '\r\n').encode('cp949')
    with open(path, 'wb') as f:
        f.write(data)


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else OUT_DIR
    if os.path.exists(DIST):
        shutil.rmtree(DIST)
    os.makedirs(DIST)
    rows, calls = [], []
    for f in FILES:
        src, dst = os.path.join(SRC_DIR, f), os.path.join(out_dir, f)
        pname = os.path.basename(f) + '.xdelta'
        patch = os.path.join(DIST, pname)
        subprocess.run([XDELTA, '-e', '-9', '-S', 'djw', '-f', '-s', src, dst, patch], check=True)
        chk = os.path.join(ROOT, 'work', 'dist_check.bin')
        subprocess.run([XDELTA, '-d', '-f', '-s', src, patch, chk], check=True)
        sm, dm = md5(src).upper(), md5(dst).upper()
        ok = md5(chk).upper() == dm
        os.remove(chk)
        if not ok:
            raise SystemExit('⛔ xdelta 되짚기 결과가 패치본과 다르다: ' + f)
        rows.append((f, sm, dm, os.path.getsize(patch)))
        calls.append('call :APPLY "%s" "%s" %s %s' % (f, pname, sm, dm))
    shutil.copyfile(XDELTA, os.path.join(DIST, 'xdelta.exe'))
    table = '\n'.join('  %-28s %s\n  %-28s -> %s' % (f, s, '', d) for f, s, d, _ in rows)
    write_cp949(os.path.join(DIST, 'readme.txt'), README.format(ver=VER, table=table))
    write_cp949(os.path.join(DIST, '패치적용.bat'), BAT.format(ver=VER, calls='\n'.join(calls)))
    zp = shutil.make_archive(DIST, 'zip', os.path.dirname(DIST), PKG)
    print('✅ %s (되짚기 일치)' % DIST)
    for f, s, d, n in rows:
        print('   %-28s %s → %s  xdelta %s B' % (f, s, d, format(n, ',')))
    print('   zip %s (%s B)' % (zp, format(os.path.getsize(zp), ',')))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
