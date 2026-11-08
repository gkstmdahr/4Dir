# -*- coding: utf-8 -*-
"""소리 파형 미리보기 (AUDIOPREV_VER 1.0.0, 0.9.116 — 사용자 11/8 요청 '미리보기 창에서 형식별로 보기: 소리')

- 미리보기 창에 끼우는 위젯: can_handle(path) (.wav .mp3 .ogg .flac .m4a .aac .wma .opus, 확장자만) · make_widget(path, parent)
- 정보: ffmpeg -i 출력에서 길이·채널·표본 빈도·비트 깊이 (runtime\\ffmpeg\\ffmpeg.exe, 창 안 띄움)
- 파형: 뒤 스레드에서 ffmpeg 로 모노 8000Hz s16le 로 풀어(앞 10분까지) 칸마다 최소·최대값만 모아 그림. 읽는 동안 조금씩 그려짐
- 재생: QtMultimedia(QMediaPlayer + QAudioOutput) — 재생/멈춤, 파형 클릭한 곳으로 이동, 재생 위치 세로선, '0:12 / 1:35', 소리 크기
- 위젯이 지워지면 ffmpeg 를 끝내고(잔류 프로세스 없음) 재생을 멈춤
로그: bin\\log\\4Dir.log [QE.audioprev]
"""
import os
import re
import sys
import time
import array
import logging
import threading
import subprocess

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

AUDIOPREV_VER = "1.0.0"
log = logging.getLogger("QE.audioprev")
EXTS = {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac", ".wma", ".opus"}
RATE = 8000
MAX_SEC = 600
BUCKETS = 2400      # 파형 칸 수 (최소·최대 한 쌍씩)
_NOWIN = 0x08000000 if sys.platform == "win32" else 0



def _narrow(lab):
    """줄 바꿈 글자표: 폭은 창에 맞춰 줄고 늘되, 높이는 글 길이에 맞게 (heightForWidth 유지)"""
    sp = lab.sizePolicy()
    sp.setHorizontalPolicy(QtWidgets.QSizePolicy.Ignored)
    lab.setSizePolicy(sp)
    lab.setMinimumWidth(1)

def can_handle(path):
    return os.path.splitext(path or "")[1].lower() in EXTS


def ffmpeg_path():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(root, "runtime", "ffmpeg", "ffmpeg.exe")
    return p if os.path.isfile(p) else None


def fmt_time(ms):
    s = max(0, int(ms // 1000))
    h, m, s = s // 3600, (s // 60) % 60, s % 60
    return "%d:%02d:%02d" % (h, m, s) if h else "%d:%02d" % (m, s)


_BITS = {"u8": 8, "s16": 16, "s16p": 16, "s32": 32, "s32p": 32, "flt": 32, "fltp": 32, "dbl": 64, "dblp": 64, "s64": 64}


def probe(path, ff=None):
    """ffmpeg -i 출력 → dict(duration 초, rate, channels, bits, codec, text)"""
    ff = ff or ffmpeg_path()
    if not ff:
        raise RuntimeError(T("ffmpeg 가 없음"))
    r = subprocess.run([ff, "-hide_banner", "-nostdin", "-i", path], capture_output=True, creationflags=_NOWIN, timeout=30)
    txt = r.stderr.decode("utf-8", "replace")
    out = {"duration": 0.0, "rate": 0, "channels": 0, "bits": 0, "codec": "", "float": False, "text": txt}
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", txt)
    if m:
        out["duration"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    m = re.search(r"Stream #\S+.*?Audio:\s*([^,\n]+),\s*(\d+) Hz,\s*([^,\n]+),\s*([^,\n]+)", txt)
    if m:
        out["codec"] = m.group(1).strip()
        out["rate"] = int(m.group(2))
        ch = m.group(3).strip()
        out["channels"] = {"mono": 1, "stereo": 2, "2.1": 3, "quad": 4, "5.0": 5, "5.1": 6, "6.1": 7, "7.1": 8}.get(
            ch.split("(")[0], 0)
        mm = re.match(r"(\d+) channels", ch)
        if mm:
            out["channels"] = int(mm.group(1))
        sf = m.group(4).strip()
        mb = re.search(r"\((\d+) bit\)", sf)
        out["bits"] = int(mb.group(1)) if mb else _BITS.get(sf.split()[0], 0)
        out["float"] = sf.startswith("flt") or sf.startswith("dbl")
    log.info("정보 %s 길이 %.2f초 %dHz %dch %dbit %s", path, out["duration"], out["rate"], out["channels"], out["bits"], out["codec"])
    return out


class _Bridge(QtCore.QObject):
    info = QtCore.Signal(object)
    peaks = QtCore.Signal(object, bool)   # (최소·최대 목록, 끝났나)


class Decoder:
    """뒤 스레드: ffmpeg 로 풀어서 칸마다 (최소, 최대) 를 모음"""

    def __init__(self, path, bridge):
        self.path = path
        self.br = bridge
        self.proc = None
        self.stop = threading.Event()
        self.samples = 0
        self.th = threading.Thread(target=self.run, daemon=True, name="audioprev")
        self.th.start()

    def emit(self, sig, *a):
        if self.stop.is_set():
            return False
        try:
            getattr(self.br, sig).emit(*a)
            return True
        except RuntimeError:
            self.stop.set()
            return False

    def run(self):
        ff = ffmpeg_path()
        try:
            info = probe(self.path, ff)
        except Exception as ex:
            log.exception("정보 읽기 실패")
            self.emit("info", ex)
            return
        if not self.emit("info", info):
            return
        dur = min(info["duration"] or MAX_SEC, MAX_SEC)
        total = max(1, int(dur * RATE))
        per = max(1, total // BUCKETS)       # 한 칸에 들어갈 표본 수
        peaks = []
        t0 = time.time()
        try:
            self.proc = subprocess.Popen([ff, "-hide_banner", "-nostdin", "-loglevel", "error", "-i", self.path, "-vn",
                                          "-t", str(MAX_SEC), "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"],
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                         creationflags=_NOWIN)
            log.info("풀기 시작 pid=%d 한 칸=%d표본", self.proc.pid, per)
            rest = b""
            last = time.time()
            chunk = per * 2 * 64
            while not self.stop.is_set():
                b = self.proc.stdout.read(chunk)
                if not b:
                    break
                b = rest + b
                n = (len(b) // (per * 2)) * per * 2
                rest = b[n:]
                a = array.array("h")
                a.frombytes(b[:n])
                self.samples += len(a)
                for i in range(0, len(a), per):
                    s = a[i:i + per]
                    peaks.append((min(s), max(s)))
                if time.time() - last > 0.25:
                    last = time.time()
                    self.emit("peaks", list(peaks), False)
            if rest and not self.stop.is_set():
                a = array.array("h")
                a.frombytes(rest[:len(rest) // 2 * 2])
                if a:
                    self.samples += len(a)
                    peaks.append((min(a), max(a)))
        except Exception:
            log.exception("파형 풀기 실패")
        finally:
            if self.proc is not None and not self.stop.is_set():
                try:
                    self.proc.wait(2)   # 다 풀었으면 스스로 끝남
                except Exception:
                    pass
            self.kill()
        if not self.stop.is_set():
            log.info("파형 끝 표본 %d개 칸 %d개 %.0fms", self.samples, len(peaks), (time.time() - t0) * 1000)
            self.emit("peaks", peaks, True)

    def kill(self):
        p = self.proc
        if p is not None and p.poll() is None:
            try:
                p.kill()
                p.wait(3)
                log.info("ffmpeg 끝냄 pid=%d", p.pid)
            except Exception:
                log.exception("ffmpeg 끝내기 실패")
        if p is not None and p.stdout:
            try:
                p.stdout.close()
            except Exception:
                pass

    def cancel(self):
        self.stop.set()
        self.kill()


class Wave(QtWidgets.QWidget):
    seek = QtCore.Signal(float)   # 0~1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.peaks = []
        self.cover = 1.0      # 파형이 전체 길이 중 어디까지인가 (10분 넘는 파일 — 뒤쪽은 비워 둠)
        self.pos = 0.0        # 재생 위치 0~1 (전체 길이 기준)
        self.done = False
        self.setMinimumHeight(70)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Expanding)
        self.setCursor(Qt.PointingHandCursor)

    def sizeHint(self):
        return QtCore.QSize(300, 120)

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        pal = self.palette()
        dark = pal.color(QtGui.QPalette.Base).lightness() < 128
        r = self.rect()
        p.fillRect(r, pal.color(QtGui.QPalette.Base))
        mid = r.height() / 2.0
        p.setPen(QtGui.QPen(pal.color(QtGui.QPalette.Mid), 1))
        p.drawLine(0, int(mid), r.width(), int(mid))
        w = r.width()
        n = len(self.peaks)
        if n:
            col = QtGui.QColor("#4f9cf0" if dark else "#2a6fd0")
            played = QtGui.QColor("#9cc8ff" if dark else "#0b3f8a")
            peak = max(0.02, max(max(-s[0], s[1]) for s in self.peaks) / 32768.0)   # 가장 큰 소리를 높이에 맞춤
            span = (BUCKETS if not self.done else n) / max(1e-9, self.cover)   # 가로 = 전체 길이
            for x in range(w):
                i0 = int(x * span / w)
                i1 = max(i0 + 1, int((x + 1) * span / w))
                if i0 >= n:
                    break
                seg = self.peaks[i0:min(i1, n)]
                lo = min(s[0] for s in seg) / 32768.0
                hi = max(s[1] for s in seg) / 32768.0
                p.setPen(played if x / max(1, w) < self.pos else col)
                p.drawLine(x, int(mid - hi / peak * (mid - 2)), x, int(mid - lo / peak * (mid - 2)))
        else:
            p.setPen(pal.color(QtGui.QPalette.PlaceholderText))
            p.drawText(r, Qt.AlignCenter, T("파형 만드는 중…"))
        x = int(self.pos * w)
        p.setPen(QtGui.QPen(QtGui.QColor("#e04040"), 1))
        p.drawLine(x, 0, x, r.height())
        p.end()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.width() > 0:
            f = min(1.0, max(0.0, ev.position().x() / self.width()))
            self.seek.emit(f)


class AudioView(QtWidgets.QWidget):
    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = path
        self.info = None
        self.dur_ms = 0
        self.player = None
        self.audio = None
        self.setMinimumWidth(150)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Expanding)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.wave = Wave()
        self.wave.seek.connect(self.seek_frac)
        lay.addWidget(self.wave, 1)
        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(4)
        self.play_btn = QtWidgets.QToolButton()
        self.play_btn.setAutoRaise(True)
        self.play_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))
        self.play_btn.setToolTip(T("재생/멈춤 (스페이스)"))
        self.play_btn.clicked.connect(self.toggle)
        bar.addWidget(self.play_btn)
        self.time = QtWidgets.QLabel("0:00 / 0:00")
        self.time.setMinimumWidth(10)
        bar.addWidget(self.time, 1)
        self.vol_ic = QtWidgets.QLabel()
        self.vol_ic.setPixmap(self.style().standardIcon(QtWidgets.QStyle.SP_MediaVolume).pixmap(14, 14))
        bar.addWidget(self.vol_ic)
        self.vol = QtWidgets.QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(80)
        self.vol.setMaximumWidth(90)
        self.vol.setMinimumWidth(40)
        self.vol.setToolTip(T("소리 크기"))
        self.vol.valueChanged.connect(self.set_volume)
        bar.addWidget(self.vol)
        lay.addLayout(bar)
        self.meta = QtWidgets.QLabel(T("읽는 중…"))
        self.meta.setWordWrap(True)
        self.meta.setTextInteractionFlags(Qt.TextSelectableByMouse)
        _narrow(self.meta)
        lay.addWidget(self.meta)
        sc = QtGui.QShortcut(QtGui.QKeySequence(Qt.Key_Space), self)
        sc.setContext(Qt.WidgetWithChildrenShortcut)
        sc.activated.connect(self.toggle)
        self._make_player()
        self.br = _Bridge(self)
        self.br.info.connect(self._on_info)
        self.br.peaks.connect(self._on_peaks)
        log.info("열기 %s", path)
        if ffmpeg_path():
            self.dec = Decoder(path, self.br)
            self.destroyed.connect(self.dec.cancel)
        else:
            self.dec = None
            self.meta.setText(T("ffmpeg 가 없어 파형을 그릴 수 없음"))

    def _make_player(self):
        try:
            os.environ.setdefault("QT_FFMPEG_DECODING_HW_DEVICE_TYPES", "")
            from PySide6 import QtMultimedia
        except Exception as ex:
            log.info("재생 부품 없음 (%s) → 파형만", ex)
            self.play_btn.setEnabled(False)
            return
        self.player = QtMultimedia.QMediaPlayer(self)
        self.audio = QtMultimedia.QAudioOutput(self)
        self.audio.setVolume(self.vol.value() / 100.0)
        self.player.setAudioOutput(self.audio)
        self.player.positionChanged.connect(self._on_pos)
        self.player.durationChanged.connect(self._on_dur)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.errorOccurred.connect(lambda e, s: log.info("재생 오류 %s %s", e, s))
        self.player.setSource(QtCore.QUrl.fromLocalFile(self.path))

    # ---- 결과
    def _on_info(self, r):
        if isinstance(r, Exception):
            self.meta.setText(T("소리 정보를 읽을 수 없음: {0}").format(r))
            return
        self.info = r
        if not self.dur_ms:
            self.dur_ms = int(r["duration"] * 1000)
        if r["duration"] > MAX_SEC:
            self.wave.cover = MAX_SEC / r["duration"]
        ch = {1: T("모노"), 2: T("스테레오")}.get(r["channels"], T("{0}채널").format(r["channels"]) if r["channels"] else "?")
        bits = (T("{0}비트").format(r["bits"]) + (" " + T("(실수)") if r["float"] else "")) if r["bits"] else "?"
        lines = [T("길이: {0}").format(fmt_time(r["duration"] * 1000)),
                 T("채널: {0}").format(ch),
                 T("표본 빈도: {0:,} Hz").format(r["rate"]) if r["rate"] else T("표본 빈도: ?"),
                 T("비트 깊이: {0}").format(bits)]
        if r["codec"]:
            lines.append(T("압축 방식: {0}").format(r["codec"]))
        if r["duration"] > MAX_SEC:
            lines.append(T("파형은 앞 10분만"))
        self.meta.setText("\n".join(lines))
        self._upd_time()

    def _on_peaks(self, peaks, done):
        self.wave.peaks = peaks
        self.wave.done = done
        self.wave.update()

    # ---- 재생
    def toggle(self):
        if self.player is None:
            return
        from PySide6 import QtMultimedia
        if self.player.playbackState() == QtMultimedia.QMediaPlayer.PlayingState:
            self.player.pause()
            log.info("멈춤 %d ms", self.player.position())
        else:
            self.player.play()
            log.info("재생 %d ms", self.player.position())

    def seek_frac(self, f):
        ms = int(f * self.dur_ms)
        log.info("이동 %.3f → %d ms", f, ms)
        if self.player is not None:
            self.player.setPosition(ms)
        self.wave.pos = f
        self.wave.update()
        self._upd_time(ms)

    def set_volume(self, v):
        if self.audio is not None:
            self.audio.setVolume(v / 100.0)

    def _on_pos(self, ms):
        if self.dur_ms:
            self.wave.pos = ms / self.dur_ms
            self.wave.update()
        self._upd_time(ms)

    def _on_dur(self, ms):
        if ms > 0:
            self.dur_ms = ms

    def _on_state(self, st):
        from PySide6 import QtMultimedia
        playing = st == QtMultimedia.QMediaPlayer.PlayingState
        self.play_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaPause if playing else QtWidgets.QStyle.SP_MediaPlay))

    def _upd_time(self, ms=None):
        if ms is None:
            ms = self.player.position() if self.player is not None else 0
        self.time.setText("%s / %s" % (fmt_time(ms), fmt_time(self.dur_ms)))

    def hideEvent(self, ev):
        super().hideEvent(ev)
        if self.player is not None:
            self.player.pause()

    def close_all(self):
        """명시적으로 정리 (지워질 때도 자동으로 함)"""
        if self.dec is not None:
            self.dec.cancel()
        if self.player is not None:
            self.player.stop()
            self.player.setSource(QtCore.QUrl())


def make_widget(path, parent=None):
    if not can_handle(path) or not os.path.isfile(path):
        return None
    try:
        return AudioView(path, parent)
    except Exception:
        log.exception("위젯 만들기 실패 %s", path)
        return None
