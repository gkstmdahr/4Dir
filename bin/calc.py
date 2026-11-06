# -*- coding: utf-8 -*-
"""계산기 (CALC_VER 1.0.0, 0.9.111 빌드 1 — 사용자 11/6 '계산기 추가, 회계·공학에서 쓰는 것도')

- 따로 창 (도구 ▸ 계산기, Alt+C). 위치·크기·항상 위 기억(설정 calc_geo·calc_top), 계산 기록 50개(calc_hist)
- 일반: 식을 한 줄로 ('1920*0.75+30', '1,200,000*1.1', '50%' = 0.5, '^' = 거듭제곱) → 치는 동안 결과, Enter = 기록에 넣기
  기록 두 번 누르기 = 그 식 다시, 결과 복사(Ctrl+Shift+C). ans = 직전 결과
- 회계: 부가세 포함/별도 · 할인·마진 · 이자(단리·월 복리) · 대출 월 상환액(원리금균등·원금균등) · 원 단위 반올림·올림·내림
- 공학: sin cos tan asin acos atan (도/라디안) · log(상용) ln exp sqrt cbrt abs fact(계승) pow · π(pi) e · 2·8·16진 (0b 0o 0x 입력, 결과 변환 표시)
  비트 연산 band bor bxor shl shr · 함수 단추
- 단위: 길이·무게·넓이(평 포함)·부피·온도·용량(1024)·시간
- 계산은 파이썬 eval 을 쓰지 않음 — 식을 나눠서 허용한 연산·함수만 직접 계산 (파일·명령 실행 불가)
로그: bin\\log\\4Dir.log [QE.calc]
"""
import ast
import math
import re
import logging
import operator

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

CALC_VER = "1.3.0"   # 1.3.0: 윈도우 계산기 기능 (그래프·프로그래머·날짜 계산 · 변환기 13개, 통화 환율) / 1.2.0: 메모리 MC MR M+ M− MS M▾ (설정 calc_mem 20개) / 1.1.1: 예전 큰 창 크기 버림 / 1.1.0: 윈도우 계산기처럼 (☰ 표준·공학용·회계·단위 변환, 기록 단추, 촘촘한 단추, 밝게·어둡게)
log = logging.getLogger("QE.calc")


# ================================================================ 식 계산 (안전)
class CalcError(ValueError):
    pass


def _fact(n):
    if n != int(n) or n < 0 or n > 170:
        raise CalcError(T("계승은 0~170 정수만"))
    return math.factorial(int(n))


def _int(x):
    if x != int(x):
        raise CalcError(T("비트 연산은 정수만"))
    return int(x)


FUNCS = {
    "sin": None, "cos": None, "tan": None, "asin": None, "acos": None, "atan": None,   # 도·라디안에 따라 (evaluate 안에서)
    "sqrt": math.sqrt, "cbrt": lambda x: math.copysign(abs(x) ** (1 / 3), x), "abs": abs, "exp": math.exp,
    "ln": math.log, "log": math.log10, "log2": math.log2, "pow": pow, "fact": _fact, "round": round,
    "floor": math.floor, "ceil": math.ceil, "min": min, "max": max, "mod": lambda a, b: a % b,
    "band": lambda a, b: _int(a) & _int(b), "bor": lambda a, b: _int(a) | _int(b), "bxor": lambda a, b: _int(a) ^ _int(b),
    "shl": lambda a, b: _int(a) << _int(b), "shr": lambda a, b: _int(a) >> _int(b),
}
CONSTS = {"pi": math.pi, "π": math.pi, "e": math.e}
BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
          ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}


def normalize(expr):
    """사람이 치는 식 → 계산용 식: × ÷ − ^ 천 단위 쉼표, '50%' → (50/100)"""
    s = expr.strip().replace("×", "*").replace("÷", "/").replace("−", "-").replace("^", "**").replace("π", "pi")
    # 1,200,000 → 1200000. 괄호·쉼표 바로 뒤 숫자는 함수 인자로 보고 그대로 (shl(1,100) 을 1100 으로 읽던 것)
    s = re.sub(r"(?<![\w.(,])(\d{1,3}(?:,\d{3})+)(?![\d,])", lambda m: m.group(1).replace(",", ""), s)
    s = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", s)
    s = re.sub(r"\s+mod\s+", "%", s)   # 1.1.0 공학 'mod' 단추 = 나머지 (퍼센트 바꾼 뒤라 섞이지 않음)
    return s


def evaluate(expr, deg=True, ans=0.0, x=None, ints=False, tree=None):
    """x = 그래프 변수 · ints = 정수 비트 연산 허용(프로그래머) · tree = 미리 나눈 식 (그래프가 점마다 다시 나누지 않게)"""
    s = "" if tree is not None else normalize(expr)
    if tree is not None:
        pass
    else:
        if not s:
            raise CalcError("")
        if len(s) > 500:
            raise CalcError(T("식이 너무 깁니다"))
        try:
            tree = ast.parse(s, mode="eval")
        except SyntaxError:
            raise CalcError(T("식을 읽을 수 없습니다"))
    return _run(tree, deg, ans, x, ints)


def parse(expr):
    """그래프용: 한 번만 나눔 (실패하면 CalcError)"""
    s = normalize(expr)
    if not s:
        raise CalcError("")
    try:
        return ast.parse(s, mode="eval")
    except SyntaxError:
        raise CalcError(T("식을 읽을 수 없습니다"))


BITOPS = {ast.BitAnd: operator.and_, ast.BitOr: operator.or_, ast.BitXor: operator.xor, ast.LShift: operator.lshift, ast.RShift: operator.rshift}


def _run(tree, deg, ans, x, ints):
    s = "-"
    conv = (lambda x: math.radians(x)) if deg else (lambda x: x)
    back = (lambda x: math.degrees(x)) if deg else (lambda x: x)
    trig = {"sin": lambda x: math.sin(conv(x)), "cos": lambda x: math.cos(conv(x)), "tan": lambda x: math.tan(conv(x)),
            "asin": lambda x: back(math.asin(x)), "acos": lambda x: back(math.acos(x)), "atan": lambda x: back(math.atan(x))}

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return n.value
        if ints and isinstance(n, ast.BinOp) and type(n.op) in BITOPS:
            a, b = ev(n.left), ev(n.right)
            if a != int(a) or b != int(b):
                raise CalcError(T("비트 연산은 정수만"))
            if isinstance(n.op, ast.LShift) and b > 256:
                raise CalcError(T("너무 큰 거듭제곱"))
            return BITOPS[type(n.op)](int(a), int(b))
        if ints and isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Invert):
            return ~int(ev(n.operand))
        if isinstance(n, ast.BinOp) and type(n.op) in BINOPS:
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Pow) and abs(b) > 10000:
                raise CalcError(T("너무 큰 거듭제곱"))
            return BINOPS[type(n.op)](a, b)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            v = ev(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.Name):
            if n.id == "ans":
                return ans
            if n.id == "x" and x is not None:
                return x
            if n.id in CONSTS:
                return CONSTS[n.id]
            raise CalcError(T("모르는 이름: {0}").format(n.id))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCS and not n.keywords:
            fn = trig.get(n.func.id) or FUNCS[n.func.id]
            return fn(*[ev(a) for a in n.args])
        raise CalcError(T("쓸 수 없는 식입니다"))
    try:
        v = ev(tree)
        if ints and isinstance(v, float):
            v = int(v)
    except CalcError:
        raise
    except ZeroDivisionError:
        raise CalcError(T("0 으로 나눌 수 없습니다"))
    except (ValueError, OverflowError, TypeError) as ex:
        raise CalcError(str(ex))
    if isinstance(v, complex):
        raise CalcError(T("복소수는 안 됩니다"))
    if isinstance(v, float) and abs(v - round(v)) < 1e-9 * max(1.0, abs(v)) and abs(v) < 1e15:
        v = float(round(v))
    return v


def fmt(v, comma=True):
    """결과 보기 — 정수면 쉼표, 실수는 유효 12자리 (끝의 0 뺌)"""
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return str(v)
    if float(v).is_integer() and abs(v) < 1e15:
        return f"{int(v):,}" if comma else str(int(v))
    s = f"{v:.12g}"
    if "e" in s or not comma:
        return s
    a, _, b = s.partition(".")
    neg = a.startswith("-")
    return ("-" if neg else "") + f"{int(a.lstrip('-')):,}" + ("." + b if b else "")


def bases(v):
    if not isinstance(v, (int, float)) or v != int(v) or abs(v) >= 2 ** 63:
        return ""
    n = int(v)
    sign = "-" if n < 0 else ""
    n = abs(n)
    return f"HEX {sign}{n:X}   OCT {sign}{n:o}   BIN {sign}{n:b}"


# ================================================================ 회계 계산
def vat(amount, rate=10.0, included=True):
    """included = 금액이 부가세 포함가 → (공급가, 세액, 합계)"""
    r = rate / 100
    if included:
        supply = amount / (1 + r)
        return supply, amount - supply, amount
    return amount, amount * r, amount * (1 + r)


def margin(cost, price):
    """(마진액, 마진율=이익/판매가 %, 이익률=이익/원가 %)"""
    m = price - cost
    return m, (m / price * 100 if price else 0.0), (m / cost * 100 if cost else 0.0)


def interest(principal, rate, months, compound=False):
    """연이율 % · 개월 → (이자, 만기 금액). compound = 월 복리"""
    r = rate / 100
    if compound:
        total = principal * (1 + r / 12) ** months
    else:
        total = principal * (1 + r * months / 12)
    return total - principal, total


def loan(principal, rate, months, kind="annuity"):
    """kind: annuity(원리금균등) → (월 상환액, 총이자) / equal(원금균등) → (첫 달, 마지막 달, 총이자)"""
    r = rate / 100 / 12
    if kind == "annuity":
        pay = principal / months if r == 0 else principal * r * (1 + r) ** months / ((1 + r) ** months - 1)
        return pay, pay * months - principal
    base = principal / months
    first = base + principal * r
    last = base + base * r
    total_int = sum((principal - base * k) * r for k in range(months))
    return first, last, total_int


def round_won(v, unit=1, how="round"):
    q = v / unit
    q = math.floor(q + 0.5) if how == "round" else (math.ceil(q) if how == "up" else math.floor(q))
    return q * unit


# ================================================================ 단위
UNITS = {
    "len": ("길이", {"mm": 0.001, "cm": 0.01, "m": 1, "km": 1000, "in": 0.0254, "ft": 0.3048, "yd": 0.9144, "mi": 1609.344}),
    "mass": ("무게", {"mg": 1e-6, "g": 0.001, "kg": 1, "t": 1000, "oz": 0.028349523125, "lb": 0.45359237, "근(600g)": 0.6}),
    "area": ("넓이", {"m²": 1, "km²": 1e6, "ha": 1e4, "평": 400 / 121, "ft²": 0.09290304, "acre": 4046.8564224}),
    "vol": ("부피", {"mL": 0.001, "L": 1, "m³": 1000, "gal(US)": 3.785411784, "fl oz": 0.0295735295625, "컵(200mL)": 0.2}),
    "temp": ("온도", {"°C": None, "°F": None, "K": None}),
    "data": ("데이터", {"bit": 1 / 8, "B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4, "PB": 1024 ** 5,
                     "kB(1000)": 1000, "MB(1000)": 1e6, "GB(1000)": 1e9, "TB(1000)": 1e12}),
    "time": ("시간", {"µs": 1e-6, "ms": 0.001, "s": 1, "min": 60, "h": 3600, "day": 86400, "week": 604800, "year(365d)": 31536000}),
    "energy": ("에너지", {"J": 1, "kJ": 1000, "cal": 4.184, "kcal": 4184, "Wh": 3600, "kWh": 3.6e6, "eV": 1.602176634e-19, "BTU": 1055.05585262}),
    "speed": ("속도", {"m/s": 1, "km/h": 1 / 3.6, "mph": 0.44704, "knot": 0.514444444, "ft/s": 0.3048, "Mach": 340.3}),
    "power": ("전력", {"W": 1, "kW": 1000, "MW": 1e6, "hp": 745.699872, "PS(마력)": 735.49875, "BTU/h": 0.29307107}),
    "press": ("압력", {"Pa": 1, "kPa": 1000, "MPa": 1e6, "bar": 1e5, "atm": 101325, "psi": 6894.757293, "mmHg": 133.322387, "kgf/cm²": 98066.5}),
    "angle": ("각도", {"°(도)": 1, "rad": 180 / math.pi, "grad": 0.9, "′(분)": 1 / 60, "″(초)": 1 / 3600}),
}
FX_URL = "https://api.frankfurter.dev/v1/latest?base=EUR"   # 유럽중앙은행 기준 환율 (무료, 열쇠 없음) — 개인 정보 안 보냄
FX_NAMES = {"KRW": "원", "USD": "미국 달러", "EUR": "유로", "JPY": "엔", "CNY": "위안", "GBP": "파운드", "HKD": "홍콩 달러",
            "TWD": "대만 달러", "AUD": "호주 달러", "CAD": "캐나다 달러", "CHF": "스위스 프랑", "SGD": "싱가포르 달러", "THB": "바트",
            "VND": "동", "PHP": "페소", "IDR": "루피아", "INR": "루피", "MYR": "링깃", "NZD": "뉴질랜드 달러"}


def fetch_fx():
    """환율 받기 (뒤 스레드에서) → {"date", "rates"(EUR 기준, EUR=1), "t"}"""
    import json
    import time as _t
    import urllib.request
    req = urllib.request.Request(FX_URL, headers={"User-Agent": "4Dir"})
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.loads(r.read().decode("utf-8"))
    rates = dict(d.get("rates", {}))
    rates["EUR"] = 1.0
    return {"date": d.get("date", ""), "rates": rates, "t": _t.time()}


def fx_convert(rates, v, a, b):
    return v / rates[a] * rates[b]


def convert(cat, v, a, b):
    if cat == "temp":
        c = v if a == "°C" else ((v - 32) * 5 / 9 if a == "°F" else v - 273.15)
        return c if b == "°C" else (c * 9 / 5 + 32 if b == "°F" else c + 273.15)
    t = UNITS[cat][1]
    return v * t[a] / t[b]


# ================================================================ 창 (1.1.0 — 사용자 11/6 '윈도우 계산기 참고해서 이쁘고 깔끔하게, 콤팩트')
def _num(edit):
    try:
        return float(evaluate(edit.text() or "0"))
    except CalcError:
        return 0.0


CALC_MODES = [("std", "표준"), ("sci", "공학용"), ("graph", "그래프"), ("prog", "프로그래머"), ("date", "날짜 계산"), ("acct", "회계")]
CONV_MODES = [("fx", "통화 환율"), ("vol", "부피"), ("len", "길이"), ("mass", "무게"), ("temp", "온도"), ("energy", "에너지"),
              ("area", "넓이"), ("speed", "속도"), ("time", "시간"), ("power", "전력"), ("data", "데이터"), ("press", "압력"), ("angle", "각도")]
MODES = CALC_MODES + [("conv:" + k, n) for k, n in CONV_MODES]

LIGHT = {"bg": "#f3f3f3", "txt": "#1a1a1a", "sub": "#6b6b6b", "num": "#ffffff", "op": "#f9f9f9", "bd": "#e5e5e5",
         "hov": "#f0f0f0", "eq": "#0067c0", "eqh": "#1975c5", "eqt": "#ffffff", "on": "#d0e4f7", "box": "#ffffff"}
DARK = {"bg": "#202020", "txt": "#ffffff", "sub": "#a0a0a0", "num": "#3b3b3b", "op": "#323232", "bd": "#2b2b2b",
        "hov": "#454545", "eq": "#4cc2ff", "eqh": "#47b1e8", "eqt": "#000000", "on": "#24476a", "box": "#2b2b2b"}


_ARROWS = {}


def _arrow(col):
    """고르기 칸 ▾ 그림 (양식은 파일 그림만 받음 → 임시 폴더에 한 번 그려 둠)"""
    if col in _ARROWS:
        return _ARROWS[col]
    import os
    import tempfile
    im = QtGui.QImage(20, 12, QtGui.QImage.Format_ARGB32)
    im.fill(Qt.transparent)
    p = QtGui.QPainter(im)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(QtGui.QPen(QtGui.QColor(col), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawPolyline([QtCore.QPointF(3, 3), QtCore.QPointF(10, 9), QtCore.QPointF(17, 3)])
    p.end()
    path = os.path.join(tempfile.gettempdir(), f"4dir_calc_arrow_{col.strip('#')}.png")
    im.save(path)
    _ARROWS[col] = path.replace("\\", "/")
    return _ARROWS[col]


def style(c):
    return f"""
#calcWin {{ background:{c['bg']}; }}
#calcWin QLabel {{ color:{c['txt']}; background:transparent; }}
#calcWin QLabel#calcSub {{ color:{c['sub']}; }}
#calcWin QLineEdit#calcExpr {{ background:transparent; border:none; color:{c['txt']}; }}
#calcWin QPushButton {{ background:{c['op']}; color:{c['txt']}; border:1px solid {c['bd']}; border-radius:4px; padding:0; }}
#calcWin QPushButton:hover {{ background:{c['hov']}; }}
#calcWin QPushButton:checked {{ background:{c['on']}; }}
#calcWin QPushButton[k="num"] {{ background:{c['num']}; font-weight:600; }}
#calcWin QPushButton[k="num"]:hover {{ background:{c['hov']}; }}
#calcWin QPushButton[k="eq"] {{ background:{c['eq']}; color:{c['eqt']}; border:none; font-size:15pt; }}
#calcWin QPushButton[k="eq"]:hover {{ background:{c['eqh']}; }}
#calcWin QToolButton {{ background:transparent; border:none; color:{c['txt']}; padding:4px 6px; border-radius:4px; }}
#calcWin QToolButton:hover, #calcWin QToolButton:checked {{ background:{c['hov']}; }}
#calcWin QToolButton::menu-indicator {{ image:none; width:0px; }}
#calcWin QToolButton:disabled {{ color:{c['sub']}; }}
#calcWin QComboBox {{ padding:2px 6px; }}
#calcWin QComboBox::drop-down {{ border:none; width:18px; }}
#calcWin QComboBox::down-arrow {{ image:url({_arrow(c['sub'])}); width:10px; height:6px; }}
#calcWin QComboBox QAbstractItemView {{ background:{c['box']}; color:{c['txt']}; selection-background-color:{c['on']}; }}
#calcWin QListWidget, #calcWin QLineEdit, #calcWin QComboBox {{ background:{c['box']}; color:{c['txt']}; border:1px solid {c['bd']}; border-radius:3px; }}
#calcWin QListWidget#calcHist {{ border:none; background:transparent; }}
#calcWin QGroupBox {{ color:{c['txt']}; border:1px solid {c['bd']}; border-radius:4px; margin-top:8px; padding:4px 6px 4px 6px; }}
#calcWin QGroupBox::title {{ subcontrol-origin:margin; left:8px; padding:0 3px; }}
#calcWin QRadioButton, #calcWin QCheckBox {{ color:{c['txt']}; }}
"""


class CalcWindow(QtWidgets.QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent, Qt.Window)
        self.S = settings
        self.setWindowTitle(T("계산기"))
        self.setObjectName("calcWin")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.ans = 0.0
        self.last = None
        self.done = False   # '=' 바로 뒤 (숫자를 치면 새 식)
        if self.S["calc_top"]:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 6)
        lay.setSpacing(2)
        # ---- 머리: ☰ 모드 · 제목 · 📌 · 기록
        head = QtWidgets.QHBoxLayout()
        self.b_menu = QtWidgets.QToolButton()
        self.b_menu.setText("☰")
        self.b_menu.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        mm = QtWidgets.QMenu(self.b_menu)
        self.mode_acts = {}
        for sec, items in ((T("계산기"), CALC_MODES), (T("변환기"), [("conv:" + k, n) for k, n in CONV_MODES])):
            h = mm.addAction(sec)   # 묶음 제목 (윈도우 계산기처럼)
            h.setEnabled(False)
            hf = h.font()
            hf.setBold(True)
            h.setFont(hf)
            for k, name in items:
                a = mm.addAction(T(name), lambda k=k: self.set_mode(k))
                a.setCheckable(True)
                self.mode_acts[k] = a
            mm.addSeparator()
        mm.addAction(T("윈도우 계산기 열기"), self.open_windows_calc)
        self.b_menu.setMenu(mm)
        head.addWidget(self.b_menu)
        self.title = QtWidgets.QLabel()
        tf = self.title.font()
        tf.setPointSizeF(max(13.0, tf.pointSizeF() + 4))
        tf.setBold(True)
        self.title.setFont(tf)
        head.addWidget(self.title)
        head.addStretch(1)
        self.pin = QtWidgets.QToolButton()
        self.pin.setText("📌")
        self.pin.setCheckable(True)
        self.pin.setChecked(bool(self.S["calc_top"]))
        self.pin.setToolTip(T("항상 위에 표시"))
        self.pin.toggled.connect(self.set_top)
        head.addWidget(self.pin)
        self.b_hist = QtWidgets.QToolButton()
        self.b_hist.setText("🕘")
        self.b_hist.setCheckable(True)
        self.b_hist.setToolTip(T("계산 기록 (Ctrl+H)"))
        self.b_hist.toggled.connect(self.show_hist)
        head.addWidget(self.b_hist)
        lay.addLayout(head)
        # ---- 표시: 작은 줄(식·미리 결과) + 큰 줄(지금 식/결과)
        self.sub = QtWidgets.QLabel("")
        self.sub.setObjectName("calcSub")
        self.sub.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.sub.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.sub)
        self.expr = QtWidgets.QLineEdit()
        self.expr.setObjectName("calcExpr")
        self.expr.setAlignment(Qt.AlignRight)
        self.expr.setPlaceholderText("0")
        ef = self.expr.font()
        ef.setPointSizeF(24)
        ef.setBold(True)
        self.expr.setFont(ef)
        self.expr.setToolTip(T("식을 그대로 쳐도 됩니다 (예: 1920*0.75+30, 1,200,000*1.1, 2^10)"))
        lay.addWidget(self.expr)
        self.res = QtWidgets.QLabel("")   # 미리 결과 · 2·8·16진 (공학)
        self.res.setObjectName("calcSub")
        self.res.setAlignment(Qt.AlignRight)
        self.res.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.res)
        # ---- 메모리 줄 (1.2.0, 사용자 11/6 'MC·MR 이런 기능') — 윈도우 계산기와 같게
        self.memrow = QtWidgets.QWidget()
        mr = QtWidgets.QHBoxLayout(self.memrow)
        mr.setContentsMargins(0, 0, 0, 0)
        mr.setSpacing(0)
        self.mem = [float(x) for x in (self.S["calc_mem"] or [])]
        self.mem_btns = {}
        for t, tip in (("MC", T("메모리 모두 지우기")), ("MR", T("메모리 값 불러오기")), ("M+", T("메모리에 더하기")),
                       ("M−", T("메모리에서 빼기")), ("MS", T("메모리에 저장")), ("M▾", T("저장한 값 목록"))):
            b = QtWidgets.QToolButton()
            b.setText(t)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            b.clicked.connect(lambda _c=False, t=t, b=b: self.mem_key(t, b))
            mr.addWidget(b)
            self.mem_btns[t] = b
        lay.addWidget(self.memrow)
        # ---- 본문 (모드별 + 기록)
        self.stack = QtWidgets.QStackedWidget()
        self.pages = {"std": self._page_std(), "sci": self._page_sci(), "graph": self._page_graph(), "prog": self._page_prog(),
                      "date": self._page_date(), "acct": self._page_acct(), "conv": self._page_unit()}
        for w_ in self.pages.values():
            self.stack.addWidget(w_)
        self.stack.addWidget(self._page_hist())
        lay.addWidget(self.stack, 1)
        self.expr.textChanged.connect(self.live)
        self.expr.returnPressed.connect(self.commit)
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+Shift+C"), self, self.copy_result)
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+H"), self, lambda: self.b_hist.toggle())
        QtGui.QShortcut(QtGui.QKeySequence("Escape"), self, lambda: self.key("C"))
        for h in (self.S["calc_hist"] or [])[-50:]:
            self.hist.insertItem(0, h)
        self.apply_theme(bool(self.S["dark"]))
        self._mem_ui()
        mode = self.S["calc_mode"] or {0: "std", 1: "acct", 2: "sci", 3: "conv:len"}.get(int(self.S["calc_tab"] or 0), "std")
        mode = "conv:len" if mode == "unit" else mode
        self.set_mode(mode if mode in dict(MODES) else "std")
        g = self.S["calc_geo"]
        if g and len(g) == 5 and g[4] == 3 and g[2] >= 260:   # 1.2.0: 3 = 메모리 줄 생긴 뒤 크기   # 1.1.1: 1.0 때 저장한 큰 크기(440x600)는 버리고 모드 기본 크기로
            self.setGeometry(*g[:4])
        self.expr.setFocus()

    def apply_theme(self, dark):
        self.setStyleSheet(style(DARK if dark else LIGHT))

    # ---------------------------------------------------- 모드
    SIZES = {"std": (300, 460), "sci": (330, 530), "acct": (350, 540), "conv": (330, 400), "graph": (520, 560), "prog": (340, 560), "date": (340, 420)}   # 1.2.0 메모리 줄만큼   # 1.1.1 더 작게

    def set_mode(self, k):
        self.mode = k
        self.S["calc_mode"] = k
        for kk, a in self.mode_acts.items():
            a.setChecked(kk == k)
        self.title.setText(T(dict(MODES)[k]))
        self.b_hist.setChecked(False)
        page = "conv" if k.startswith("conv:") else k
        self.stack.setCurrentWidget(self.pages[page])
        if page == "conv":
            self._conv_set(k[5:])
        keypad = k in ("std", "sci")
        for w in (self.sub, self.expr, self.res, self.memrow):
            w.setVisible(keypad)
        self.b_hist.setVisible(keypad)
        w0, h0 = self.SIZES[page]
        gg = self.S["calc_geo"]
        if not (gg and len(gg) == 5) or getattr(self, "_mode_set", False):
            self.resize(w0, h0)   # 1.3.0: 모드마다 그 크기로 (그래프 뒤 좁은 모드가 넓게 남던 것)
        self._mode_set = True
        self.live()
        log.info("계산기 모드 %s", k)

    # ---------------------------------------------------- 메모리 (1.2.0)
    def _cur(self):
        """지금 값: 식이 계산되면 그 값, 아니면 직전 결과"""
        try:
            return float(evaluate(self.expr.text(), self.deg.isChecked(), self.ans)) if self.expr.text().strip() else float(self.ans)
        except CalcError:
            return float(self.ans)

    def mem_key(self, t, btn=None):
        if t == "MS":
            self.mem.append(self._cur())
        elif t == "MC":
            self.mem = []
        elif t in ("M+", "M−"):
            v = self._cur()
            if not self.mem:
                self.mem.append(0.0)
            self.mem[-1] += v if t == "M+" else -v
        elif t == "MR":
            if self.mem:
                self.expr.setText(fmt(self.mem[-1], comma=False))
                self.done = True
        elif t == "M▾":
            m = QtWidgets.QMenu(self)
            for i, v in reversed(list(enumerate(self.mem))):
                m.addAction(fmt(v), lambda v=v: (self.expr.setText(fmt(v, comma=False)), setattr(self, "done", True)))
            if self.mem:
                m.addSeparator()
                m.addAction(T("메모리 모두 지우기"), lambda: self.mem_key("MC"))
            m.exec((btn or self.mem_btns["M▾"]).mapToGlobal(QtCore.QPoint(0, (btn or self.mem_btns["M▾"]).height())))
            return
        self.S["calc_mem"] = list(self.mem)[-20:]
        self.mem = self.mem[-20:]
        self._mem_ui()
        log.info("계산기 메모리 %s → %s", t, [fmt(x) for x in self.mem[-3:]])
        self.expr.setFocus()

    def _mem_ui(self):
        has = bool(self.mem)
        for t in ("MC", "MR", "M▾"):
            self.mem_btns[t].setEnabled(has)
        self.mem_btns["MR"].setToolTip(T("메모리 값 불러오기") + (f"  ({fmt(self.mem[-1])})" if has else ""))

    def show_hist(self, on):
        self.stack.setCurrentWidget(self.hist_page if on else self.pages["conv" if self.mode.startswith("conv:") else self.mode])

    # ---------------------------------------------------- 단추
    def _btn(self, text, k="op", fn=None, tip=""):
        b = QtWidgets.QPushButton(text)
        b.setProperty("k", k)
        b.setFocusPolicy(Qt.NoFocus)
        b.setMinimumHeight(34)
        b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        if tip:
            b.setToolTip(tip)
        f = b.font()
        f.setPointSizeF(11.5 if k == "num" else 10.5)
        b.setFont(f)
        b.clicked.connect(fn or (lambda _c=False, t=text: self.key(t)))
        return b

    def _grid(self, rows, kinds=None):
        w = QtWidgets.QWidget()
        g = QtWidgets.QGridLayout(w)
        g.setContentsMargins(0, 2, 0, 0)
        g.setSpacing(2)
        for r, row in enumerate(rows):
            for c, t in enumerate(row):
                if t is None:
                    continue
                k = "num" if t in "0123456789." or t == "+/−" else ("eq" if t == "=" else "op")
                g.addWidget(self._btn(t, k), r, c)
        return w, g

    def _page_std(self):
        w, _g = self._grid([["%", "CE", "C", "⌫"], ["¹⁄ₓ", "x²", "²√x", "÷"], ["7", "8", "9", "×"],
                            ["4", "5", "6", "−"], ["1", "2", "3", "+"], ["+/−", "0", ".", "="]])
        return w

    def _page_sci(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        top = QtWidgets.QHBoxLayout()
        self.deg = QtWidgets.QPushButton("DEG")
        self.deg.setCheckable(True)
        self.deg.setChecked(self.S["calc_deg"] is not False)
        self.deg.setToolTip(T("각도 단위 — DEG(도) / RAD(라디안)"))
        self.deg.setFocusPolicy(Qt.NoFocus)
        self.deg.setFixedHeight(26)
        self.deg.toggled.connect(lambda on: (self.deg.setText("DEG" if on else "RAD"), self.S.__setitem__("calc_deg", on), self.live()))
        self.deg.setText("DEG" if self.deg.isChecked() else "RAD")
        top.addWidget(self.deg)
        for title, items in ((T("삼각법"), ["sin(", "cos(", "tan(", "asin(", "acos(", "atan("]),
                             (T("함수"), ["floor(", "ceil(", "round(", "min(", "max(", "cbrt(", "log2("]),
                             (T("비트·진법"), ["band(", "bor(", "bxor(", "shl(", "shr(", "0x", "0b", "0o"])):
            tb = QtWidgets.QToolButton()
            tb.setText(title + " ▾")
            tb.setPopupMode(QtWidgets.QToolButton.InstantPopup)
            m = QtWidgets.QMenu(tb)
            for it in items:
                m.addAction(it.rstrip("("), lambda it=it: self.ins(it))
            tb.setMenu(m)
            top.addWidget(tb)
        top.addStretch(1)
        v.addLayout(top)
        g, self.sci_grid = self._grid([["2ⁿᵈ", "π", "e", "C", "⌫"], ["x²", "¹⁄ₓ", "|x|", "exp", "mod"], ["²√x", "(", ")", "n!", "÷"],
                                       ["xʸ", "7", "8", "9", "×"], ["10ˣ", "4", "5", "6", "−"], ["log", "1", "2", "3", "+"],
                                       ["ln", "+/−", "0", ".", "="]])
        self.second = False
        v.addWidget(g, 1)
        return w

    SECOND = {"x²": "x³", "²√x": "³√x", "10ˣ": "2ˣ", "log": "log₂", "ln": "eˣ"}

    def _toggle_second(self):
        self.second = not self.second
        back = {v: k for k, v in self.SECOND.items()}
        for i in range(self.sci_grid.count()):
            b = self.sci_grid.itemAt(i).widget()
            t = b.text()
            if t == "2ⁿᵈ":
                b.setCheckable(True)
                b.setChecked(self.second)
            elif self.second and t in self.SECOND:
                b.setText(self.SECOND[t])
            elif not self.second and t in back:
                b.setText(back[t])
        for i in range(self.sci_grid.count()):   # 단추 글자로 동작하므로 연결을 다시 (글자 바뀜)
            b = self.sci_grid.itemAt(i).widget()
            b.clicked.disconnect()
            b.clicked.connect(lambda _c=False, b=b: self.key(b.text()))

    # ---- 단추 → 식
    def ins(self, t):
        if self.done and (t[:1].isdigit() or t[:1] in ".(" or t[:1].isalpha()):
            self.expr.clear()   # '=' 뒤에 숫자·함수를 치면 새 식 (연산자면 결과에 이어서)
        self.done = False
        self.expr.insert(t)
        self.expr.setFocus()

    def _wrap(self, pre, post=")"):
        t = self.expr.text().strip() or "0"
        self.expr.setText(f"{pre}{t}{post}")
        self.done = False

    def key(self, k):
        if k in ("C",):
            self.expr.clear()
            self.sub.setText("")
            self.done = False
        elif k == "CE":
            self.expr.clear()
        elif k == "⌫":
            self.expr.backspace()
        elif k == "=":
            self.commit()
        elif k == "2ⁿᵈ":
            self._toggle_second()
        elif k == "+/−":
            t = self.expr.text().strip()
            self.expr.setText(t[2:-1] if t.startswith("-(") and t.endswith(")") else (f"-({t})" if t else "-"))
        elif k == "¹⁄ₓ":
            self._wrap("1/(")
        elif k == "x²":
            self._wrap("(", ")^2")
        elif k == "x³":
            self._wrap("(", ")^3")
        elif k == "²√x":
            self._wrap("sqrt(")
        elif k == "³√x":
            self._wrap("cbrt(")
        elif k == "|x|":
            self.ins("abs(")
        elif k == "n!":
            self._wrap("fact(")
        elif k == "xʸ":
            self.ins("^")
        elif k == "10ˣ":
            self.ins("10^(")
        elif k == "2ˣ":
            self.ins("2^(")
        elif k == "eˣ":
            self.ins("exp(")
        elif k == "exp":
            self.ins("exp(")
        elif k == "log":
            self.ins("log(")
        elif k == "log₂":
            self.ins("log2(")
        elif k == "ln":
            self.ins("ln(")
        elif k == "mod":
            self.ins(" mod ")
        else:
            self.ins(k)
        self.expr.setFocus()

    # ---- 계산
    def live(self):
        if not hasattr(self, "deg"):
            return
        t = self.expr.text()
        if not t.strip():
            self.res.setText("")
            self.last = None
            return
        try:
            v = evaluate(t, self.deg.isChecked(), self.ans)
            self.last = v
            extra = bases(v) if self.mode == "sci" else ""
            self.res.setText(("= " + fmt(v)) + (f"    {extra}" if extra else ""))
        except CalcError as ex:
            self.last = None
            self.res.setText(str(ex))

    def commit(self):
        self.live()
        if self.last is None:
            return
        e = self.expr.text().strip()
        line = f"{e} = {fmt(self.last)}"
        self.hist.insertItem(0, line)
        while self.hist.count() > 50:
            self.hist.takeItem(self.hist.count() - 1)
        self.S["calc_hist"] = [self.hist.item(i).text() for i in range(self.hist.count() - 1, -1, -1)]
        self.ans = self.last
        self.sub.setText(e + " =")
        self.expr.setText(fmt(self.last, comma=False))
        self.res.setText(bases(self.last) if self.mode == "sci" else "")   # 결과는 큰 줄에 (표준은 두 번 보이지 않게)
        self.done = True
        log.info("계산 %s", line)

    def copy_result(self):
        v = self.last if self.last is not None else self.ans
        QtWidgets.QApplication.clipboard().setText(fmt(v, comma=False))

    # ---------------------------------------------------- 기록
    def _page_hist(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(0, 2, 0, 0)
        self.hist = QtWidgets.QListWidget()
        self.hist.setObjectName("calcHist")
        self.hist.setWordWrap(True)
        self.hist.itemDoubleClicked.connect(self._reuse)
        self.hist.setToolTip(T("두 번 누르면 그 식을 다시 씀"))
        v.addWidget(self.hist, 1)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        clr = QtWidgets.QToolButton()
        clr.setText("🗑 " + T("기록 지우기"))
        clr.clicked.connect(self.clear_hist)
        row.addWidget(clr)
        v.addLayout(row)
        self.hist_page = w
        return w

    def _reuse(self, it):
        self.b_hist.setChecked(False)
        if self.mode not in ("std", "sci"):
            self.set_mode("std")
        self.expr.setText(it.text().split(" = ")[0])
        self.done = False

    def clear_hist(self):
        self.hist.clear()
        self.S["calc_hist"] = []

    # ---------------------------------------------------- 회계
    def _page_acct(self):
        sc = QtWidgets.QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QtWidgets.QFrame.NoFrame)
        inner = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 4, 0)
        v.setSpacing(4)
        self.acct = {}

        def group(title, fields, fn):
            g = QtWidgets.QGroupBox(title)
            fl = QtWidgets.QFormLayout(g)
            fl.setContentsMargins(6, 4, 6, 4)
            fl.setVerticalSpacing(3)
            fl.setHorizontalSpacing(8)
            eds = {}
            for key, label, default in fields:
                if isinstance(default, list):
                    e = QtWidgets.QComboBox()
                    for txt, data in default:
                        e.addItem(txt, data)
                    e.currentIndexChanged.connect(lambda _i, fn=fn, eds=eds: fn(eds))
                else:
                    e = QtWidgets.QLineEdit(default)
                    e.setAlignment(Qt.AlignRight)
                    e.textChanged.connect(lambda _t, fn=fn, eds=eds: fn(eds))
                fl.addRow(label, e)
                eds[key] = e
            out = QtWidgets.QLabel()
            out.setTextInteractionFlags(Qt.TextSelectableByMouse)
            out.setWordWrap(True)
            of = out.font()
            of.setBold(True)
            out.setFont(of)
            fl.addRow(out)
            eds["_out"] = out
            v.addWidget(g)
            fn(eds)
            return eds
        self.acct["vat"] = group(T("부가세"), [("amt", T("금액"), "110000"), ("rate", T("세율 %"), "10"),
                                             ("kind", T("금액은"), [(T("부가세 포함가"), True), (T("공급가 (부가세 별도)"), False)])], self._vat)
        self.acct["margin"] = group(T("할인·마진"), [("cost", T("원가"), "70000"), ("price", T("판매가"), "100000"), ("disc", T("할인율 %"), "0")], self._margin)
        self.acct["int"] = group(T("이자"), [("p", T("원금"), "10000000"), ("rate", T("연이율 %"), "3.5"), ("m", T("기간 (개월)"), "12"),
                                            ("kind", T("방식"), [(T("단리"), False), (T("월 복리"), True)])], self._int)
        self.acct["loan"] = group(T("대출 상환"), [("p", T("대출금"), "100000000"), ("rate", T("연이율 %"), "4.5"), ("m", T("기간 (개월)"), "360")], self._loan)
        self.acct["round"] = group(T("원 단위 맞추기"), [("v", T("금액"), "123456"), ("unit", T("단위"), [(T("1원"), 1), (T("10원"), 10), (T("100원"), 100), (T("1,000원"), 1000), (T("10,000원"), 10000)]),
                                                    ("how", T("방법"), [(T("반올림"), "round"), (T("올림"), "up"), (T("내림"), "down")])], self._round)
        v.addStretch(1)
        sc.setWidget(inner)
        return sc

    @staticmethod
    def _won(x):
        return T("{0}원").format(fmt(round(x)))   # 다른 언어는 숫자만

    def _vat(self, e):
        s, t, total = vat(_num(e["amt"]), _num(e["rate"]), e["kind"].currentData())
        e["_out"].setText(T("공급가 {0} · 부가세 {1} · 합계 {2}").format(self._won(s), self._won(t), self._won(total)))

    def _margin(self, e):
        cost, price, d = _num(e["cost"]), _num(e["price"]), _num(e["disc"])
        sale = price * (1 - d / 100)
        m, mr, pr = margin(cost, sale)
        e["_out"].setText(T("할인가 {0} · 마진 {1} · 마진율 {2}% (판매가 기준) · 이익률 {3}% (원가 기준)").format(
            self._won(sale), self._won(m), fmt(round(mr, 2)), fmt(round(pr, 2))))

    def _int(self, e):
        i, total = interest(_num(e["p"]), _num(e["rate"]), max(0, int(_num(e["m"]))), e["kind"].currentData())
        tax = i * 0.154
        e["_out"].setText(T("이자 {0} · 만기 {1} (세전) · 일반과세 15.4% 뒤 이자 {2}").format(self._won(i), self._won(total), self._won(i - tax)))

    def _loan(self, e):
        p, r, m = _num(e["p"]), _num(e["rate"]), max(1, int(_num(e["m"])))
        pay, ti = loan(p, r, m, "annuity")
        f, l, ti2 = loan(p, r, m, "equal")
        e["_out"].setText(T("원리금균등: 매달 {0} · 총이자 {1}\n원금균등: 첫 달 {2} → 마지막 달 {3} · 총이자 {4}").format(
            self._won(pay), self._won(ti), self._won(f), self._won(l), self._won(ti2)))

    def _round(self, e):
        e["_out"].setText(self._won(round_won(_num(e["v"]), e["unit"].currentData(), e["how"].currentData())))

    # ---------------------------------------------------- 변환기 (1.3.0 — 윈도우 계산기처럼 위 값·아래 값 크게, 통화 환율 포함)
    def _page_unit(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(4, 6, 4, 4)
        v.setSpacing(4)
        big = QtGui.QFont(self.font())
        big.setPointSizeF(22)
        big.setBold(True)
        self.u_val = QtWidgets.QLineEdit("1")
        self.u_val.setObjectName("calcExpr")
        self.u_val.setFont(big)
        self.u_from = QtWidgets.QComboBox()
        self.u_out = QtWidgets.QLabel()
        self.u_out.setFont(big)
        self.u_out.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.u_to = QtWidgets.QComboBox()
        swap = QtWidgets.QToolButton()
        swap.setText("⇅ " + T("바꾸기"))
        swap.clicked.connect(lambda: self._swap_units())
        for x in (self.u_val, self.u_from):
            v.addWidget(x)
        v.addSpacing(8)
        v.addWidget(self.u_out)
        v.addWidget(self.u_to)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(swap)
        row.addStretch(1)
        self.fx_btn = QtWidgets.QToolButton()
        self.fx_btn.setText("⟳ " + T("환율 새로 받기"))
        self.fx_btn.clicked.connect(lambda: self._fx_fetch(force=True))
        row.addWidget(self.fx_btn)
        v.addLayout(row)
        self.u_info = QtWidgets.QLabel()
        self.u_info.setObjectName("calcSub")
        self.u_info.setWordWrap(True)
        v.addWidget(self.u_info)
        v.addStretch(1)
        self.u_cat = None
        for wd in (self.u_from, self.u_to):
            wd.currentIndexChanged.connect(lambda _i: self._unit_calc())
        self.u_val.textChanged.connect(lambda _t: self._unit_calc())
        self._fx_sig = _FxSig()
        self._fx_sig.done.connect(self._fx_done)
        return w

    def _conv_set(self, cat):
        self.u_cat = cat
        if cat == "fx":
            fx = self.S["calc_fx"] or {}
            names = sorted(fx.get("rates", {"KRW": 1, "USD": 1}).keys(), key=lambda c: (c not in FX_NAMES, c))
            labels = [f"{c}  {T(FX_NAMES[c])}" if c in FX_NAMES else c for c in names]
        else:
            names = list(UNITS[cat][1])
            labels = names
        keep = (self.S["calc_conv"] or {}).get(cat)
        for wd in (self.u_from, self.u_to):
            wd.blockSignals(True)
            wd.clear()
            for n, lb in zip(names, labels):
                wd.addItem(lb, n)
            wd.blockSignals(False)
        if keep and keep[0] in names and keep[1] in names:
            self.u_from.setCurrentIndex(names.index(keep[0]))
            self.u_to.setCurrentIndex(names.index(keep[1]))
        elif cat == "fx":
            self.u_from.setCurrentIndex(names.index("USD") if "USD" in names else 0)
            self.u_to.setCurrentIndex(names.index("KRW") if "KRW" in names else min(1, len(names) - 1))
        elif cat == "area":
            self.u_from.setCurrentIndex(names.index("m²"))
            self.u_to.setCurrentIndex(names.index("평"))
        else:
            self.u_to.setCurrentIndex(min(1, len(names) - 1))
        self.fx_btn.setVisible(cat == "fx")
        if cat == "fx":
            self._fx_fetch()
        self._unit_calc()

    def _swap_units(self):
        a, b = self.u_from.currentIndex(), self.u_to.currentIndex()
        self.u_from.setCurrentIndex(b)
        self.u_to.setCurrentIndex(a)

    def _unit_calc(self):
        if not self.u_cat:
            return
        a, b = self.u_from.currentData(), self.u_to.currentData()
        if a is None or b is None:
            return
        conv = dict(self.S["calc_conv"] or {})
        conv[self.u_cat] = [a, b]
        self.S["calc_conv"] = conv
        try:
            v = float(evaluate(self.u_val.text() or "0"))
            if self.u_cat == "fx":
                fx = self.S["calc_fx"] or {}
                rates = fx.get("rates") or {}
                if a not in rates or b not in rates:
                    self.u_out.setText("—")
                    self.u_info.setText(T("환율을 아직 못 받았습니다 — 인터넷 연결 뒤 '환율 새로 받기'"))
                    return
                r = fx_convert(rates, v, a, b)
                self.u_out.setText(fmt(round(r, 4) if abs(r) < 1000 else round(r, 2)) + f" {b}")
                one = fx_convert(rates, 1, a, b)
                self.u_info.setText(T("1 {0} = {1} {2} · 기준일 {3} · 유럽중앙은행(ECB) 기준 환율, 참고용").format(a, fmt(round(one, 6)), b, fx.get("date", "?")))
            else:
                r = convert(self.u_cat, v, a, b)
                self.u_out.setText(f"{fmt(r)} {b}")
                self.u_info.setText(f"1 {a} = {fmt(convert(self.u_cat, 1, a, b))} {b}")
        except (CalcError, KeyError, ZeroDivisionError) as ex:
            self.u_out.setText(str(ex))

    def _fx_fetch(self, force=False):
        import time as _t
        fx = self.S["calc_fx"] or {}
        if not force and fx.get("rates") and _t.time() - fx.get("t", 0) < 6 * 3600:
            return
        if getattr(self, "_fx_busy", False):
            return
        self._fx_busy = True
        self.u_info.setText(T("환율 받는 중…"))
        import threading

        def work():
            try:
                self._fx_sig.done.emit(fetch_fx(), "")
            except Exception as ex:
                self._fx_sig.done.emit({}, str(ex))
        threading.Thread(target=work, daemon=True).start()

    def _fx_done(self, fx, err):
        self._fx_busy = False
        if fx:
            self.S["calc_fx"] = fx
            log.info("환율 받음 %s (%d개)", fx.get("date"), len(fx.get("rates", {})))
        else:
            log.warning("환율 못 받음: %s", err)
        if self.u_cat == "fx":
            self._conv_set("fx")
            if err:
                self.u_info.setText(T("환율을 받지 못했습니다 ({0}) — 마지막에 받은 값을 씁니다").format(err[:80]))

    # ---------------------------------------------------- 그래프 (1.3.0)
    def _page_graph(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        self.graph = GraphView()
        v.addWidget(self.graph, 1)
        self.g_eds = []
        saved = list(self.S["calc_graph"] or ["sin(x)", "x^2/10", ""])
        for i, col in enumerate(GraphView.COLORS):
            row = QtWidgets.QHBoxLayout()
            dot = QtWidgets.QLabel("●")
            dot.setStyleSheet(f"color:{col}; font-size:14pt;")
            row.addWidget(dot)
            row.addWidget(QtWidgets.QLabel(f"y{i + 1} ="))
            e = QtWidgets.QLineEdit(saved[i] if i < len(saved) else "")
            e.setPlaceholderText(T("예: sin(x), x^2-3, 2*x+1"))
            e.textChanged.connect(self._graph_upd)
            row.addWidget(e, 1)
            v.addLayout(row)
            self.g_eds.append(e)
        tip = QtWidgets.QLabel(T("휠 = 확대·축소 · 끌기 = 옮기기 · 두 번 누르기 = 처음 보기 (라디안)"))
        tip.setObjectName("calcSub")
        v.addWidget(tip)
        self._graph_upd()
        return w

    def _graph_upd(self, *_):
        fs = [e.text() for e in self.g_eds]
        self.S["calc_graph"] = fs
        self.graph.set_funcs(fs)

    # ---------------------------------------------------- 프로그래머 (1.3.0)
    WORDS = [("QWORD", 64), ("DWORD", 32), ("WORD", 16), ("BYTE", 8)]

    def _page_prog(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        self.p_expr = QtWidgets.QLineEdit()
        self.p_expr.setObjectName("calcExpr")
        self.p_expr.setAlignment(Qt.AlignRight)
        self.p_expr.setPlaceholderText("0")
        pf = self.p_expr.font()
        pf.setPointSizeF(20)
        pf.setBold(True)
        self.p_expr.setFont(pf)
        v.addWidget(self.p_expr)
        self.p_err = QtWidgets.QLabel()
        self.p_err.setObjectName("calcSub")
        self.p_err.setAlignment(Qt.AlignRight)
        v.addWidget(self.p_err)
        self.p_base = 10
        self.p_rows = {}
        mono = QtGui.QFont("Consolas")
        mono.setPointSizeF(10)
        for b, name in ((16, "HEX"), (10, "DEC"), (8, "OCT"), (2, "BIN")):
            btn = QtWidgets.QPushButton()
            btn.setCheckable(True)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setFont(mono)
            btn.setStyleSheet("text-align:left; padding:3px 8px; border:none;")
            btn.clicked.connect(lambda _c=False, b=b: self._p_set_base(b))
            btn.setProperty("nm", name)
            v.addWidget(btn)
            self.p_rows[b] = btn
        top = QtWidgets.QHBoxLayout()
        self.p_word = QtWidgets.QComboBox()
        for n, bits in self.WORDS:
            self.p_word.addItem(n, bits)
        self.p_word.setCurrentIndex(0)
        self.p_word.currentIndexChanged.connect(lambda _i: self._p_calc())
        top.addWidget(self.p_word)
        top.addStretch(1)
        v.addLayout(top)
        g = QtWidgets.QGridLayout()
        g.setSpacing(2)
        rows = [["A", "<<", ">>", "C", "⌫"], ["B", "(", ")", "%", "÷"], ["C₁₆", "7", "8", "9", "×"],
                ["D", "4", "5", "6", "−"], ["E", "1", "2", "3", "+"], ["F", "AND", "OR", "XOR", "NOT"], ["+/−", "0", "NAND", "NOR", "="]]
        self.p_btns = {}
        for r, row in enumerate(rows):
            for c, t in enumerate(row):
                k = "num" if (t in "0123456789" or t in "ABDEF" or t == "C₁₆") else ("eq" if t == "=" else "op")
                b = self._btn(t, k, lambda _c=False, t=t: self._p_key(t))
                b.setMinimumHeight(30)
                g.addWidget(b, r, c)
                self.p_btns[t] = b
        v.addLayout(g, 1)
        self.p_expr.textChanged.connect(lambda _t: self._p_calc())
        self.p_expr.returnPressed.connect(lambda: self._p_key("="))
        self._p_set_base(10)
        return w

    def _p_set_base(self, b):
        """입력 진법 바꿈 — 지금 값을 그 진법 글자로"""
        val = getattr(self, "_p_val", None)
        self.p_base = b
        for bb, btn in self.p_rows.items():
            btn.setChecked(bb == b)
        digits = "0123456789ABCDEF"[:b]
        for t, btn in self.p_btns.items():
            d = "C" if t == "C₁₆" else t
            if len(d) == 1 and d in "0123456789ABCDEF":
                btn.setEnabled(d in digits)
        if val is not None:
            self.p_expr.setText(self._p_fmt(val, b))
        self._p_calc()

    def _p_fmt(self, v, b):
        bits = self.p_word.currentData()
        u = v & ((1 << bits) - 1)
        if b == 10:
            return str(u - (1 << bits) if u >> (bits - 1) else u)   # 부호 있는 10진 (윈도우 계산기와 같게)
        s_ = format(u, {16: "X", 8: "o", 2: "b"}[b])
        if b == 2:   # 네 자리씩 띄움 (윈도우 계산기처럼)
            s_ = s_.zfill(-(-len(s_) // 4) * 4)
            s_ = " ".join(s_[i:i + 4] for i in range(0, len(s_), 4))
        return s_

    def _p_eval(self, text):
        """프로그래머 식: 지금 진법 숫자 → 10진으로 바꿔 정수 계산 (AND OR XOR NOT << >> % ÷=몫)"""
        t = text.upper().replace("×", "*").replace("÷", "//").replace("−", "-").replace(" ", "")
        t = t.replace("XOR", "^").replace("AND", "&").replace("OR", "|").replace("NOT", "~")
        b = self.p_base
        pat = {16: r"[0-9A-F]+", 10: r"[0-9]+", 8: r"[0-7]+", 2: r"[01]+"}[b]
        t2 = re.sub(pat, lambda m: str(int(m.group(0), b)), t)
        if re.search(r"[A-Z]", t2):
            raise CalcError(T("이 진법에서 쓸 수 없는 글자"))
        try:
            tree = ast.parse(t2, mode="eval")
        except SyntaxError:
            raise CalcError(T("식을 읽을 수 없습니다"))
        return int(_run(tree, True, 0, None, True))

    def _p_calc(self):
        txt = self.p_expr.text().strip()
        if not txt:
            v = 0
        else:
            try:
                t = re.sub(r"(\w+)\s*NAND\s*(\w+)", r"~(\1 AND \2)", txt.upper())
                t = re.sub(r"(\w+)\s*NOR\s*(\w+)", r"~(\1 OR \2)", t)
                v = self._p_eval(t)
                self.p_err.setText("")
            except (CalcError, SyntaxError, ValueError) as ex:
                self.p_err.setText(str(ex) or T("식을 읽을 수 없습니다"))
                return
        bits = self.p_word.currentData()
        u = v & ((1 << bits) - 1)
        self._p_val = u
        for b, btn in self.p_rows.items():
            btn.setText(f"{btn.property('nm'):<4} {self._p_fmt(u, b)}")

    def _p_key(self, t):
        if t == "C":
            self.p_expr.clear()
        elif t == "⌫":
            self.p_expr.backspace()
        elif t == "=":
            self._p_calc()
            if getattr(self, "_p_val", None) is not None and not self.p_err.text():
                e = self.p_expr.text()
                self.p_expr.setText(self._p_fmt(self._p_val, self.p_base).replace(" ", ""))
                self.p_err.setText(e + " =")
        elif t == "+/−":
            self.p_expr.setText(f"-({self.p_expr.text() or '0'})")
        elif t == "C₁₆":
            self.p_expr.insert("C")
        elif t in ("AND", "OR", "XOR", "NAND", "NOR", "<<", ">>"):
            self.p_expr.insert(f" {t} ")
        elif t == "NOT":
            self.p_expr.insert("NOT ")
        else:
            self.p_expr.insert(t)
        self.p_expr.setFocus()

    # ---------------------------------------------------- 날짜 계산 (1.3.0)
    def _page_date(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(6)
        self.d_kind = QtWidgets.QComboBox()
        self.d_kind.addItem(T("날짜 사이 차이"), "diff")
        self.d_kind.addItem(T("날짜에 더하기·빼기"), "add")
        v.addWidget(self.d_kind)
        today = QtCore.QDate.currentDate()

        def dedit():
            e = QtWidgets.QDateEdit(today)
            e.setCalendarPopup(True)
            e.setDisplayFormat("yyyy-MM-dd (ddd)")
            return e
        self.d_box_diff = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(self.d_box_diff)
        f.setContentsMargins(0, 0, 0, 0)
        self.d_from = dedit()
        self.d_to = dedit()
        self.d_to.setDate(today.addDays(100))
        f.addRow(T("시작"), self.d_from)
        f.addRow(T("끝"), self.d_to)
        v.addWidget(self.d_box_diff)
        self.d_box_add = QtWidgets.QWidget()
        f2 = QtWidgets.QFormLayout(self.d_box_add)
        f2.setContentsMargins(0, 0, 0, 0)
        self.d_base = dedit()
        self.d_sign = QtWidgets.QComboBox()
        self.d_sign.addItem(T("더하기"), 1)
        self.d_sign.addItem(T("빼기"), -1)
        self.d_y, self.d_m, self.d_dd = QtWidgets.QSpinBox(), QtWidgets.QSpinBox(), QtWidgets.QSpinBox()
        for sp, mx in ((self.d_y, 999), (self.d_m, 999), (self.d_dd, 99999)):
            sp.setRange(0, mx)
        self.d_dd.setValue(100)
        f2.addRow(T("날짜"), self.d_base)
        f2.addRow("", self.d_sign)
        f2.addRow(T("년"), self.d_y)
        f2.addRow(T("개월"), self.d_m)
        f2.addRow(T("일"), self.d_dd)
        v.addWidget(self.d_box_add)
        self.d_out = QtWidgets.QLabel()
        df = self.d_out.font()
        df.setPointSizeF(15)
        df.setBold(True)
        self.d_out.setFont(df)
        self.d_out.setWordWrap(True)
        self.d_out.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.d_out)
        self.d_sub = QtWidgets.QLabel()
        self.d_sub.setObjectName("calcSub")
        self.d_sub.setWordWrap(True)
        v.addWidget(self.d_sub)
        v.addStretch(1)
        for x in (self.d_from, self.d_to, self.d_base):
            x.dateChanged.connect(lambda _d: self._date_calc())
        for x in (self.d_y, self.d_m, self.d_dd):
            x.valueChanged.connect(lambda _v: self._date_calc())
        self.d_sign.currentIndexChanged.connect(lambda _i: self._date_calc())
        self.d_kind.currentIndexChanged.connect(lambda _i: self._date_calc())
        self._date_calc()
        return w

    def _date_calc(self):
        diff = self.d_kind.currentData() == "diff"
        self.d_box_diff.setVisible(diff)
        self.d_box_add.setVisible(not diff)
        if diff:
            a, b = self.d_from.date(), self.d_to.date()
            if b < a:
                a, b = b, a
            days = a.daysTo(b)
            y, m, d = date_diff(a.year(), a.month(), a.day(), b.year(), b.month(), b.day())
            parts = []
            if y:
                parts.append(T("{0}년").format(y))
            if m:
                parts.append(T("{0}개월").format(m))
            w_, d2 = divmod(d, 7)
            if w_:
                parts.append(T("{0}주").format(w_))
            if d2 or not parts:
                parts.append(T("{0}일").format(d2))
            self.d_out.setText(" ".join(parts) if days else T("같은 날"))
            self.d_sub.setText(T("총 {0:,}일 · {1:,}주 {2}일 · 시작일 빼고 셈 (D+{0})").format(days, days // 7, days % 7))
        else:
            s_ = self.d_sign.currentData()
            r = self.d_base.date().addYears(s_ * self.d_y.value()).addMonths(s_ * self.d_m.value()).addDays(s_ * self.d_dd.value())
            self.d_out.setText(r.toString("yyyy-MM-dd (dddd)"))
            self.d_sub.setText(T("오늘부터 {0:+,}일").format(QtCore.QDate.currentDate().daysTo(r)))

    # ---------------------------------------------------- 창
    def open_windows_calc(self):
        import os
        try:
            os.startfile("calc.exe")
            log.info("윈도우 계산기 열기")
        except OSError as ex:
            log.warning("윈도우 계산기 못 엶: %s", ex)

    def set_top(self, on):
        self.S["calc_top"] = bool(on)
        g = self.geometry()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(on))
        self.setGeometry(g)
        self.show()

    def save_geo(self):
        g = self.geometry()
        self.S["calc_geo"] = [g.x(), g.y(), g.width(), g.height(), 3]   # 끝 3 = 1.2 화면(메모리 줄)에서 저장한 크기

    def closeEvent(self, ev):
        self.save_geo()
        super().closeEvent(ev)


# ================================================================ 1.3.0 도움 (날짜·환율 신호·그래프)
def date_diff(y1, m1, d1, y2, m2, d2):
    """(년, 개월, 일) — 앞 날짜에 달을 더할 수 있는 만큼 더하고(달 끝은 그 달 마지막 날), 남은 날 수"""
    import calendar
    import datetime as _dt
    a, b = _dt.date(y1, m1, d1), _dt.date(y2, m2, d2)

    def add_m(n):
        yy, mm = divmod(a.month - 1 + n, 12)
        yy += a.year
        return _dt.date(yy, mm + 1, min(a.day, calendar.monthrange(yy, mm + 1)[1]))
    n = (b.year - a.year) * 12 + (b.month - a.month)
    while n > 0 and add_m(n) > b:
        n -= 1
    days = (b - add_m(n)).days
    return n // 12, n % 12, days


class _FxSig(QtCore.QObject):
    done = QtCore.Signal(dict, str)


class GraphView(QtWidgets.QWidget):
    """y = f(x) 그래프 (라디안). 휠 확대·축소, 끌어서 옮기기, 두 번 누르면 처음 보기"""
    COLORS = ["#2563eb", "#e5484d", "#16a34a"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cx, self.cy, self.scale = 0.0, 0.0, 40.0   # 가운데 값 · 1 단위 = 몇 화소
        self.trees = []
        self._drag = None
        self.setMinimumHeight(260)
        self.setMouseTracking(True)
        self._hover = None

    def set_funcs(self, fs):
        self.trees = []
        for f in fs:
            f = (f or "").strip()
            if not f:
                self.trees.append(None)
                continue
            try:
                self.trees.append(parse(f))
            except CalcError:
                self.trees.append(False)
        self.update()

    def _to_px(self, x, y):
        return self.width() / 2 + (x - self.cx) * self.scale, self.height() / 2 - (y - self.cy) * self.scale

    def _to_val(self, px, py):
        return self.cx + (px - self.width() / 2) / self.scale, self.cy - (py - self.height() / 2) / self.scale

    @staticmethod
    def _step(scale):
        raw = 60 / scale   # 눈금 사이가 60화소쯤
        e = 10 ** math.floor(math.log10(raw))
        for m in (1, 2, 5, 10):
            if m * e >= raw:
                return m * e
        return 10 * e

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        pal = self.palette()
        bg = pal.base().color()
        p.fillRect(self.rect(), bg)
        dark = bg.lightness() < 128
        grid = QtGui.QColor(255, 255, 255, 30) if dark else QtGui.QColor(0, 0, 0, 25)
        axis = QtGui.QColor(255, 255, 255, 140) if dark else QtGui.QColor(0, 0, 0, 140)
        txt = QtGui.QColor(200, 200, 200) if dark else QtGui.QColor(90, 90, 90)
        st = self._step(self.scale)
        x0, y1 = self._to_val(0, 0)
        x1, y0 = self._to_val(self.width(), self.height())
        f = p.font()
        f.setPointSizeF(8)
        p.setFont(f)
        ox, oy = self._to_px(0, 0)
        k = math.floor(x0 / st)
        while k * st <= x1:
            px, _ = self._to_px(k * st, 0)
            p.setPen(grid)
            p.drawLine(QtCore.QPointF(px, 0), QtCore.QPointF(px, self.height()))
            if k:
                p.setPen(txt)
                p.drawText(QtCore.QPointF(px + 2, min(max(oy + 12, 12), self.height() - 3)), fmt(round(k * st, 10), comma=False))
            k += 1
        k = math.floor(y0 / st)
        while k * st <= y1:
            _, py = self._to_px(0, k * st)
            p.setPen(grid)
            p.drawLine(QtCore.QPointF(0, py), QtCore.QPointF(self.width(), py))
            if k:
                p.setPen(txt)
                p.drawText(QtCore.QPointF(min(max(ox + 3, 3), self.width() - 30), py - 2), fmt(round(k * st, 10), comma=False))
            k += 1
        p.setPen(QtGui.QPen(axis, 1.2))
        p.drawLine(QtCore.QPointF(0, oy), QtCore.QPointF(self.width(), oy))
        p.drawLine(QtCore.QPointF(ox, 0), QtCore.QPointF(ox, self.height()))
        for tree, col in zip(self.trees, self.COLORS):
            if not tree:
                continue
            p.setPen(QtGui.QPen(QtGui.QColor(col), 2))
            path = QtGui.QPainterPath()
            started = False
            prev = None
            for px in range(0, self.width() + 1, 2):
                xv, _ = self._to_val(px, 0)
                try:
                    yv = float(_run(tree, False, 0, xv, False))
                    if math.isnan(yv) or math.isinf(yv):
                        raise ValueError
                except (CalcError, ValueError, OverflowError, ZeroDivisionError, TypeError):
                    started = False
                    prev = None
                    continue
                _, py = self._to_px(xv, yv)
                if prev is not None and abs(py - prev) > self.height() * 2:   # tan 같은 끊김
                    started = False
                py = min(max(py, -1e5), 1e5)
                if started:
                    path.lineTo(px, py)
                else:
                    path.moveTo(px, py)
                    started = True
                prev = py
            p.drawPath(path)
        if self._hover is not None:
            hx, hy = self._hover
            vx, vy = self._to_val(hx, hy)
            p.setPen(txt)
            p.drawText(QtCore.QPointF(6, self.height() - 6), f"x = {vx:.4g}   y = {vy:.4g}")
        p.end()

    def wheelEvent(self, ev):
        pos = ev.position()
        before = self._to_val(pos.x(), pos.y())
        self.scale = min(max(self.scale * (1.2 if ev.angleDelta().y() > 0 else 1 / 1.2), 1e-3), 1e6)
        after = self._to_val(pos.x(), pos.y())
        self.cx += before[0] - after[0]
        self.cy += before[1] - after[1]
        self.update()

    def mousePressEvent(self, ev):
        self._drag = (ev.position().x(), ev.position().y(), self.cx, self.cy)

    def mouseMoveEvent(self, ev):
        if self._drag:
            x0, y0, cx, cy = self._drag
            self.cx = cx - (ev.position().x() - x0) / self.scale
            self.cy = cy + (ev.position().y() - y0) / self.scale
        self._hover = (ev.position().x(), ev.position().y())
        self.update()

    def mouseReleaseEvent(self, ev):
        self._drag = None

    def mouseDoubleClickEvent(self, ev):
        self.cx, self.cy, self.scale = 0.0, 0.0, 40.0
        self.update()

    def leaveEvent(self, ev):
        self._hover = None
        self.update()
