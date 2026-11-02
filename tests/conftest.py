"""Đối tượng giả (fake) để test engine mà không cần Windows / Roblox."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aotr_farm.platform.window import Rect  # noqa: E402


class FakeWindow:
    def __init__(self):
        self.alive = True

    def ensure(self):
        return self.alive

    def find(self):
        return self.alive

    def is_valid(self):
        return self.alive

    def client_rect(self):
        return Rect(0, 0, 1280, 720) if self.alive else None

    def is_minimized(self):
        return False

    def is_foreground(self):
        return True

    def focus(self):
        return self.alive


class FakeInput:
    def __init__(self):
        self.events = []
        self.held_keys = set()

    def press(self, key, duration=0.05):
        self.events.append(("press", key))

    def key_down(self, key):
        self.held_keys.add(key)
        self.events.append(("down", key))

    def key_up(self, key):
        self.held_keys.discard(key)
        self.events.append(("up", key))

    def click(self, x=None, y=None, button="left", hold=0.05):
        self.events.append(("click", x, y, button))

    def mouse_down(self, button="left"):
        self.events.append(("mdown", button))

    def mouse_up(self, button="left"):
        self.events.append(("mup", button))

    def move_rel(self, dx, dy):
        self.events.append(("move", dx, dy))

    def scroll(self, amount):
        self.events.append(("scroll", amount))

    def release_all(self):
        for k in list(self.held_keys):
            self.key_up(k)
        self.events.append(("release_all",))

    @property
    def held(self):
        return set(self.held_keys)


class FakeMatcher:
    def __init__(self, available):
        self.available = set(available)

    def exists(self, name):
        return name in self.available


class FakeMatch:
    def __init__(self, name):
        self.name, self.score, self.x, self.y, self.w, self.h = name, 0.99, 100, 100, 10, 10


class FakeVision:
    """``script`` là hàm trả về trạng thái hiện tại ('lobby', 'reward', None...)."""

    def __init__(self, available, script):
        self.matcher = FakeMatcher(available)
        self.script = script
        self.calls = 0

    def grab(self, rect):
        import numpy as np
        return np.zeros((rect.height, rect.width, 3), dtype="uint8")

    def find_any(self, rect, names):
        self.calls += 1
        state = self.script()
        if state in names:
            return state, FakeMatch(names[state])
        return None

    def find(self, rect, name, threshold=None):
        return FakeMatch(name) if name in self.matcher.available else None

    def count_items(self, rect, item_dir):
        return {}


class FakeReader:
    def __init__(self, exp=100, gold=50):
        self.exp, self.gold = exp, gold

    def read_rewards(self, frame, rect):
        return {"exp": self.exp, "gold": self.gold}


@pytest.fixture
def macro_dir(tmp_path):
    d = tmp_path / "macros"
    d.mkdir()

    def write(name, steps):
        (d / f"{name}.json").write_text(json.dumps({"name": name, "steps": steps}), encoding="utf-8")

    write("mission_loop", [{"action": "press", "key": "e"}, {"action": "wait", "seconds": 0.01}])
    write("after_reward", [{"action": "log", "message": "reward"}])
    write("recover", [{"action": "release_all"}])
    return d
