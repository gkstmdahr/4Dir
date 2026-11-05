# -*- coding: utf-8 -*-
"""미리보기 창 동영상 재생·장면 단위 이동 (VIDEO_VER 1.0.1, 빌드 21 — 사용자 11/5 'GIF 처럼 재생하고 프레임 단위로')

- Qt 동영상(QtMultimedia) + FFmpeg 해독기 (_build\\get_video.py 로 runtime 에 넣음). 없으면 available()=False → 첫 장면 그림만
- VideoMovie = QMovie 와 같은 모양(frameChanged·jumpToFrame·setPaused·currentImage…) → 미리보기 창의 GIF 조작줄을 그대로 씀
- 소리 있음(1.0.6, 단추로 끔·설정 video_sound 기억), 끝나면 처음부터 다시(GIF 처럼). 장면 번호 = 시작 시각 ÷ 장면 길이(fps)
- 부품은 동영상을 처음 고를 때만 불러옴 (시작 속도·평소 메모리 그대로)
- 장면 띠: 따로 재생기 하나로 고르게 뽑은 장면 최대 60장 (끝나면 재생기 버림)
로그: bin\\log\\4Dir.log [QE.video]
"""
import os
import logging

from PySide6 import QtCore, QtGui

VIDEO_VER = "1.0.7"   # 1.0.7: 장면 띠를 끝까지 고르게 / 1.0.6: 소리 (사용자 11/6 '영상에서 소리 안 남') — 끄고 켜기 set_muted / 1.0.5: 글자 fps = 파일 정보 값(실측과 1% 안이면 — 윈도우 속성과 같게, 11/6 사용자) / 1.0.4: 첫 장면 시각(0 이 아닐 수 있음, 실측 33ms) 기준으로 번호·이동 / 1.0.3: 장면 띠 만드는 중에 닫아도 오류 없음(close) / 1.0.2: 장면 길이는 실제 장면에서 잼(파일 정보 60.08fps ≠ 실제 60 → 앞으로 안 감·뒤로 2장씩, 11/6 사용자), 장면 가운데로 이동 / 1.0.1: 하드웨어 해독 끔
log = logging.getLogger("QE.video")
EXTS = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".wmv", ".mpg", ".mpeg", ".ts", ".mts", ".m2ts", ".flv", ".3gp"}
_MM = [None]   # QtMultimedia 모듈 (불러오기 실패 = False)


def available():
    if _MM[0] is None:
        try:
            # 1.0.1: 하드웨어 해독 끔 — 실측(720p): 재생 CPU 0.7→1.1%(16코어 기준)로 거의 같고, 보고 난 뒤 남는 메모리 180→120MB
            os.environ.setdefault("QT_FFMPEG_DECODING_HW_DEVICE_TYPES", "")
            from PySide6 import QtMultimedia
            _MM[0] = QtMultimedia
            log.info("동영상 부품 불러옴 (QtMultimedia)")
        except Exception as ex:
            _MM[0] = False
            log.info("동영상 부품 없음 → 첫 장면 그림만 (%s)", ex)
    return bool(_MM[0])


def is_video(name):
    return os.path.splitext(name)[1].lower() in EXTS


class VideoMovie(QtCore.QObject):
    """QMovie 흉내 — 미리보기 창 GIF 조작줄이 그대로 씀"""
    frameChanged = QtCore.Signal(int)
    ready = QtCore.Signal()     # 길이·fps 를 앎 (장면 수가 정해짐)
    failed = QtCore.Signal(str)

    def __init__(self, path, parent=None, muted=False):
        super().__init__(parent)
        mm = _MM[0]
        self.path = path
        self.fps = 30.0
        self.fms = 1000.0 / 30
        self.frames = 0
        self._n = 0
        self._t = 0            # 지금 장면의 실제 시작 시각(ms)
        self._t0 = None        # 첫 장면의 시작 시각(ms) — 0 이 아닌 영상이 있음 (장면 번호 기준점)
        self._dur_us = 0       # 실제 장면 길이(µs) — 디코딩한 장면의 끝-시작 중 가장 짧은 값
        self._img = QtGui.QImage()
        self._ok = False
        self.pl = mm.QMediaPlayer(self)
        self.sink = mm.QVideoSink(self)
        self.pl.setVideoOutput(self.sink)
        self.audio = mm.QAudioOutput(self)   # 1.0.6 소리 (장면 띠 재생기는 소리 없음)
        self.audio.setMuted(bool(muted))
        self.pl.setAudioOutput(self.audio)
        self.pl.setLoops(mm.QMediaPlayer.Infinite)
        self.sink.videoFrameChanged.connect(self._frame)
        self.pl.mediaStatusChanged.connect(self._status)
        self.pl.errorOccurred.connect(lambda e, s: (log.warning("동영상 오류 %s: %s", os.path.basename(path), s), self.failed.emit(s)))
        self.pl.setSource(QtCore.QUrl.fromLocalFile(path))

    def _status(self, st):
        mm = _MM[0]
        if st in (mm.QMediaPlayer.LoadedMedia, mm.QMediaPlayer.BufferedMedia) and not self._ok:
            self._ok = True
            fps = self.pl.metaData().value(mm.QMediaMetaData.VideoFrameRate)
            try:
                fps = float(fps)
            except (TypeError, ValueError):
                fps = 0.0
            self.fps = fps if 1 <= fps <= 240 else 30.0
            self.meta_fps = fps if 1 <= fps <= 240 else 0.0
            self.fms = 1000.0 / self.fps
            self.frames = max(1, int(round(self.pl.duration() / self.fms)))
            log.info("동영상 열림 %s : %.1f초 · %.2ffps · 장면 %d", os.path.basename(self.path), self.pl.duration() / 1000, self.fps, self.frames)
            self.ready.emit()
        elif st == mm.QMediaPlayer.InvalidMedia:
            self.failed.emit("invalid")

    def _frame(self, fr):
        if not fr.isValid():
            return
        im = fr.toImage()
        if im.isNull():
            return
        st, en = fr.startTime(), fr.endTime()
        d = en - st
        if 1000 <= d <= 1000000 and (not self._dur_us or d < self._dur_us * 0.9 or (d < self._dur_us and self._dur_us - d < 2000)):
            if not self._dur_us or abs(d - self._dur_us) > 50:   # 실제 장면 길이 (파일 정보 fps 는 60.08 처럼 틀릴 수 있음)
                self._dur_us = d
                self.fms = d / 1000.0
                self.fps = 1000.0 / self.fms
                self.frames = max(1, int(round(self.pl.duration() / self.fms)))
                log.info("동영상 실제 장면 길이 %.3fms (%.2ffps) → 장면 %d", self.fms, self.fps, self.frames)
        self._img = im
        self._t = st / 1000.0
        if self._t0 is None or self._t < self._t0:
            self._t0 = self._t   # 장면 수는 그대로 길이÷장면 길이 (실측: 첫 장면 32ms 영상도 길이에 그만큼이 안 들어 있음 → 181장면 맞음)
        self._n = min(max(0, int((self._t - self._t0) / self.fms + 0.5)), max(0, self.frames - 1))   # (시작 시각 - 첫 장면) → 번호 (반올림)
        self.frameChanged.emit(self._n)

    # ---- QMovie 와 같은 이름
    def fileName(self):
        return self.path

    def isValid(self):
        return self.pl.error() == _MM[0].QMediaPlayer.NoError

    def frameCount(self):
        return self.frames

    def currentFrameNumber(self):
        return self._n

    def currentImage(self):
        return self._img

    def set_muted(self, on):
        self.audio.setMuted(bool(on))

    def muted(self):
        return self.audio.isMuted()

    def has_audio(self):
        try:
            return bool(self.pl.hasAudio())
        except Exception:
            return True

    def duration(self):
        """전체 길이(ms) — 첫 장면이 0 이 아닌 영상은 그만큼 뺌 (글자 '지금 / 전체' 가 같은 기준)"""
        return max(0, self.pl.duration() - (self._t0 or 0))

    def display_fps(self):
        """글자에 보일 fps: 파일 정보 값이 실측 장면 길이와 1% 안이면 그 값(평균 — 윈도우 속성과 같음), 아니면 실측"""
        mf = getattr(self, "meta_fps", 0.0)
        v = mf if mf and abs(mf - self.fps) / self.fps < 0.01 else self.fps
        return f"{v:.3f}".rstrip("0").rstrip(".")

    def currentTime(self):
        """지금 장면의 실제 시작 시각(ms)"""
        return self._t

    def currentPixmap(self):
        return QtGui.QPixmap.fromImage(self._img)

    def nextFrameDelay(self):
        return int(round(self.fms))

    def state(self):
        return QtGui.QMovie.Running if self.pl.playbackState() == _MM[0].QMediaPlayer.PlayingState else QtGui.QMovie.Paused

    def start(self):
        self.pl.play()

    def stop(self):
        self.pl.stop()
        self.pl.setSource(QtCore.QUrl())   # 파일 놓음

    def setPaused(self, paused):
        if paused:
            self.pl.pause()
        else:
            self.pl.play()

    def jumpToFrame(self, n):
        """n 번째 장면으로 (멈춘 채). 장면 가운데 시각으로 감 — 경계값이면 앞 장면이 오고(실측), fps 가 조금 틀려도 안전"""
        n = min(max(0, int(n)), max(0, self.frames - 1))
        if self.pl.playbackState() == _MM[0].QMediaPlayer.PlayingState:
            self.pl.pause()
        self.pl.setPosition(int((self._t0 or 0) + (n + 0.5) * self.fms))
        self._n = n
        return True

    def jumpToNextFrame(self):
        return self.jumpToFrame(self._n + 1)


class VideoStrip(QtCore.QObject):
    """장면 띠: 따로 재생기로 고르게 뽑은 장면 → done([(장면 번호, 작은 그림)])"""
    done = QtCore.Signal(list)

    def __init__(self, path, frames, fms, count=60, parent=None):
        super().__init__(parent)
        mm = _MM[0]
        # 1.0.7: 처음부터 끝까지 고르게 (전엔 92장면 영상에서 앞 60장만 — 92번째에서 띠는 60, 11/6 캡처). 120장 이하면 전부
        count = min(frames, max(count, 120 if frames <= 120 else count))
        last = max(0, frames - 2)   # 맨 끝 장면으로 가면 그림이 안 올 때가 있음(실측) → 끝에서 한 장 앞까지
        self.want = sorted({int(round(i * last / max(1, count - 1))) for i in range(count)}) if frames > 1 else [0]
        self.fms = fms
        self.out = []
        self.i = -1
        self.dead = False
        self.pl = mm.QMediaPlayer(self)
        self.sink = mm.QVideoSink(self)
        self.pl.setVideoOutput(self.sink)
        self.sink.videoFrameChanged.connect(self._frame)
        self.pl.mediaStatusChanged.connect(self._status)
        self.timer = QtCore.QTimer(self)   # 장면이 안 오면 다음으로 (한 장에 1초까지)
        self.timer.setSingleShot(True)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._next)
        self.pl.setSource(QtCore.QUrl.fromLocalFile(path))

    def close(self):
        """그만 (다른 파일을 고르거나 미리보기를 닫음) — 예약된 다음 단계도 안 함"""
        self.dead = True
        self.timer.stop()
        self.pl.stop()
        self.pl.setSource(QtCore.QUrl())

    def _status(self, st):
        if self.dead:
            return
        if st == _MM[0].QMediaPlayer.LoadedMedia and self.i < 0:
            self.pl.pause()
            self._next()

    def _next(self):
        if self.dead:
            return
        self.i += 1
        if self.i >= len(self.want):
            self.pl.stop()
            self.pl.setSource(QtCore.QUrl())
            self.done.emit(self.out)
            return
        self.timer.start()
        self.pl.setPosition(int((self.want[self.i] + 0.5) * self.fms))

    def _frame(self, fr):
        if self.dead or self.i < 0 or self.i >= len(self.want) or not fr.isValid():
            return
        im = fr.toImage()
        if im.isNull():
            return
        self.out.append((self.want[self.i], im.scaled(48, 48, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)))
        self.timer.stop()
        QtCore.QTimer.singleShot(0, self, self._next)   # self 가 지워지면 같이 취소
