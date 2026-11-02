# AOTR Farm Assistant

Công cụ hỗ trợ farm cho **Attack on Titan Revolution (Roblox)** trên Windows, viết bằng Python:
giao diện riêng, Start/Stop/Pause/Resume, theo dõi trạng thái nhiệm vụ, thống kê EXP/vàng/vật
phẩm, ghi log, phát hiện lỗi và thông báo, giới hạn thời gian chạy.

> ## ⚠️ Đọc trước khi dùng
> * Công cụ **chỉ** làm những gì một người chơi làm: **nhìn màn hình** (chụp ảnh, so khớp hình,
>   OCR) và **bấm phím/chuột** (Windows `SendInput`). Nó **không** inject, **không** đọc/ghi bộ nhớ,
>   **không** sửa client Roblox và **không** dùng API nội bộ hay mã nguồn của AOTR.
> * Dù vậy, **Điều khoản sử dụng của Roblox** và luật của từng game có thể cấm hoặc hạn chế
>   macro/AFK farm. Hãy tự đọc luật hiện hành của Roblox và AOTR. **Bạn tự chịu trách nhiệm** về
>   tài khoản của mình. Nên dùng ở private server và không để máy chạy khi vắng mặt quá lâu.
> * Không dùng công cụ này để làm phiền hoặc gây bất lợi cho người chơi khác.

---

## 1. Kiến trúc

```
┌──────────────────────────── GUI (tkinter) ─────────────────────────────┐
│ Điều khiển │ Thống kê │ Nhật ký │ Cài đặt │ Công cụ    + phím tắt F6/F7/F8│
└───────▲───────────────────────────────┬────────────────────────────────┘
        │ sự kiện (queue, 200 ms)        │ start/stop/pause/resume
┌───────┴───────────────────────────────▼────────────────────────────────┐
│ FarmEngine (luồng riêng) - máy trạng thái                               │
│   LOBBY → IN_MISSION (lặp macro) → REWARD → LOBBY ...                   │
│   giới hạn lượt/thời gian/giờ dừng, nghỉ giải lao, phát hiện lỗi/kẹt    │
└──┬──────────────┬──────────────┬──────────────┬──────────────┬─────────┘
   │              │              │              │              │
┌──▼─────┐ ┌──────▼──────┐ ┌─────▼─────┐ ┌──────▼─────┐ ┌──────▼──────┐
│ Macro  │ │ Vision      │ │ OCR       │ │ Stats      │ │ Notifier    │
│ (JSON) │ │ mss+OpenCV  │ │ Tesseract │ │ CSV/JSON   │ │ âm thanh,   │
└──┬─────┘ └──────┬──────┘ └───────────┘ └────────────┘ │ toast,      │
   │              │                                      │ Discord     │
┌──▼──────────────▼──────────────────────────┐          └─────────────┘
│ platform/: window (user32), input          │
│ (SendInput scan code), hotkeys (RegisterHotKey)
└────────────────────────────────────────────┘
```

| Module | Vai trò |
|---|---|
| `aotr_farm/config.py` | Cấu hình dạng dataclass ↔ `config/settings.json` (chịu được file hỏng/thiếu khóa) |
| `aotr_farm/engine.py` | **Máy trạng thái** farm, Pause/Resume tức thì, phát hiện lỗi, khôi phục, giới hạn thời gian |
| `aotr_farm/macro.py` | Trình chạy macro JSON (phím, chuột, chờ, click theo ảnh, if/repeat/call), kiểm tra cú pháp |
| `aotr_farm/vision.py` | Chụp vùng cửa sổ game (`mss`), so khớp template (OpenCV), tự scale theo kích thước cửa sổ |
| `aotr_farm/ocr.py` | Đọc số EXP/vàng ("1,250", "12.5K"...) bằng Tesseract (tùy chọn) |
| `aotr_farm/stats.py` | Thống kê từng lượt + cả phiên, EXP/giờ, vàng/giờ, xuất `data/run_history.csv` |
| `aotr_farm/notifier.py` | Thông báo: âm thanh, toast Windows (plyer), Discord webhook; chống spam |
| `aotr_farm/resources.py` | Đo CPU/RAM của tool và của Roblox |
| `aotr_farm/platform/` | `window.py` tìm/focus cửa sổ, `input.py` SendInput scan code, `hotkeys.py` phím tắt toàn cục |
| `aotr_farm/gui/` | Cửa sổ chính, công cụ khoanh vùng chụp template / vùng OCR |
| `config/macros/*.json` | Macro: chỉnh theo lối chơi của bạn, **không cần sửa code** |
| `templates/*.png` | Ảnh mẫu bạn tự chụp từ game để nhận diện màn hình/nút |

### Cách nhận biết trạng thái
Tool không biết gì về bên trong game, nên nó **nhìn** màn hình như bạn: nếu thấy ảnh
`reward_screen.png` thì lượt đã xong, thấy `disconnected_dialog.png` thì đã mất kết nối...
Bạn tự chụp các ảnh mẫu này trong tab **Công cụ** (vì giao diện game, độ phân giải và ngôn ngữ của
mỗi máy khác nhau).

* Không có template nào → **chế độ hẹn giờ**: mỗi lần chạy xong macro `mission_loop` được tính là một lượt.
* Có `reward_screen` → lặp `mission_loop` tới khi thấy màn hình thưởng, sau đó đọc phần thưởng
  rồi chạy `after_reward`.

### Phát hiện lỗi
| Lỗi | Cách phát hiện | Xử lý |
|---|---|---|
| Không thấy cửa sổ Roblox | `FindWindow` | Lúc Start: báo lỗi; khi đang chạy: chờ mở lại |
| Cửa sổ bị thu nhỏ / bị che | `IsIconic`, `GetForegroundWindow` | Tự focus lại, không được thì báo lỗi |
| Mất kết nối | template `disconnected_dialog` | Thông báo + macro `recover` |
| Kẹt | Không nhận diện được màn hình trong `stuck_timeout` | Thông báo + macro `recover` |
| Lượt quá lâu | `mission_timeout` | Thông báo + macro `recover` |
| Macro lỗi | Không thấy nút cần bấm, file JSON sai | Ghi log rõ dòng lỗi |
| Lỗi liên tiếp ≥ `max_consecutive_errors` | | **Dừng hẳn** + thông báo |

### Tối ưu CPU & RAM
* Chỉ chụp vùng client của cửa sổ Roblox, tái sử dụng đối tượng `mss`.
* So khớp ảnh xám (1 kênh), template được scale một lần rồi cache.
* Chụp **một** khung hình rồi thử mọi template (`find_any`), không chụp lại cho từng template.
* Chu kỳ quét chỉnh được (`detection_interval`); khi Pause, luồng engine **ngủ hẳn** (Event.wait), 0% CPU.
* Log trong RAM có giới hạn (hàng đợi 2000 bản ghi, ô log 1000 dòng, bảng 300 lượt); file log xoay vòng 2 MB × 5.
* GUI cập nhật 1 lần/giây; dùng tkinter có sẵn của Python (~40–60 MB RAM tổng).

---

## 2. Cài đặt (Windows 10/11)

### Cách dễ nhất: bản `.exe` (không cần cài Python)
1. Vào repo trên GitHub → tab **Actions** → chọn lần chạy **Build Windows EXE** mới nhất (dấu ✓ xanh).
2. Kéo xuống mục **Artifacts** → tải **AOTRFarm-windows** → giải nén.
3. Nháy đúp **`AOTRFarm.exe`**. Nếu Windows SmartScreen cảnh báo (vì file chưa được ký số):
   bấm *More info → Run anyway*.

Cấu hình, template, log và thống kê được lưu cạnh file `.exe`. Đặt nó trong một thư mục riêng,
ví dụ `C:\AOTRFarm`. Sau đó làm tiếp từ **mục 3**.

> Tự build: `pip install pyinstaller` → `python tools/build_onefile.py` →
> `pyinstaller --onefile --windowed --name AOTRFarm AOTRFarm.py` → file nằm ở `dist\AOTRFarm.exe`.

### Cách cài từ mã nguồn

### Bước 1: Cài Python
1. Tải **Python 3.10 trở lên** tại <https://www.python.org/downloads/windows/>.
2. Khi cài, **tích ô "Add python.exe to PATH"**, rồi bấm *Install Now*.
3. Mở *Command Prompt* và gõ `python --version` để kiểm tra.

### Bước 2: Tải công cụ
* Có Git: `git clone <địa chỉ repo này>`
* Không có Git: bấm **Code → Download ZIP** trên GitHub, rồi giải nén vào ví dụ `C:\AOTRFarm`.

### Bước 3: Cài thư viện
Nháy đúp **`install.bat`**. Script sẽ tạo môi trường ảo `.venv`, cài thư viện và chạy kiểm tra.

Hoặc làm thủ công:
```bat
cd C:\AOTRFarm
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m aotr_farm --check
```

### Bước 4 (tùy chọn): Cài Tesseract để đọc EXP/vàng
1. Tải bộ cài Windows tại <https://github.com/UB-Mannheim/tesseract/wiki>.
2. Cài vào thư mục mặc định `C:\Program Files\Tesseract-OCR\`.
3. Trong tab **Cài đặt**: bật *"Bật OCR"* và kiểm tra đường dẫn `tesseract.exe`.

Nếu không cài OCR, bạn vẫn có thể nhập *"EXP/Vàng mặc định mỗi lượt"* để thống kê ước lượng.

### Cách nhanh: bản MỘT FILE `AOTRFarm.py`
Không muốn tải cả thư mục? Chỉ cần file `AOTRFarm.py` (toàn bộ chương trình gộp lại):
```bat
pip install numpy opencv-python mss Pillow psutil
python AOTRFarm.py
```
Lần chạy đầu, chương trình tự tạo `config/`, macro mẫu, `templates/`, `logs/`, `data/` cạnh file.
Đây là chương trình Python chạy **ngoài** Roblox, **không** phải script Lua cho executor.
Sau khi sửa code trong `aotr_farm/`, tạo lại file bằng `python tools/build_onefile.py`.

### Bước 5: Chạy
* Nháy đúp **`run.bat`** (không hiện cửa sổ console), hoặc
* **`run_debug.bat`** (hiện console để xem lỗi), hoặc `python -m aotr_farm`.

---

## 3. Thiết lập lần đầu (khoảng 10 phút)

1. **Mở Roblox → AOTR**, đặt chế độ **cửa sổ** (không fullscreen), kích thước cố định
   (ví dụ 1280×720). Đừng đổi kích thước sau khi đã chụp template.
2. Tab **Công cụ → "Tìm cửa sổ Roblox"** để kiểm tra tool đã thấy game.
3. **Chụp template** (chọn tên → *"Chụp & khoanh vùng"* → kéo chuột quanh vùng → Enter), theo đúng thứ tự vào game:
   * Màn hình chọn nhân vật: `slot_a_card` = **cả thẻ Slot A** (từ chữ "SLOT A" xuống hết nút SELECT).
   * Popup "Join AoTR": `join_community_button` = nút xanh **Join Community**.
   * Menu chính: `lobby_play_button` = chữ **PLAY kèm một phần chữ CUSTOMIZATION** bên dưới
     (để không nhầm với ô PLAY trong lobby).
   * Sau khi bấm PLAY: `lobby_card` = **ô LOBBY** (không phải ô TRADE).
   * Trong lobby: `mission_play_button` = **ô PLAY lớn** (khung viền cam, dòng N/A phía trên).
   * Chọn chế độ: `missions_card` = **thẻ MISSIONS** (tiêu đề kèm phần trên của hình).
   * Chọn map: `forest_map` = **chỉ chữ FOREST** (không lấy dòng REWARD BOOST có đồng hồ).
   * Tạo phòng: `create_button` = nút **CREATE** (vàng).
   * Bắt đầu: `start_button` = nút **START** (vàng).
   * Trong trận: `mission_hud` (một phần HUD luôn hiện, ví dụ biểu tượng gas).
   * Màn hình thưởng: `reward_screen` (tiêu đề), `retry_button` hoặc `continue_button`.
   * (Nếu gặp) hộp thoại mất kết nối: `disconnected_dialog`, `reconnect_button`.
   * Vật phẩm: đặt tên `items/<tên vật phẩm>` để tool đếm số vật phẩm rơi.

   Luồng tự động: **chọn Slot A → Join Community (nếu popup hiện) → PLAY → LOBBY → PLAY trong lobby → MISSIONS → FOREST → CREATE → START → vào nhiệm vụ**.
   Bước chọn slot do macro `select_slot.json` làm; Các bước từ PLAY tới START do `start_mission.json` làm.
4. **Chọn vùng OCR** (nếu dùng): ở màn hình thưởng, chọn `exp` → *"Khoanh vùng OCR"* quanh con số;
   làm tương tự cho `gold`. Bấm *"Thử đọc OCR"* để kiểm tra.
5. **"Thử nhận diện trạng thái"**: điểm khớp nên ≥ ngưỡng (mặc định 0.82) ở đúng màn hình.
   Nếu thấp, hãy chụp lại vùng nhỏ hơn và đặc trưng hơn; nếu khớp nhầm thì tăng ngưỡng.
6. **Chỉnh macro** `config/macros/mission_loop.json` theo phím điều khiển và lối đánh của bạn (xem mục 4).
7. Tab **Điều khiển**: đặt giới hạn lượt/phút/giờ dừng → **Start** (hoặc F6).

### Phím tắt (hoạt động cả khi đang ở trong game)
| Phím | Chức năng |
|---|---|
| **F6** | Start / Stop |
| **F7** | Pause / Resume (nhả mọi phím đang giữ ngay lập tức) |
| **F8** | Dừng khẩn cấp |

---

## 4. Viết macro

Macro là file JSON trong `config/macros/`. Tool **tự nạp lại** khi bạn lưu file, kể cả lúc đang chạy.
Tọa độ `x`, `y` là **tương đối** (0..1) theo cửa sổ game, nên không phụ thuộc độ phân giải.

| action | Tham số | Ý nghĩa |
|---|---|---|
| `press` | `key`, `times`=1, `interval`=0.1, `hold`=0.05 | Nhấn phím |
| `key_down` / `key_up` | `key` | Giữ / nhả phím |
| `hold` | `key`, `seconds` | Giữ phím trong N giây |
| `wait` | `seconds`, `jitter` | Chờ (có dao động ngẫu nhiên) |
| `click` | `x`, `y` (tùy chọn), `button`, `times`, `interval` | Click chuột |
| `mouse_down` / `mouse_up` | `button` | Giữ / nhả chuột |
| `mouse_move_rel` | `dx`, `dy`, `steps`=10, `duration`=0.2 | Xoay camera |
| `scroll` | `amount` | Lăn chuột |
| `click_image` | `template`, `timeout`=10, `threshold`, `optional`, `offset_x/y` | Chờ ảnh xuất hiện rồi click vào |
| `wait_image` / `wait_image_gone` | `template`, `timeout`, `optional` | Chờ ảnh xuất hiện / biến mất |
| `if_image` | `template`, `then`: [...], `else`: [...] | Rẽ nhánh theo màn hình |
| `repeat` | `times`, `steps`: [...] | Lặp |
| `call` | `macro` | Gọi macro khác |
| `release_all` | | Nhả mọi phím |
| `log` | `message` | Ghi log |

Tên phím: `a`–`z`, `0`–`9`, `space`, `shift`, `ctrl`, `alt`, `tab`, `enter`, `esc`, `f1`–`f12`,
`up/down/left/right`... (xem `SCAN_CODES` trong `aotr_farm/platform/input.py`).

Ví dụ:
```json
{
  "name": "mission_loop",
  "steps": [
    {"action": "key_down", "key": "w"},
    {"action": "press", "key": "space", "times": 2, "interval": 0.25},
    {"action": "wait", "seconds": 1.2},
    {"action": "key_up", "key": "w"},
    {"action": "mouse_move_rel", "dx": 250, "dy": 0},
    {"action": "click", "times": 3, "interval": 0.35}
  ]
}
```

Macro đi kèm chỉ là **mẫu**; hãy chỉnh theo phím bạn đã gán trong game.

---

## 5. Thời gian chạy & thống kê

* **Số lượt tối đa**, **số phút tối đa**, **dừng lúc HH:MM**: đặt nhanh ở tab Điều khiển.
* **Nghỉ giải lao**: sau mỗi X phút thì nghỉ Y phút (tab Cài đặt → Thời gian chạy). Thời gian nghỉ và
  thời gian Pause không tính vào thời gian farm.
* Tab **Thống kê**: bảng từng lượt (thời gian, EXP, vàng, vật phẩm, lỗi), tổng vật phẩm.
* Dữ liệu lưu ở `data/run_history.csv` (mở bằng Excel) và `data/session_*.json` cho mỗi phiên.
* Log ở `logs/farm.log`.

## 6. Xử lý sự cố

| Vấn đề | Cách xử lý |
|---|---|
| Phím không vào game | Chạy Roblox ở chế độ cửa sổ; bật *"Tự focus cửa sổ"*. Nếu Roblox chạy bằng quyền Admin thì tool cũng phải chạy bằng quyền Admin. |
| Click lệch vị trí | Windows scale khác 100% vẫn được hỗ trợ (DPI aware); hãy chụp lại template sau khi đổi kích thước cửa sổ. |
| Không nhận ra màn hình | Dùng "Thử nhận diện", chụp vùng nhỏ và đặc trưng hơn, giảm ngưỡng còn khoảng 0.75. |
| Khớp nhầm | Tăng ngưỡng lên 0.88–0.92, chọn vùng ít thay đổi theo bối cảnh. |
| OCR đọc sai | Khoanh sát con số hơn; kiểm tra Tesseract đã cài. |
| CPU cao | Tăng *"Chu kỳ quét màn hình"* lên 1.0 s; giảm kích thước cửa sổ game. |

## 7. Phát triển

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```
Lõi (engine, macro, stats, config, vision) không phụ thuộc Windows. Test dùng cửa sổ/input/vision
giả trong `tests/conftest.py`.
