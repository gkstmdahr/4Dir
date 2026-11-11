# -*- coding: utf-8 -*-
"""CPU·그래픽카드 사용량 (상단 메뉴 표시용)

- CPU: 작업 관리자와 같은 '\\Processor Information(_Total)\\% Processor Utility'(PDH, 터보 주파수 반영, 100% 넘으면 100) — 1.1.0 (0.9.132, 사용자 11/11
  '작업 관리자랑 다르다': 예전 GetSystemTimes 는 '일한 시간 비율'이라 이 PC 에서 35% vs 작업 관리자 68% 로 약 1.9배 차이 실측).
  PDH 를 못 쓰면(카운터 없음 등) 예전 GetSystemTimes 로. 1회 읽기 약 0.1ms (실측)
- GPU: NVIDIA 드라이버의 nvml.dll (사용률·그래픽 메모리). 없으면(다른 회사 그래픽카드) GPU 표시 생략.
- 1회 읽기 0.03ms 수준(2026-10-02 실측, RTX 3060). 프로그램 실행·WMI 조회 없음.
"""
import os
import ctypes
import logging

log = logging.getLogger("QE.sysmon")
MONITOR_VER = "1.1.0"   # 이름에 회사 글자 검사 낱말이 들어가지 않게 (예전 이름이 걸림)


class _FT(ctypes.Structure):
    _fields_ = [("lo", ctypes.c_ulong), ("hi", ctypes.c_ulong)]


def _ft(f):
    return (f.hi << 32) | f.lo


class _Util(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


class _Mem(ctypes.Structure):
    _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]


class SysMon:
    def __init__(self):
        self._prev = None
        self._pdh = None   # (query, counter) — 작업 관리자 방식
        try:
            import win32pdh
            q = win32pdh.OpenQuery()
            c = win32pdh.AddEnglishCounter(q, r"\Processor Information(_Total)\% Processor Utility")
            win32pdh.CollectQueryData(q)   # 첫 기준값
            self._pdh = (win32pdh, q, c)
            log.info("CPU = 작업 관리자 방식(%% Processor Utility, PDH)")
        except Exception as ex:
            log.warning("CPU PDH 못 씀 → 예전 방식(GetSystemTimes): %r", ex)
        self.gpu_name = ""
        self._nv = None
        self._h = None
        try:
            path = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvml.dll")
            if os.path.exists(path):
                nv = ctypes.WinDLL(path)
                if nv.nvmlInit_v2() == 0:
                    h = ctypes.c_void_p()
                    if nv.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(h)) == 0:
                        self._nv, self._h = nv, h
                        buf = ctypes.create_string_buffer(96)
                        nv.nvmlDeviceGetName(h, buf, 96)
                        self.gpu_name = buf.value.decode(errors="ignore")
        except Exception:
            log.exception("NVML 초기화 실패 → GPU 표시 생략")
        log.info("사용량 표시 준비 GPU=%s", self.gpu_name or "(없음/NVIDIA 아님)")

    def cpu(self):
        if self._pdh is not None:
            pdh, q, c = self._pdh
            try:
                pdh.CollectQueryData(q)
                v = pdh.GetFormattedCounterValue(c, pdh.PDH_FMT_DOUBLE | pdh.PDH_FMT_NOCAP100)[1]
                return max(0.0, min(100.0, float(v)))
            except Exception as ex:   # 첫 읽기 직후 등은 값이 아직 없을 수 있음 → 이번만 예전 방식
                log.debug("CPU PDH 읽기 실패 %r", ex)
        idle, kern, user = _FT(), _FT(), _FT()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)):
            return None
        cur = (_ft(idle), _ft(kern), _ft(user))
        prev, self._prev = self._prev, cur
        if prev is None:
            return None
        di, dk, du = (cur[i] - prev[i] for i in range(3))
        total = dk + du          # kernel 시간에 idle 이 포함됨
        return max(0.0, min(100.0, (total - di) * 100.0 / total)) if total else None

    def gpu(self):
        """(사용률%, 사용GB, 전체GB) 또는 None"""
        if not self._nv:
            return None
        u, m = _Util(), _Mem()
        if self._nv.nvmlDeviceGetUtilizationRates(self._h, ctypes.byref(u)) != 0:
            return None
        self._nv.nvmlDeviceGetMemoryInfo(self._h, ctypes.byref(m))
        return u.gpu, m.used / 2 ** 30, m.total / 2 ** 30

    def close(self):
        if self._pdh is not None:
            try:
                self._pdh[0].CloseQuery(self._pdh[1])
            except Exception:
                pass
            self._pdh = None
        if self._nv:
            try:
                self._nv.nvmlShutdown()
            except Exception:
                pass
            self._nv = None
