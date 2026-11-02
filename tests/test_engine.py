import threading
import time

from aotr_farm.config import AppConfig, NotifyConfig
from aotr_farm.engine import FarmEngine, State
from aotr_farm.macro import MacroLibrary
from aotr_farm.notifier import Notifier
from aotr_farm.stats import SessionStats

from conftest import FakeInput, FakeReader, FakeVision, FakeWindow

ALL_TEMPLATES = ["lobby_play_button", "mission_hud", "reward_screen", "disconnected_dialog"]


def make_engine(macro_dir, script, templates=ALL_TEMPLATES, **timing):
    cfg = AppConfig()
    cfg.focus_window = False
    cfg.timing.detection_interval = 0.01
    cfg.timing.delay_between_runs = 0
    cfg.timing.action_jitter = 0
    for k, v in timing.items():
        setattr(cfg.timing, k, v)
    notifier = Notifier(NotifyConfig(sound=False, desktop_toast=False))
    events = []
    eng = FarmEngine(cfg, FakeWindow(), FakeVision(templates, script), FakeInput(),
                     MacroLibrary(macro_dir), FakeReader(), notifier, SessionStats())
    eng.on_event = lambda kind, data: events.append((kind, data))
    eng.REWARD_SETTLE_DELAY = 0      # chạy test nhanh hơn
    return eng, events


def wait_done(eng, timeout=10):
    eng.join(timeout)
    assert not eng.running, "engine không dừng"


def test_completes_requested_number_of_runs(macro_dir):
    # Mỗi lượt: 2 lần thấy HUD nhiệm vụ rồi tới màn hình thưởng
    seq = iter(["in_mission", "in_mission", "reward"] * 10)
    eng, events = make_engine(macro_dir, lambda: next(seq, "reward"), max_runs=3)
    eng.start()
    wait_done(eng)
    snap = eng.stats.snapshot()
    assert snap["success_runs"] == 3
    assert snap["total_exp"] == 300 and snap["total_gold"] == 150
    assert eng.state == State.STOPPED
    assert "Đã đủ 3 lượt" in eng.stop_reason
    assert [k for k, _ in events].count("run_finished") == 3


def test_timed_mode_without_reward_template(macro_dir):
    eng, _ = make_engine(macro_dir, lambda: None, templates=[], max_runs=2)
    eng.start()
    wait_done(eng)
    assert eng.stats.success_runs == 2


def test_stuck_detection_stops_after_max_errors(macro_dir):
    # Không nhận diện được gì (None) dù có template -> kẹt
    eng, events = make_engine(macro_dir, lambda: None,
                              templates=["reward_screen"], stuck_timeout=0.05)
    eng.cfg.max_consecutive_errors = 2
    eng._recover = lambda: None    # bỏ qua khoảng chờ khôi phục
    eng.start()
    wait_done(eng)
    assert eng.stats.errors == 2
    assert "lỗi liên tiếp" in eng.stop_reason
    assert any(k == "error" for k, _ in events)


def test_disconnect_is_reported(macro_dir):
    eng, events = make_engine(macro_dir, lambda: "disconnected")
    eng.cfg.max_consecutive_errors = 1
    eng.start()
    wait_done(eng)
    assert "mất kết nối" in eng.stop_reason.lower()


def test_missing_window_is_fatal(macro_dir):
    eng, _ = make_engine(macro_dir, lambda: None)
    eng.window.alive = False
    eng.start()
    wait_done(eng)
    assert eng.state == State.ERROR
    assert "Không tìm thấy cửa sổ" in eng.stop_reason


def test_pause_resume_and_stop(macro_dir):
    eng, _ = make_engine(macro_dir, lambda: "in_mission", mission_timeout=60)
    eng.start()
    time.sleep(0.2)
    eng.input.key_down("w")             # giả lập đang giữ phím
    eng.pause()
    assert eng.paused and eng.state == State.PAUSED
    assert "w" not in eng.input.held    # phím được nhả khi pause
    def sent():  # các thao tác thật sự gửi tới game (bỏ qua lệnh nhả phím)
        return [e for e in eng.input.events if e[0] not in ("release_all", "up")]

    presses = len(eng.input.events)
    before = len(sent())
    time.sleep(0.3)
    assert len(sent()) == before              # không gửi phím khi đang pause
    eng.resume()
    time.sleep(0.2)
    assert not eng.paused
    assert ("down", "w") in eng.input.events[presses:]   # giữ lại phím sau resume
    eng.stop()
    wait_done(eng)
    assert eng.state == State.STOPPED
    assert eng.input.held == set()


def test_max_duration_limit(macro_dir):
    eng, _ = make_engine(macro_dir, lambda: "reward", max_duration_minutes=0.5 / 60)
    eng.start()
    wait_done(eng)
    assert "phút" in eng.stop_reason


def test_selects_slot_then_plays(macro_dir):
    """Mới vào game: màn hình chọn slot -> SELECT -> menu chính -> PLAY -> nhiệm vụ."""
    import json
    (macro_dir / "select_slot.json").write_text(json.dumps({"steps": [
        {"action": "click_image", "template": "slot_a_card", "anchor_x": 0.5, "anchor_y": 0.92},
        {"action": "click_image", "template": "join_community_button", "timeout": 0, "optional": True},
    ]}))
    (macro_dir / "start_mission.json").write_text(json.dumps({"steps": [
        {"action": "click_image", "template": "lobby_play_button"},
    ]}))
    seq = iter(["slot_select", "slot_select", "lobby", "lobby", "in_mission", "reward"])
    eng, events = make_engine(macro_dir, lambda: next(seq, "reward"),
                              templates=ALL_TEMPLATES + ["slot_a_card", "join_community_button"],
                              max_runs=1)
    eng.start()
    wait_done(eng)
    assert eng.stats.success_runs == 1
    clicks = [e for e in eng.input.events if e[0] == "click"]
    # FakeMatch: tâm (100,100), cao 10 -> anchor_y 0.92 => y = 100 + int(0.42*10) = 104
    assert clicks[0][1:3] == (100, 104)          # SELECT ở đáy thẻ Slot A
    assert len(clicks) >= 3                      # SELECT, Join Community, PLAY
    states = [d["state"] for k, d in events if k == "state"]
    assert states.index(State.SELECT_SLOT) < states.index(State.IN_MISSION)


def test_kicked_to_slot_screen_mid_mission_is_error(macro_dir):
    seq = iter(["in_mission", "slot_select"])
    eng, _ = make_engine(macro_dir, lambda: next(seq, "slot_select"),
                         templates=ALL_TEMPLATES + ["slot_a_card"])
    eng.cfg.max_consecutive_errors = 1
    eng.start()
    wait_done(eng)
    assert "chọn slot" in eng.stop_reason
