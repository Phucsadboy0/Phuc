"""Gộp toàn bộ package aotr_farm thành MỘT file Python: AOTRFarm.py

    python tools/build_onefile.py

File kết quả chạy độc lập: ``python AOTRFarm.py`` (tự tạo config/, macro mẫu,
templates/, logs/, data/ cạnh file).
"""

from __future__ import annotations

import json
import pprint
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "aotr_farm"
OUT = ROOT / "AOTRFarm.py"

# Thứ tự theo phụ thuộc (module được dùng phải đứng trước)
MODULES = [
    "__init__.py", "config.py", "logging_setup.py", "stats.py",
    "platform/__init__.py", "platform/window.py", "platform/input.py", "platform/hotkeys.py",
    "vision.py", "ocr.py", "macro.py", "notifier.py", "resources.py", "engine.py",
    "services.py", "gui/region_picker.py", "gui/app.py", "__main__.py",
]

REL_IMPORT = re.compile(r"^(\s*)from \.+[\w.]* import .*$")
FUTURE = "from __future__ import annotations"


def strip_module(src: str) -> str:
    lines = src.splitlines()
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == FUTURE:
            i += 1
            continue
        m = REL_IMPORT.match(line)
        if m:
            indent = m.group(1)
            # import nhiều dòng trong ngoặc: bỏ tới dấu ')'
            if "(" in line and ")" not in line:
                while ")" not in lines[i]:
                    i += 1
            # trong hàm: thay bằng 'pass' để không làm rỗng khối lệnh
            if indent:
                out.append(f"{indent}pass")
            i += 1
            continue
        out.append(line)
        i += 1
    return "\n".join(out).strip("\n")


def main() -> None:
    parts = [
        '"""AOTR Farm Assistant - bản MỘT FILE (tự sinh bởi tools/build_onefile.py).',
        "",
        "Chạy trên Windows:  python AOTRFarm.py          (mở giao diện)",
        "                    python AOTRFarm.py --check  (kiểm tra môi trường)",
        "Cài thư viện:       pip install numpy opencv-python mss Pillow psutil",
        "",
        "Đây là chương trình Python chạy NGOÀI Roblox (đọc màn hình + giả lập phím/chuột).",
        "KHÔNG phải script Lua cho executor.",
        '"""',
        "",
        FUTURE,
        "",
    ]
    for rel in MODULES:
        src = (PKG / rel).read_text(encoding="utf-8")
        body = strip_module(src)
        if rel == "config.py":
            # Bản một file: thư mục làm việc là thư mục chứa AOTRFarm.py
            body = body.replace("Path(__file__).resolve().parent.parent", "Path(__file__).resolve().parent")
        if rel == "__main__.py":
            body = body.replace("    ensure_dirs()\n", "    ensure_dirs()\n    write_default_macros()\n", 1)
        parts += [f"# {'=' * 70}", f"# {rel}", f"# {'=' * 70}", body, "", ""]

        if rel == "config.py":
            macros = {p.stem: json.loads(p.read_text(encoding="utf-8"))
                      for p in sorted((ROOT / "config" / "macros").glob("*.json"))}
            parts += [
                "# Macro mẫu - tự ghi ra config/macros/ nếu chưa có",
                f"DEFAULT_MACROS = {pprint.pformat(macros, width=110, sort_dicts=False)}",
                "",
                "",
                "def write_default_macros() -> None:",
                "    MACRO_DIR.mkdir(parents=True, exist_ok=True)",
                "    for _name, _data in DEFAULT_MACROS.items():",
                "        _p = MACRO_DIR / f'{_name}.json'",
                "        if not _p.exists():",
                "            _p.write_text(json.dumps(_data, ensure_ascii=False, indent=2), encoding='utf-8')",
                "",
                "",
            ]
    OUT.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    print(f"Đã tạo {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
