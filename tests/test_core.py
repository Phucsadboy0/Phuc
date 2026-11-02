import json
import time

import pytest

from aotr_farm.config import AppConfig, load_config, save_config
from aotr_farm.macro import Macro, MacroError, MacroRunner, StopRequested
from aotr_farm.ocr import parse_number
from aotr_farm.stats import SessionStats, fmt_duration

from conftest import FakeInput


# ------------------------------- config -------------------------------- #
def test_config_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    cfg = AppConfig()
    cfg.timing.max_runs = 7
    cfg.ocr.regions["exp"] = [0.1, 0.2, 0.3, 0.4]
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.timing.max_runs == 7
    assert loaded.ocr.regions["exp"] == [0.1, 0.2, 0.3, 0.4]


def test_config_tolerates_bad_and_unknown_keys(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"unknown": 1, "timing": {"max_runs": "5", "mission_timeout": "abc"}}))
    cfg = load_config(path)
    assert cfg.timing.max_runs == 5
    assert cfg.timing.mission_timeout == AppConfig().timing.mission_timeout


def test_config_corrupt_file_falls_back(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    assert load_config(path).window_title == "Roblox"


# -------------------------------- stats -------------------------------- #
def test_stats_accumulate_and_csv(tmp_path):
    st = SessionStats(tmp_path)
    st.start_session()
    st.begin_run()
    st.finish_run(True, exp=100, gold=20, items={"crystal": 1})
    st.begin_run()
    st.finish_run(False, note="fail")
    st.begin_run()
    st.finish_run(True, exp=50, gold=5, items={"crystal": 2})
    snap = st.snapshot()
    assert snap["total_runs"] == 3 and snap["success_runs"] == 2 and snap["failed_runs"] == 1
    assert snap["total_exp"] == 150 and snap["total_gold"] == 25
    assert snap["items"] == {"crystal": 3}
    lines = (tmp_path / "run_history.csv").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 4  # header + 3
    st.end_session()
    assert st.save_summary().exists()


def test_stats_pause_excluded_from_elapsed():
    st = SessionStats()
    st.start_session()
    st.session_start -= 10          # giả lập đã chạy 10s
    st.pause()
    st._pause_started -= 4          # trong đó 4s là pause
    st.resume()
    assert 5.5 < st.elapsed < 6.5


def test_fmt_duration():
    assert fmt_duration(3725) == "01:02:05"


# --------------------------------- OCR --------------------------------- #
@pytest.mark.parametrize("text,expected", [
    ("+1,250 EXP", 1250), ("Gold: 3.400", 3400), ("12.5K", 12500),
    ("1.2M", 1_200_000), ("", None), ("abc", None), ("x 25\n", 25),
])
def test_parse_number(text, expected):
    assert parse_number(text) == expected


# -------------------------------- macro -------------------------------- #
class Ctx:
    def __init__(self, stop_after=None):
        self.input = FakeInput()
        self.slept = 0.0
        self.checks = 0
        self.stop_after = stop_after

    def checkpoint(self):
        self.checks += 1
        if self.stop_after and self.checks > self.stop_after:
            raise StopRequested()

    def sleep(self, s):
        self.slept += s

    def to_abs(self, rx, ry):
        return int(rx * 1000), int(ry * 1000)

    def find_template(self, name, threshold=None):
        return None

    def run_macro(self, name):
        pass


@pytest.mark.parametrize("steps", [
    [{"key": "w"}],                                   # thiếu action
    [{"action": "fly"}],                              # action lạ
    [{"action": "press"}],                            # thiếu key
    [{"action": "click", "x": 1.5, "y": 0.2}],        # ngoài 0..1
    [{"action": "repeat", "times": 2, "steps": [{"action": "nope"}]}],
])
def test_macro_validation_errors(steps):
    with pytest.raises(MacroError):
        Macro("bad", steps)


def test_macro_runner_executes_steps():
    ctx = Ctx()
    m = Macro("m", [
        {"action": "hold", "key": "w", "seconds": 1.0},
        {"action": "repeat", "times": 2, "steps": [{"action": "press", "key": "space"}]},
        {"action": "click", "x": 0.5, "y": 0.25},
        {"action": "mouse_move_rel", "dx": 100, "dy": -10, "steps": 4},
        {"action": "if_image", "template": "x", "then": [{"action": "press", "key": "q"}],
         "else": [{"action": "press", "key": "e"}]},
    ])
    MacroRunner(ctx, jitter=0).run(m)
    ev = ctx.input.events
    assert ev[0] == ("down", "w") and ev[1] == ("up", "w")
    assert ev.count(("press", "space")) == 2
    assert ("click", 500, 250, "left") in ev
    moves = [e for e in ev if e[0] == "move"]
    assert sum(e[1] for e in moves) == 100 and sum(e[2] for e in moves) == -10
    assert ("press", "e") in ev and ("press", "q") not in ev


def test_macro_wait_image_timeout_raises_unless_optional():
    ctx = Ctx()
    runner = MacroRunner(ctx, jitter=0)
    with pytest.raises(MacroError):
        runner.run(Macro("m", [{"action": "wait_image", "template": "t", "timeout": 0}]))
    runner.run(Macro("m", [{"action": "click_image", "template": "t", "timeout": 0, "optional": True}]))


def test_macro_stop_interrupts():
    ctx = Ctx(stop_after=2)
    with pytest.raises(StopRequested):
        MacroRunner(ctx).run(Macro("m", [{"action": "press", "key": "e"}] * 10))
    assert ctx.input.events.count(("press", "e")) == 2


def test_hold_releases_key_on_stop():
    class StopCtx(Ctx):
        def sleep(self, s):
            raise StopRequested()

    ctx = StopCtx()
    with pytest.raises(StopRequested):
        MacroRunner(ctx).run(Macro("m", [{"action": "hold", "key": "w", "seconds": 5}]))
    assert ctx.input.held == set()


def test_shipped_macros_are_valid():
    from aotr_farm.config import MACRO_DIR
    files = list(MACRO_DIR.glob("*.json"))
    assert files
    for f in files:
        Macro.load(f)


# ------------------------------- vision -------------------------------- #
def test_template_matching_with_scaling(tmp_path):
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    from aotr_farm.platform.window import Rect
    from aotr_farm.vision import TemplateMatcher, save_png

    rng = np.random.default_rng(0)
    # "Nút" có họa tiết riêng, chụp ở cửa sổ rộng 640px
    button = rng.integers(0, 255, (30, 60, 3), dtype=np.uint8)
    save_png(button, tmp_path / "btn.png")
    save_png(button, tmp_path / "items" / "gem.png")

    m = TemplateMatcher(tmp_path, threshold=0.8, reference_width=640)
    # Cửa sổ hiện tại rộng 1280 -> nút to gấp đôi
    frame = np.full((720, 1280, 3), 40, dtype=np.uint8)
    big = cv2.resize(button, (120, 60), interpolation=cv2.INTER_LINEAR)
    frame[400:460, 700:820] = big
    hit = m.find(m.prepare(frame), "btn", Rect(10, 20, 1280, 720))
    assert hit is not None and hit.score > 0.8
    assert abs(hit.x - (10 + 760)) <= 3 and abs(hit.y - (20 + 430)) <= 3
    assert m.find(m.prepare(np.full_like(frame, 40)), "btn", Rect(0, 0, 1280, 720)) is None
    assert m.find(m.prepare(frame), "missing", Rect(0, 0, 1280, 720)) is None

    # Đếm 3 icon giống nhau
    m2 = TemplateMatcher(tmp_path, threshold=0.9, reference_width=1280)
    frame2 = np.full((720, 1280, 3), 40, dtype=np.uint8)
    for x, y in [(100, 50), (300, 200), (500, 120)]:
        frame2[y:y + 30, x:x + 60] = button
    assert m2.count(m2.prepare(frame2), str(tmp_path / "items" / "gem.png"), 1280) == 3


def test_click_image_anchor():
    class Hit:
        x, y, w, h = 200, 300, 100, 200

    class AnchorCtx(Ctx):
        def find_template(self, name, threshold=None):
            return Hit()

    ctx = AnchorCtx()
    MacroRunner(ctx, jitter=0).run(Macro("m", [
        {"action": "click_image", "template": "card", "anchor_x": 0.5, "anchor_y": 0.92},
        {"action": "click_image", "template": "card"},
    ]))
    clicks = [e for e in ctx.input.events if e[0] == "click"]
    assert clicks[0][1:3] == (200, 384)   # 300 + (0.92-0.5)*200
    assert clicks[1][1:3] == (200, 300)   # mặc định: tâm ảnh
    with pytest.raises(MacroError):
        Macro("bad", [{"action": "click_image", "template": "t", "anchor_y": 1.5}])


def test_old_config_gets_new_state_templates(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"detection": {"state_templates": {"lobby": "my_lobby"}}}))
    cfg = load_config(path)
    assert cfg.detection.state_templates["lobby"] == "my_lobby"
    assert cfg.detection.state_templates["slot_select"] == "slot_a_card"
