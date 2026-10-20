# -*- coding: utf-8 -*-
"""CPU·그래픽카드 사용량 (상단 메뉴 표시용)

- CPU: kernel32.GetSystemTimes (전체 CPU 사용률, 직전 값과의 차이로 계산)
- GPU: NVIDIA 드라이버의 nvml.dll (사용률·그래픽 메모리). 없으면(다른 회사 그래픽카드) GPU 표시 생략.
- 1회 읽기 0.03ms 수준(2026-10-02 실측, RTX 3060). 프로그램 실행·WMI 조회 없음.
"""
import os
import ctypes
import logging

log = logging.getLogger("QE.sysmon")


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
        if self._nv:
            try:
                self._nv.nvmlShutdown()
            except Exception:
                pass
            self._nv = None
