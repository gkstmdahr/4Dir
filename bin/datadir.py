# -*- coding: utf-8 -*-
"""설정·메모·로그 등 '사용자 데이터'를 둘 폴더 (DATADIR_VER 1.0.0, 0.9.114 빌드 2 — MS 스토어판 1단계)

- 압축판(지금처럼): 프로그램 폴더의 bin 그대로 (휴대용 — 폴더째 옮기면 설정도 같이). 아무것도 안 바뀜.
- 스토어판(MSIX 로 설치): 설치 폴더가 읽기 전용 → %LOCALAPPDATA%\\4Dir 에 둠 (윈도우가 앱별로 따로 보관, 지우면 같이 지워짐).
- 시험·특수: 환경 변수 QE_DATA_DIR 이 있으면 그 폴더.
스토어판 확인 = GetCurrentPackageFullName 이 성공하면 '패키지로 설치되어 실행 중'.
"""
import os
import ctypes

DATADIR_VER = "1.0.0"
CODE_DIR = os.path.dirname(os.path.abspath(__file__))   # bin (프로그램 파일·번역·그림 — 읽기만)


def _packaged():
    try:
        n = ctypes.c_uint32(0)
        r = ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(n), None)
        return r != 15700   # APPMODEL_ERROR_NO_PACKAGE 가 아니면 패키지 (버퍼 부족 122 등)
    except (AttributeError, OSError):
        return False   # 윈도우 7 등 함수 없음


PACKAGED = os.environ.get("QE_PACKAGED") == "1" or _packaged()


def _pick():
    env = os.environ.get("QE_DATA_DIR")
    if env:
        return os.path.abspath(env)
    if PACKAGED:
        return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "4Dir")
    return CODE_DIR


DATA_DIR = _pick()
if DATA_DIR != CODE_DIR:
    os.makedirs(DATA_DIR, exist_ok=True)


def path(*parts):
    return os.path.join(DATA_DIR, *parts)
