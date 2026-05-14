import sys
import subprocess
import importlib.util

# === TỰ ĐỘNG CÀI THƯ VIỆN (học từ webtoon.py) ===
REQUIRED_MODULES = ["flask", "werkzeug"]

def check_and_install_packages():
    missing = [m for m in REQUIRED_MODULES if importlib.util.find_spec(m) is None]
    if missing:
        print(f"Đang cài: {', '.join(missing)}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
        print("Cài xong!\n" + "-"*40)

check_and_install_packages()

import os, json, hashlib, time, logging, socket, traceback
from collections import deque
from functools import wraps
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from datetime import datetime
from flask import (Flask, render_template_string, request, redirect,
                   url_for, session, jsonify, abort, make_response)
from werkzeug.security import generate_password_hash, check_password_hash

# =====================================================================
#   HỆ THỐNG LOGGING NÂNG CAO
#   Ghi ra 3 file: shop_error.log | shop_access.log | shop_YYYY-MM.log
# =====================================================================

LOG_DIR      = "./logs"
MAX_BYTES    = 5 * 1024 * 1024   # 5 MB mỗi file → rotate
BACKUP_COUNT = 10                 # Giữ 10 file cũ
CONSOLE_LINES = 20

os.makedirs(LOG_DIR, exist_ok=True)

# --- Màu ANSI cho console ---
class C:
    R="\033[0m"; BOLD="\033[1m"; RED="\033[31m"; GREEN="\033[32m"
    YELLOW="\033[33m"; GRAY="\033[90m"; BG_RED="\033[41m"; WHITE="\033[37m"

_LEVEL_COLOR = {"DEBUG":C.GRAY,"INFO":C.GREEN,"WARNING":C.YELLOW,"ERROR":C.RED,"CRITICAL":C.BG_RED+C.WHITE}
_LEVEL_ICON  = {"DEBUG":"","INFO":"","WARNING":" ","ERROR":"","CRITICAL":""}

# --- Formatter console có màu ---
class ColorConsoleFormatter(logging.Formatter):
    def format(self, record):
        color = _LEVEL_COLOR.get(record.levelname, "")
        icon  = _LEVEL_ICON.get(record.levelname, "  ")
        ts    = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        name  = record.name[:14].ljust(14)
        line  = f"{C.GRAY}[{ts}]{C.R} {icon} {color}{C.BOLD}{record.levelname:<8}{C.R} {C.GRAY}{name}{C.R} {color}{record.getMessage()}{C.R}"
        if record.exc_info:
            tb = self.formatException(record.exc_info)
            line += f"\n{C.GRAY}{'─'*60}{C.R}\n{C.RED}{tb}{C.R}\n{C.GRAY}{'─'*60}{C.R}"
        return line

# --- Formatter file có cấu trúc rõ ràng ---
class FileFormatter(logging.Formatter):
    def format(self, record):
        ts  = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            f"[{ts}] {record.levelname} | {record.module}.{record.funcName}():{record.lineno}",
            f"MSG  : {record.getMessage()}",
        ]
        extras = {k: v for k, v in record.__dict__.items()
                  if k not in logging.LogRecord.__dict__ and
                     k not in ('msg','args','levelname','levelno','pathname','filename',
                               'module','exc_info','exc_text','stack_info','lineno',
                               'funcName','created','msecs','relativeCreated','thread',
                               'threadName','processName','process','name','message','taskName')}
        if extras:
            lines.append(f"DATA : {json.dumps(extras, ensure_ascii=False)}")
        if record.exc_info:
            lines.append("TRACE:")
            lines.append(self.formatException(record.exc_info))
        lines.append("─" * 60)
        return "\n".join(lines)

# --- Console handler: cuộn 20 dòng (học từ webtoon.py, nâng cấp) ---
class SmartConsoleHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.queue = deque(maxlen=CONSOLE_LINES)
        self.setFormatter(ColorConsoleFormatter())
    def emit(self, record):
        try:
            for line in self.format(record).split("\n"):
                self.queue.append(line)
            print("\033[2J\033[H", end="", flush=True)
            print("\n".join(self.queue), flush=True)
        except Exception:
            self.handleError(record)

# --- Tạo các handler file ---
def _make_error_handler():
    h = RotatingFileHandler(
        os.path.join(LOG_DIR, "shop_error.log"),
        maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    h.setLevel(logging.ERROR)
    h.setFormatter(FileFormatter())
    return h

def _make_access_handler():
    h = TimedRotatingFileHandler(
        os.path.join(LOG_DIR, "shop_access.log"),
        when="midnight", interval=1, backupCount=30, encoding="utf-8"
    )
    h.setLevel(logging.INFO)
    h.setFormatter(logging.Formatter("%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    h.suffix = "%Y-%m-%d"
    return h

def _make_monthly_handler():
    month = datetime.now().strftime("%Y-%m")
    h = RotatingFileHandler(
        os.path.join(LOG_DIR, f"shop_{month}.log"),
        maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    h.setLevel(logging.DEBUG)
    h.setFormatter(FileFormatter())
    return h

# --- Khởi tạo logger ---
_console_h  = SmartConsoleHandler()
_console_h.setLevel(logging.INFO)
_error_h    = _make_error_handler()
_access_h   = _make_access_handler()
_monthly_h  = _make_monthly_handler()

# Logger werkzeug (HTTP access)
_wz = logging.getLogger("werkzeug")
_wz.setLevel(logging.INFO)
_wz.handlers = []
_wz.addHandler(_console_h)
_wz.addHandler(_access_h)

# Logger chính
logger = logging.getLogger("urbanstore")
logger.setLevel(logging.DEBUG)
logger.handlers = []
logger.addHandler(_console_h)
logger.addHandler(_error_h)
logger.addHandler(_monthly_h)
logger.propagate = False

# --- Flask app ---
app = Flask(__name__)
app.logger.handlers = []
app.logger.addHandler(_console_h)
app.logger.addHandler(_error_h)
app.logger.addHandler(_monthly_h)
app.logger.setLevel(logging.DEBUG)
app.secret_key = 'shop_secret_key_2024'

# =====================================================================
#   DECORATOR & HOOK LOGGING
# =====================================================================

def catch_errors(f):
    """Bọc route, tự bắt exception và ghi vào error log + traceback."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            try:
                url  = request.url
                meth = request.method
                user = session.get("user", "guest")
            except Exception:
                url = meth = user = "N/A"
            logger.error(
                f"[{f.__name__}] {type(e).__name__}: {e}",
                exc_info=True,
                extra={"route": f.__name__, "url": url, "method": meth, "user": user}
            )
            raise
    return wrapper

@app.after_request
def _log_request(response):
    """Ghi mọi HTTP request vào access log."""
    try:
        status = response.status_code
        flag   = "OK " if status < 300 else ("RDR" if status < 400 else ("ERR" if status < 500 else "SRV"))
        user   = session.get("user", "-")
        size   = response.content_length or 0
        msg    = f"{flag} {status} | {request.method:<6} {request.path:<38} | {request.remote_addr:<15} | user={user:<12} | {size}B"
        if status >= 500:   logger.error(msg)
        elif status >= 400: logger.warning(msg)
        else:               logger.info(msg)
    except Exception:
        pass
    return response

@app.errorhandler(404)
def _err404(e):
    logger.warning(f"404 Not Found: {request.method} {request.path} | {request.remote_addr}")
    return f"<h2 style='font-family:sans-serif;padding:40px'>404 — Không tìm thấy trang</h2><p style='padding:0 40px'><a href='/'>← Về trang chủ</a></p>", 404

@app.errorhandler(500)
def _err500(e):
    logger.critical(f"500 Internal Server Error: {request.method} {request.path}", exc_info=True)
    return f"<h2 style='font-family:sans-serif;padding:40px'>500 — Lỗi máy chủ</h2><p style='padding:0 40px'><a href='/'>← Về trang chủ</a></p>", 500

# === CẤU HÌNH ===
DB_FILE     = "./shop_db.json"
ADMIN_USER  = "admin"
ADMIN_PASS  = "admin123"

# === DỮ LIỆU MẪU SẢN PHẨM — Arknights Chubby Lung (龙泡泡) ===
SAMPLE_PRODUCTS = [
    {
        "id": "p001",
        "name": "[Chính hãng] Thú bông Chubby Lung — Bộ 3 Nian · Chongyue · Dusk (龙泡泡毛绒玩偶 #17)",
        "price": 980000,
        "original_price": 1200000,
        "category": "thubong",
        "stock": 15,
        "sold": 213,
        "image": "",
        "img_file": "bean1_.webp",
        "desc": "Bộ 3 thú bông Chubby Lung tiêu chuẩn ra mắt lần đầu, gồm Nian (trắng - đỏ, biểu cảm tinh nghịch), Chongyue (xám đậm, chuỗi hạt gỗ đặc trưng + tua rua xám), và Dusk (xám xanh, móc đỏ mini). Vải bông mềm mịn cao cấp, nhân bông PP đàn hồi tốt, giữ form tròn đẹp. Chuẩn tag chính hãng CHOEARTH × Hypergryph. Kích thước ~20cm.",
        "tags": ["hot", "bán chạy"],
        "nhan_vat": "Nian · Chongyue · Dusk",
        "kich_thuoc": "~20cm",
        "thuong_hieu": "CHOEARTH / Hypergryph",
    },
    {
        "id": "p002",
        "name": "[Chính hãng CHOEARTH] Thú bông Chubby Lung — Shu (泰VER.) 龙泡泡毛绒玩偶",
        "price": 650000,
        "original_price": 780000,
        "category": "thubong",
        "stock": 18,
        "sold": 97,
        "image": "",
        "img_file": "bean2.webp",
        "desc": "Phiên bản Shu (Thục) — em út nhà Sui với tông màu trắng kem - vàng óng đặc trưng. Sừng gradient vàng - xanh tím cực kỳ đặc sắc, đuôi nơ xanh tím bồng bềnh phía sau. Gương mặt mang biểu cảm 'ngái ngủ' lười biếng đúng chất Shu. Chất vải Spandex mịn, bông PP cao cấp giữ form tròn hoàn hảo. Kích thước ~20cm — chuẩn chính hãng CHOEARTH 朝陇山.",
        "tags": ["mới", "hot"],
        "nhan_vat": "Shu (泰)",
        "kich_thuoc": "~20cm",
        "thuong_hieu": "CHOEARTH / Hypergryph",
    },
    {
        "id": "p003",
        "name": "[Chính hãng] CHOEARTH Ball — Bộ 4 Nian · Ling · Dusk · Chongyue (Dạng Cupcake)",
        "price": 1200000,
        "original_price": 1500000,
        "category": "thubong",
        "stock": 10,
        "sold": 154,
        "image": "",
        "img_file": "bean3.webp",
        "desc": "Dòng CHOEARTH Ball phiên bản Cupcake độc đáo — 4 anh chị em nhà Sui được thiết kế ngồi gọn trong ly cupcake thêu tên riêng. Nian (đỏ - trắng, nền cam rực), Ling (xanh dương, nền tím), Dusk (xám xanh teal, nền đen), Chongyue (xám đậm, chuỗi hạt + tua rua, nền đen cam). Mỗi nhân vật có biểu cảm mắt đặc trưng khác nhau. Set 4 món, đóng hộp đẹp — lý tưởng để trưng bày hoặc tặng quà.",
        "tags": ["hot", "bán chạy"],
        "nhan_vat": "Nian · Ling · Dusk · Chongyue",
        "kich_thuoc": "~12cm",
        "thuong_hieu": "CHOEARTH / Hypergryph",
    },
    {
        "id": "p004",
        "name": "[Chính hãng CHOEARTH 2023] Thú bông Chubby Lung — Chongyue (重岳VER.)",
        "price": 620000,
        "original_price": 750000,
        "category": "thubong",
        "stock": 22,
        "sold": 189,
        "image": "",
        "img_file": "bean4.webp",
        "desc": "Phiên bản Chongyue (Trọng Nhạc) tiêu chuẩn năm 2023 — tái hiện chính xác đại ca khắc nghiêm của nhà Sui. Thân tròn phủ lông nhung xám đậm cao cấp, đôi sừng vàng đất đặc trưng, ánh mắt đỏ cam rực lửa uy nghiêm. Điểm nhấn là chuỗi hạt đỏ - vàng thủ công kèm tua rua xám dài buông thướt — chi tiết không thể nhầm lẫn của Trọng Nhạc. Chân trắng mập mạp cực kỳ đáng yêu. Kích thước ~20cm.",
        "tags": ["bán chạy"],
        "nhan_vat": "Chongyue (重岳)",
        "kich_thuoc": "~20cm",
        "thuong_hieu": "CHOEARTH / Hypergryph",
    },
    {
        "id": "p005",
        "name": "[Chính hãng Bandai × Ichibansho] Thú bông Khổng Lồ Chubby Lung — Chongyue Big Plush",
        "price": 2800000,
        "original_price": 3500000,
        "category": "thubong",
        "stock": 5,
        "sold": 41,
        "image": "",
        "img_file": "bean6.jpg",
        "desc": "Phiên bản Chongyue KHỔNG LỒ — collab độc quyền Bandai Namco × Ichibansho, đủ lớn để ôm ngủ. Thân cầu xám khổng lồ với đôi sừng vàng to bản, chuỗi hạt đỏ - cam thủ công, tua rua xám dài. Đặc biệt: đuôi rồng dài quấn băng đỏ chi tiết cực kỳ ấn tượng, uốn lượn tự nhiên. Bông PP mật độ cao, giữ form vững, mềm mại ôm cực thích. Doctor nào cũng cần một chú Trọng Nhạc cỡ này trấn giữ căn phòng! Kích thước đầu ~35cm, tổng chiều dài ~80cm.",
        "tags": ["hot", "mới"],
        "nhan_vat": "Chongyue (重岳) — Big Plush",
        "kich_thuoc": "Đầu ~35cm | Tổng ~80cm",
        "thuong_hieu": "Bandai Namco × Ichibansho / Hypergryph",
    },
    {
        "id": "p006",
        "name": "[Chính hãng CHOEARTH] Gối Cổ Chữ U Chubby Lung — Nian (龙泡泡转转 生活之乐)",
        "price": 480000,
        "original_price": 580000,
        "category": "phukien",
        "stock": 25,
        "sold": 76,
        "image": "S/D",
        "img_file": "bean7.jpg",
        "desc": "Gối cổ chữ U phiên bản Nian (Niên) — thiết kế toàn thân rồng trắng đỏ uốn lượn ôm quanh cổ, đầu và đuôi Nian nhô ra hai bên cực kỳ ngộ nghĩnh. Gương mặt Nian với đốm đỏ trên trán và nụ cười tinh nghịch. Vải bông mềm mại, bông PP đàn hồi tốt, hỗ trợ cổ hiệu quả khi ngồi dài hoặc di chuyển. Ra mắt tại sự kiện Parade Party 朝陇山巡游派对. Lý tưởng cho hành trình dài hoặc làm gối ngủ bàn.",
        "tags": ["mới"],
        "nhan_vat": "Nian (年)",
        "kich_thuoc": "Vòng cổ tiêu chuẩn",
        "thuong_hieu": "CHOEARTH / Hypergryph",
    },
    {
        "id": "p007",
        "name": "[Chính hãng CHOEARTH] Móc Khóa Chạy 跑跑龙泡泡 — Dusk & Shu (Có Cơ Chế Dây Kéo)",
        "price": 280000,
        "original_price": 350000,
        "category": "mockey",
        "stock": 30,
        "sold": 132,
        "image": "",
        "img_file": "bean8.jpg",
        "desc": "Móc khóa 跑跑龙泡泡 (Run Run Bean) — dòng sản phẩm cực kỳ được yêu thích với cơ chế dây kéo độc đáo: kéo dây là chú rồng 'chạy' về phía trước! Bộ gồm Dusk (xám xanh teal, mắt cam bừng sáng) và Shu (trắng vàng, mắt xanh long lanh). Kích thước mini ~8-10cm, dễ thương cực kỳ. Kèm móc khóa bi bạc chắc chắn. Hoàn thiện thêu tay tỉ mỉ, biểu cảm sống động. Lý tưởng để treo ba lô, túi xách, chìa khóa xe.",
        "tags": ["hot", "bán chạy"],
        "nhan_vat": "Dusk · Shu",
        "kich_thuoc": "~8-10cm",
        "thuong_hieu": "CHOEARTH / Hypergryph",
    },
    {
        "id": "p008",
        "name": "[Chính hãng CHOEARTH] Móc Khóa Chạy 跑跑龙泡泡 — Bộ 3: Dusk · Ling · Nian",
        "price": 720000,
        "original_price": 900000,
        "category": "mockey",
        "stock": 20,
        "sold": 98,
        "image": "",
        "img_file": "bean9.webp",
        "desc": "Bộ 3 móc khóa 跑跑龙泡泡 đầy đủ nhất — Dusk (xám, mắt cam dữ dội), Ling (trắng xanh, mắt tím to tròn say sưa) và Nian (trắng đỏ, mắt híp cười rạng rỡ). Mỗi nhân vật có biểu cảm khác nhau hoàn toàn. Cơ chế kéo dây cực vui: chú rồng lao về phía trước khi kéo. Vải bông mềm mịn, thêu mắt sắc nét, dây kéo bền. Mua bộ 3 tiết kiệm hơn mua lẻ. Đi kèm túi đựng nhỏ.",
        "tags": ["hot", "sale"],
        "nhan_vat": "Dusk · Ling · Nian",
        "kich_thuoc": "~8-10cm mỗi con",
        "thuong_hieu": "CHOEARTH / Hypergryph",
    },
    {
        "id": "p009",
        "name": "[Chính hãng CHOEARTH 2026] Thú bông Chubby Lung — Chongyue (望VER.) Arknights 2026",
        "price": 680000,
        "original_price": 820000,
        "category": "thubong",
        "stock": 12,
        "sold": 55,
        "image": "",
        "img_file": "bean10.webp",
        "desc": "Phiên bản Chongyue 望VER. đặc biệt năm 2026 — màu sắc hoàn toàn mới với tông xám trắng nhạt thanh lịch, đôi sừng xám vàng đất kết hợp tinh tế. Chuỗi hạt đen - trắng thay thế cho bản cũ, tua rua xám nhẹ nhàng hơn. Đôi cánh nhỏ xám hai bên mang nét uy nghiêm mới lạ. Chân hồng phấn đáng yêu bất ngờ. Gương mặt 'vô tri' với miệng há to hình chữ U đặc trưng — xả stress cực đỉnh. Bản giới hạn Arknights 2026.",
        "tags": ["mới", "hot"],
        "nhan_vat": "Chongyue (望VER.)",
        "kich_thuoc": "~20-25cm",
        "thuong_hieu": "CHOEARTH 朝陇山 / Hypergryph",
    },
    {
        "id": "p010",
        "name": "[Chính hãng CHOEARTH 2026] Móc Khóa 小笼'泡' — Bộ 7 Nhân Vật Đầy Đủ (Hộp Dim Sum)",
        "price": 1500000,
        "original_price": 1900000,
        "category": "mockey",
        "stock": 8,
        "sold": 67,
        "image": "",
        "img_file": "bean11.webp",
        "desc": "Bộ sưu tập móc khóa 小笼'泡' 2026 đầy đủ nhất từ trước đến nay — 7 nhân vật: Chongyue望 · Chongyue重岳 · Ling · Shu · Yu · Nian · Dusk, mỗi nhân vật mang trang phục trắng tinh khôi phong cách dim sum cực kỳ dễ thương. Đóng trong hộp thiếc hình xửng hấp dim sum 朝陇山 độc đáo — vừa chơi vừa trưng bày. Kích thước mini ~6-8cm mỗi con, hoàn thiện thêu sắc nét. Bản giới hạn 2026, Doctor đừng bỏ lỡ!",
        "tags": ["mới", "hot", "bán chạy"],
        "nhan_vat": "Chongyue望·重岳 · Ling · Shu · Yu · Nian · Dusk",
        "kich_thuoc": "~6-8cm mỗi con | Hộp đóng gói đặc biệt",
        "thuong_hieu": "CHOEARTH 朝陇山 / Hypergryph",
    },
    {
        "id": "p011",
        "name": "[Chính hãng CHOEARTH 2024] Gối Ôm Dài Chubby Lung — Nian 'Dài Thượt' (那么长龙泡泡)",
        "price": 890000,
        "original_price": 1100000,
        "category": "phukien",
        "stock": 10,
        "sold": 88,
        "image": "",
        "img_file": "bean12.webp",
        "desc": "Gối ôm dài phiên bản Nian 2024 — có đến 2 size để Doctor lựa chọn: '那么长龙泡泡' (Dài thượt ~100cm) và '没那么长龙泡泡' (Vừa phải ~60cm). Thiết kế toàn thân rồng Nian trắng đỏ trải dài, họa tiết vảy rồng đỏ thêu nổi đặc sắc ở thân giữa, đầu và đuôi cong vút hai bên. Gương mặt Nian mắt lim dim nghịch ngợm. Bông PP mật độ cao êm ái, vải bông mềm mịn không gây kích ứng da. Vừa làm gối ôm ngủ, vừa trang trí sofa siêu cute.",
        "tags": ["mới", "bán chạy"],
        "nhan_vat": "Nian (年)",
        "kich_thuoc": "Size lớn ~100cm | Size nhỏ ~60cm",
        "thuong_hieu": "CHOEARTH / Hypergryph",
    },
]

CATEGORIES = {
    "all":      "Tất cả",
    "thubong":  " Thú Bông",
    "mockey":   " Móc Khóa",
    "phukien":  " Phụ Kiện",
}

# === DATABASE (học từ webtoon.py) ===
def load_db():
    if not os.path.exists(DB_FILE):
        return {"users": {}, "orders": [], "products": SAMPLE_PRODUCTS}
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"JSONDecodeError khi đọc DB: {e}", exc_info=True, extra={"file": DB_FILE})
        return {"users": {}, "orders": [], "products": SAMPLE_PRODUCTS}
    except Exception as e:
        logger.error(f"Lỗi đọc DB: {e}", exc_info=True, extra={"file": DB_FILE})
        return {"users": {}, "orders": [], "products": SAMPLE_PRODUCTS}

def save_db(data):
    try:
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except PermissionError as e:
        logger.error(f"Không có quyền ghi DB: {e}", exc_info=True, extra={"file": DB_FILE})
    except Exception as e:
        logger.error(f"Lỗi lưu DB: {e}", exc_info=True, extra={"file": DB_FILE})

def get_products():
    db = load_db()
    return db.get("products", SAMPLE_PRODUCTS)

def get_product(pid):
    return next((p for p in get_products() if p["id"] == pid), None)

# === DECORATOR (học từ webtoon.py) ===
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user'):
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('is_admin'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated

# === FORMAT TIỀN ===
def fmt(n):
    return f"{int(n):,}đ".replace(",", ".")

# =====================================================================
#   CSS & HTML TEMPLATES
# =====================================================================

BASE_STYLE = """
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#f7f7f5; --bg2:#ffffff; --bg3:#f0eeeb; --bg4:#e8e5e0;
  --text:#1a1a1a; --text2:#555; --text3:#999;
  --accent:#e85d26; --accent2:#ff7a42;
  --border:#e0ddd8; --border2:#ccc9c3;
  --success:#16a34a; --danger:#dc2626; --info:#2563eb;
  --radius:12px; --radius-sm:8px; --radius-lg:20px;
  --shadow:0 4px 24px rgba(0,0,0,.08);
}
body.dark{
  --bg:#0a0a0a; --bg2:#111; --bg3:#1a1a1a; --bg4:#222;
  --text:#f0f0f0; --text2:#aaa; --text3:#666;
  --border:#2a2a2a; --border2:#333;
  --success:#22c55e; --danger:#ef4444; --info:#3b82f6;
  --shadow:0 4px 24px rgba(0,0,0,.5);
}
body.dark .nav{background:rgba(10,10,10,.95)}
body.dark .hero{background:linear-gradient(135deg,#111 0%,#1a1a1a 100%)}
body.dark .auth-card{background:var(--bg2)}

/* THEME TOGGLE SWITCH */
.theme-toggle{position:relative;width:64px;height:32px;flex-shrink:0;cursor:pointer}
.theme-toggle input{opacity:0;width:0;height:0;position:absolute}
.theme-track{position:absolute;inset:0;border-radius:999px;background:#1a1a1a;transition:background .3s;display:flex;align-items:center;justify-content:space-between;padding:0 8px}
.theme-track .t-icon{font-size:13px;line-height:1;user-select:none;transition:opacity .3s}
.theme-track .t-moon{opacity:1;color:#fff}
.theme-track .t-sun{opacity:0.4;color:#fff}
.theme-thumb{position:absolute;top:3px;left:3px;width:26px;height:26px;border-radius:50%;background:#fff;box-shadow:0 1px 4px rgba(0,0,0,.3);transition:transform .3s cubic-bezier(.4,0,.2,1)}
body.dark .theme-track{background:#333}
body.dark .theme-track .t-moon{opacity:.4}
body.dark .theme-track .t-sun{opacity:1}
body.dark .theme-thumb{transform:translateX(32px);background:#fff}
body{background:var(--bg);color:var(--text);font-family:'Be Vietnam Pro',sans-serif;min-height:100vh;overflow-x:hidden}
a{color:inherit;text-decoration:none}
img{display:block}

/* SCROLLBAR */
::-webkit-scrollbar{width:6px}
::-webkit-scrollbar-track{background:var(--bg3)}
::-webkit-scrollbar-thumb{background:var(--border2);border-radius:3px}

/* NAV */
.nav{position:sticky;top:0;z-index:100;background:rgba(255,255,255,.95);backdrop-filter:blur(12px);border-bottom:1px solid var(--border);padding:0 max(20px,calc((100vw - 1200px)/2));display:flex;align-items:center;gap:16px;height:60px;box-shadow:0 1px 8px rgba(0,0,0,.06)}
.nav-brand{font-size:20px;font-weight:700;color:var(--accent);letter-spacing:-0.5px;white-space:nowrap}
.nav-brand span{color:var(--text)}
.nav-links{display:flex;gap:4px;margin-left:16px}
.nav-links a{padding:6px 14px;border-radius:var(--radius-sm);font-size:14px;color:var(--text2);transition:all .2s}
.nav-links a:hover,.nav-links a.active{color:var(--text);background:var(--bg3)}
.nav-right{margin-left:auto;display:flex;align-items:center;gap:10px}
.nav-search{background:var(--bg3);border:1px solid var(--border2);border-radius:var(--radius-sm);padding:8px 14px;color:var(--text);font-size:14px;width:200px;outline:none;transition:all .2s;font-family:inherit}
.nav-search:focus{border-color:var(--accent);width:260px}
.nav-search::placeholder{color:var(--text3)}
.cart-btn{position:relative;background:var(--accent);color:#fff;border:none;border-radius:var(--radius-sm);padding:8px 16px;font-size:14px;cursor:pointer;display:flex;align-items:center;gap:6px;font-family:inherit;font-weight:500;transition:all .2s}
.cart-btn:hover{background:var(--accent2);transform:translateY(-1px)}
.cart-badge{background:#fff;color:var(--accent);border-radius:50%;width:18px;height:18px;font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center;line-height:1}
.user-btn{background:var(--bg3);border:1px solid var(--border2);border-radius:var(--radius-sm);padding:8px 14px;font-size:14px;cursor:pointer;color:var(--text);font-family:inherit;transition:all .2s}
.user-btn:hover{background:var(--bg4)}

/* HERO */
.hero{background:linear-gradient(135deg,#fff8f5 0%,#fff3ee 100%);padding:80px max(20px,calc((100vw - 1200px)/2));display:flex;align-items:center;gap:60px;border-bottom:1px solid var(--border);min-height:420px;position:relative;overflow:hidden}
.hero-bg{position:absolute;inset:0;background-image:url('/imgs/nian.jpg');background-size:cover;background-position:center;opacity:0.08;pointer-events:none;z-index:0}
body.dark .hero-bg{opacity:0.05}
.hero::before{content:'';position:absolute;top:0;left:0;right:0;bottom:0;background:linear-gradient(135deg,rgba(255,248,245,.92) 0%,rgba(255,243,238,.85) 100%);pointer-events:none;z-index:0}
body.dark .hero::before{background:linear-gradient(135deg,rgba(17,17,17,.95) 0%,rgba(26,26,26,.92) 100%)}
.hero-content{flex:1;z-index:1}
.hero-tag{display:inline-block;background:rgba(232,93,38,.1);color:var(--accent);border:1px solid rgba(232,93,38,.25);border-radius:999px;padding:4px 14px;font-size:12px;font-weight:600;letter-spacing:1px;text-transform:uppercase;margin-bottom:20px}
.hero-title{font-size:clamp(32px,5vw,56px);font-weight:700;line-height:1.1;letter-spacing:-1px;margin-bottom:16px;color:var(--text)}
.hero-title span{color:var(--accent)}
.hero-desc{color:var(--text2);font-size:16px;line-height:1.7;max-width:480px;margin-bottom:32px}
.hero-actions{display:flex;gap:12px;flex-wrap:wrap}
.btn-primary{background:var(--accent);color:#fff;border:none;border-radius:var(--radius-sm);padding:14px 28px;font-size:15px;font-weight:600;cursor:pointer;font-family:inherit;transition:all .2s;display:inline-flex;align-items:center;gap:8px}
.btn-primary:hover{background:var(--accent2);transform:translateY(-2px);box-shadow:0 8px 24px rgba(232,93,38,.25)}
.btn-secondary{background:transparent;color:var(--text);border:1px solid var(--border2);border-radius:var(--radius-sm);padding:14px 28px;font-size:15px;font-weight:500;cursor:pointer;font-family:inherit;transition:all .2s}
.btn-secondary:hover{background:var(--bg3)}
.hero-stats{display:flex;gap:40px;margin-top:40px}
.hero-stat{text-align:center}
.hero-stat-num{font-size:28px;font-weight:700;color:var(--accent)}
.hero-stat-label{font-size:12px;color:var(--text3);margin-top:2px}
.hero-visual{flex-shrink:0;width:340px;height:340px;background:var(--bg3);border-radius:var(--radius-lg);overflow:hidden;display:flex;align-items:center;justify-content:center;border:1px solid var(--border)}
.hero-visual img{width:100%;height:100%;object-fit:cover}
@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-12px)}}

/* SECTION */
.section{padding:60px max(20px,calc((100vw - 1200px)/2))}
.section-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:32px}
.section-title{font-size:24px;font-weight:700;letter-spacing:-0.5px}
.section-title span{color:var(--accent)}
.see-all{color:var(--accent);font-size:14px;font-weight:500;transition:gap .2s;display:flex;align-items:center;gap:4px}
.see-all:hover{gap:8px}

/* CATEGORY TABS */
.cat-tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:28px}
.cat-tab{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius-sm);padding:8px 18px;font-size:14px;color:var(--text2);cursor:pointer;transition:all .2s;font-family:inherit}
.cat-tab:hover,.cat-tab.active{background:var(--accent);color:#fff;border-color:var(--accent)}

/* PRODUCT GRID */
.product-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:20px}
.product-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;transition:all .25s;cursor:pointer;position:relative}
.product-card:hover{border-color:var(--accent);transform:translateY(-4px);box-shadow:0 8px 32px rgba(232,93,38,.12)}
.product-card:hover .card-overlay{opacity:1}
.card-img{height:220px;display:flex;align-items:center;justify-content:center;background:var(--bg3);position:relative;overflow:hidden}
.card-img img{width:100%;height:100%;object-fit:cover;transition:transform .3s}
.product-card:hover .card-img img{transform:scale(1.05)}
.card-overlay{position:absolute;inset:0;background:rgba(0,0,0,.35);display:flex;align-items:center;justify-content:center;gap:8px;opacity:0;transition:opacity .2s}
.card-overlay button{background:var(--accent);color:#fff;border:none;border-radius:var(--radius-sm);padding:10px 20px;font-size:13px;cursor:pointer;font-family:inherit;font-weight:600;transition:all .2s}
.card-overlay button:hover{background:var(--accent2);transform:scale(1.05)}
.card-body{padding:16px}
.card-tags{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}
.tag{font-size:11px;font-weight:600;padding:2px 8px;border-radius:4px;text-transform:uppercase;letter-spacing:.5px}
.tag-new{background:rgba(37,99,235,.08);color:#2563eb;border:1px solid rgba(37,99,235,.15)}
.tag-hot{background:rgba(232,93,38,.08);color:var(--accent);border:1px solid rgba(232,93,38,.15)}
.tag-sale{background:rgba(22,163,74,.08);color:#16a34a;border:1px solid rgba(22,163,74,.15)}
.tag-best{background:rgba(147,51,234,.08);color:#7c3aed;border:1px solid rgba(147,51,234,.15)}
.card-name{font-size:14px;font-weight:600;margin-bottom:8px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;line-height:1.4;color:var(--text)}
.card-price{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.price-current{font-size:18px;font-weight:700;color:var(--accent)}
.price-old{font-size:13px;color:var(--text3);text-decoration:line-through}
.price-discount{font-size:11px;background:rgba(22,163,74,.1);color:#16a34a;padding:2px 6px;border-radius:4px;font-weight:600}
.card-meta{display:flex;justify-content:space-between;margin-top:10px;font-size:12px;color:var(--text3)}
.card-stock{color:var(--success)}

/* PRODUCT DETAIL */
.detail-layout{display:grid;grid-template-columns:1fr 1fr;gap:60px;align-items:start}
.detail-img{background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius-lg);height:460px;display:flex;align-items:center;justify-content:center;position:sticky;top:80px;overflow:hidden}
.detail-img img{width:100%;height:100%;object-fit:contain;padding:12px}
.detail-name{font-size:28px;font-weight:700;letter-spacing:-0.5px;margin-bottom:12px;line-height:1.3;color:var(--text)}
.detail-price{font-size:36px;font-weight:700;color:var(--accent);margin:16px 0}
.detail-price-old{font-size:18px;color:var(--text3);text-decoration:line-through;margin-left:12px}
.detail-desc{color:var(--text2);font-size:15px;line-height:1.7;margin-bottom:24px;padding:20px;background:var(--bg3);border-radius:var(--radius-sm);border:1px solid var(--border)}
.detail-qty{display:flex;align-items:center;gap:12px;margin-bottom:20px}
.qty-btn{background:var(--bg3);border:1px solid var(--border2);color:var(--text);width:36px;height:36px;border-radius:var(--radius-sm);cursor:pointer;font-size:18px;display:flex;align-items:center;justify-content:center;font-family:inherit;transition:all .2s}
.qty-btn:hover{background:var(--bg4)}
.qty-input{background:var(--bg3);border:1px solid var(--border2);color:var(--text);width:60px;height:36px;text-align:center;font-size:15px;border-radius:var(--radius-sm);font-family:inherit;outline:none}
.add-cart-btn{background:var(--accent);color:#fff;border:none;border-radius:var(--radius-sm);padding:16px 36px;font-size:16px;font-weight:600;cursor:pointer;font-family:inherit;transition:all .2s;display:flex;align-items:center;gap:8px;width:100%;justify-content:center}
.add-cart-btn:hover{background:var(--accent2);transform:translateY(-2px);box-shadow:0 8px 24px rgba(232,93,38,.25)}
.detail-meta{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:24px}
.meta-item{background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius-sm);padding:12px;text-align:center}
.meta-item-label{font-size:11px;color:var(--text3);text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px}
.meta-item-value{font-size:15px;font-weight:600;color:var(--text)}

/* CART */
.cart-layout{display:grid;grid-template-columns:1fr 380px;gap:32px;align-items:start}
.cart-item{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:16px;display:flex;align-items:center;gap:16px;margin-bottom:12px;transition:all .2s}
.cart-item:hover{border-color:var(--border2);box-shadow:var(--shadow)}
.cart-item-img{min-width:80px;width:80px;height:80px;background:var(--bg3);border-radius:var(--radius-sm);overflow:hidden;border:1px solid var(--border);flex-shrink:0}
.cart-item-img img{width:100%;height:100%;object-fit:cover}
.cart-item-img-fallback{width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:32px}
.cart-item-info{flex:1;min-width:0}
.cart-item-name{font-weight:600;margin-bottom:4px;font-size:14px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cart-item-price{color:var(--accent);font-weight:700;font-size:15px}
.cart-item-remove{background:none;border:none;color:var(--text3);cursor:pointer;font-size:20px;padding:4px;line-height:1;transition:color .2s;flex-shrink:0}
.cart-item-remove:hover{color:var(--danger)}
.order-summary{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:24px;position:sticky;top:80px;box-shadow:var(--shadow)}
.order-summary h3{font-size:18px;font-weight:700;margin-bottom:20px;padding-bottom:16px;border-bottom:1px solid var(--border);color:var(--text)}
.summary-row{display:flex;justify-content:space-between;margin-bottom:12px;font-size:14px;color:var(--text2)}
.summary-total{display:flex;justify-content:space-between;font-size:18px;font-weight:700;padding-top:16px;border-top:1px solid var(--border);margin-top:12px;color:var(--text)}
.summary-total span:last-child{color:var(--accent)}
.checkout-btn{background:var(--accent);color:#fff;border:none;border-radius:var(--radius-sm);padding:16px;font-size:15px;font-weight:600;cursor:pointer;font-family:inherit;width:100%;margin-top:20px;transition:all .2s}
.checkout-btn:hover{background:var(--accent2);transform:translateY(-1px)}
.empty-cart{text-align:center;padding:80px 20px}
.empty-cart-icon{font-size:60px;margin-bottom:20px;opacity:.3}
.empty-cart h3{font-size:22px;font-weight:600;margin-bottom:8px;color:var(--text)}
.empty-cart p{color:var(--text2);margin-bottom:24px}

/* CHECKOUT */
.checkout-layout{display:grid;grid-template-columns:1fr 360px;gap:32px;align-items:start}
.form-group{margin-bottom:20px}
.form-label{display:block;font-size:14px;font-weight:500;margin-bottom:8px;color:var(--text2)}
.form-input{width:100%;background:var(--bg2);border:1px solid var(--border2);border-radius:var(--radius-sm);padding:12px 16px;color:var(--text);font-size:15px;font-family:inherit;outline:none;transition:border-color .2s}
.form-input:focus{border-color:var(--accent)}
.form-row{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.form-section{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:24px;margin-bottom:24px;box-shadow:var(--shadow)}
.form-section h3{font-size:17px;font-weight:600;margin-bottom:20px;display:flex;align-items:center;gap:8px;color:var(--text)}
.payment-methods{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:8px}
.payment-method{background:var(--bg3);border:2px solid var(--border);border-radius:var(--radius-sm);padding:14px;text-align:center;cursor:pointer;transition:all .2s}
.payment-method.active{border-color:var(--accent);background:rgba(232,93,38,.05)}
.payment-method input{display:none}
.payment-method-icon{font-size:24px;margin-bottom:6px;display:block}
.payment-method-name{font-size:12px;font-weight:500;color:var(--text)}
.place-order-btn{background:var(--accent);color:#fff;border:none;border-radius:var(--radius-sm);padding:18px;font-size:16px;font-weight:700;cursor:pointer;font-family:inherit;width:100%;transition:all .2s}
.place-order-btn:hover{background:var(--accent2)}

/* ORDER */
.order-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:20px;margin-bottom:12px;box-shadow:var(--shadow)}
.order-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;padding-bottom:14px;border-bottom:1px solid var(--border)}
.order-id{font-weight:600;font-size:14px;color:var(--text)}
.order-status{font-size:12px;font-weight:600;padding:4px 10px;border-radius:999px}
.status-pending{background:rgba(37,99,235,.1);color:#2563eb}
.status-processing{background:rgba(234,179,8,.1);color:#b45309}
.status-shipped{background:rgba(147,51,234,.1);color:#7c3aed}
.status-done{background:rgba(22,163,74,.1);color:#16a34a}
.order-items-preview{display:flex;gap:8px;flex-wrap:wrap}
.order-item-chip{background:var(--bg3);border-radius:var(--radius-sm);padding:4px 10px;font-size:13px;color:var(--text2)}

/* AUTH */
.auth-page{min-height:100vh;display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#fff8f5 0%,#f7f7f5 100%);padding:20px}
.auth-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius-lg);padding:40px;width:100%;max-width:420px;box-shadow:0 20px 60px rgba(0,0,0,.08)}
.auth-title{font-size:26px;font-weight:700;margin-bottom:6px;text-align:center;color:var(--text)}
.auth-sub{color:var(--text3);font-size:14px;text-align:center;margin-bottom:32px}
.auth-btn{background:var(--accent);color:#fff;border:none;border-radius:var(--radius-sm);padding:14px;font-size:15px;font-weight:600;cursor:pointer;font-family:inherit;width:100%;transition:all .2s;margin-top:8px}
.auth-btn:hover{background:var(--accent2)}
.auth-link{text-align:center;margin-top:20px;font-size:14px;color:var(--text3)}
.auth-link a{color:var(--accent);font-weight:500}
.auth-divider{display:flex;align-items:center;gap:12px;margin:20px 0;color:var(--text3);font-size:13px}
.auth-divider::before,.auth-divider::after{content:'';flex:1;height:1px;background:var(--border)}

/* ADMIN */
.admin-layout{display:grid;grid-template-columns:240px 1fr;min-height:calc(100vh - 60px)}
.admin-sidebar{background:var(--bg2);border-right:1px solid var(--border);padding:24px 16px}
.admin-sidebar-title{font-size:12px;font-weight:600;color:var(--text3);text-transform:uppercase;letter-spacing:1px;margin-bottom:12px;padding:0 8px}
.admin-nav-item{display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:var(--radius-sm);color:var(--text2);font-size:14px;margin-bottom:2px;transition:all .2s;cursor:pointer}
.admin-nav-item:hover,.admin-nav-item.active{background:var(--bg3);color:var(--text)}
.admin-nav-item.active{color:var(--accent)}
.admin-content{padding:32px;background:var(--bg)}
.stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:32px}
.stat-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:20px;box-shadow:var(--shadow)}
.stat-icon{font-size:28px;margin-bottom:12px}
.stat-value{font-size:28px;font-weight:700;margin-bottom:4px;color:var(--text)}
.stat-label{font-size:13px;color:var(--text3)}
.stat-change{font-size:12px;color:var(--success);margin-top:4px}
.admin-table{width:100%;border-collapse:collapse}
.admin-table th{text-align:left;font-size:12px;font-weight:600;color:var(--text3);text-transform:uppercase;letter-spacing:.5px;padding:12px 16px;border-bottom:2px solid var(--border);background:var(--bg3)}
.admin-table td{padding:14px 16px;border-bottom:1px solid var(--border);font-size:14px;vertical-align:middle;color:var(--text)}
.admin-table tr:hover td{background:var(--bg3)}
.action-btn{background:var(--bg3);border:1px solid var(--border);color:var(--text);border-radius:var(--radius-sm);padding:5px 12px;font-size:12px;cursor:pointer;font-family:inherit;transition:all .2s;margin-right:4px}
.action-btn:hover{background:var(--bg4)}
.action-btn.danger{border-color:var(--danger);color:var(--danger)}
.action-btn.danger:hover{background:rgba(220,38,38,.08)}
.table-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;box-shadow:var(--shadow)}
.table-header{padding:20px 24px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;background:var(--bg2)}
.table-header h3{font-size:17px;font-weight:600;color:var(--text)}

/* ALERT */
.alert{padding:14px 20px;border-radius:var(--radius-sm);margin-bottom:20px;font-size:14px;font-weight:500}
.alert-success{background:rgba(22,163,74,.08);color:#16a34a;border:1px solid rgba(22,163,74,.15)}
.alert-error{background:rgba(220,38,38,.08);color:#dc2626;border:1px solid rgba(220,38,38,.15)}
.alert-info{background:rgba(37,99,235,.08);color:#2563eb;border:1px solid rgba(37,99,235,.15)}

/* SUCCESS PAGE */
.success-page{text-align:center;padding:80px 20px}
.success-icon{font-size:80px;margin-bottom:24px;animation:pop .5s ease}
@keyframes pop{0%{transform:scale(0)}80%{transform:scale(1.1)}100%{transform:scale(1)}}

/* TOAST */
.toast-container{position:fixed;bottom:24px;right:24px;z-index:9999;display:flex;flex-direction:column;gap:8px}
.toast{background:var(--bg2);border:1px solid var(--border2);border-radius:var(--radius-sm);padding:14px 20px;font-size:14px;font-weight:500;box-shadow:0 4px 20px rgba(0,0,0,.12);animation:slideIn .3s ease;min-width:260px;color:var(--text)}
.toast-success{border-left:3px solid var(--success)}
.toast-error{border-left:3px solid var(--danger)}
@keyframes slideIn{from{transform:translateX(100%);opacity:0}to{transform:translateX(0);opacity:1}}
@keyframes fadeOut{to{transform:translateX(100%);opacity:0}}

/* RESPONSIVE */
@media(max-width:900px){
  .detail-layout,.cart-layout,.checkout-layout{grid-template-columns:1fr}
  .detail-img{position:static}
  .order-summary{position:static}
  .hero{flex-direction:column;padding:40px 20px;gap:32px}
  .hero-visual{width:100%;height:240px}
  .stats-grid{grid-template-columns:1fr 1fr}
  .admin-layout{grid-template-columns:1fr}
  .admin-sidebar{display:none}
}
@media(max-width:600px){
  .nav-links{display:none}
  .nav-search{width:140px}
  .nav-search:focus{width:160px}
  .form-row{grid-template-columns:1fr}
  .payment-methods{grid-template-columns:repeat(3,1fr)}
}
</style>
"""

TOAST_JS = """
<div class="toast-container" id="toastContainer"></div>
<script>
function showToast(msg,type='success'){
  const t=document.getElementById('toastContainer');
  const d=document.createElement('div');
  d.className=`toast toast-${type}`;
  d.textContent=msg;
  t.appendChild(d);
  setTimeout(()=>{d.style.animation='fadeOut .3s ease forwards';setTimeout(()=>d.remove(),300)},3000);
}
function addToCart(pid,name,price,imgFile){
  fetch('/api/cart/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pid,name,price,imgFile,qty:1})})
  .then(r=>{
    if(r.status===401){
      showToast('Vui lòng đăng nhập để thêm vào giỏ hàng','error');
      setTimeout(()=>window.location='/login?next='+encodeURIComponent(window.location.pathname),1200);
      return null;
    }
    return r.json();
  })
  .then(data=>{
    if(!data) return;
    document.querySelectorAll('.cart-badge').forEach(b=>b.textContent=data.total_qty||0);
    showToast('Đã thêm vào giỏ hàng');
  })
  .catch(()=>showToast('Có lỗi xảy ra','error'));
}
function updateCartBadge(){
  fetch('/api/cart')
  .then(r=>r.status===401?[]:r.json())
  .then(cart=>{
    const total=Array.isArray(cart)?cart.reduce((s,x)=>s+x.qty,0):0;
    document.querySelectorAll('.cart-badge').forEach(b=>b.textContent=total||0);
  })
  .catch(()=>{});
}
document.addEventListener('DOMContentLoaded',updateCartBadge);
</script>
"""

def card_img_html(p):
    f = p.get("img_file", "")
    if f:
        return f'<img src="/imgs/{f}" alt="{p["name"]}" style="width:100%;height:100%;object-fit:cover;transition:transform .3s" loading="lazy">'
    return f'<div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;color:var(--text3);font-size:14px">No image</div>'

def nav(active='', user=None):
    u = session.get('user', '')
    is_admin = session.get('is_admin', False)
    user_html = f'<span style="font-size:13px;color:var(--text2)">Xin chào, <b style="color:var(--text)">{u}</b></span> <a href="/logout"><button class="user-btn">Đăng xuất</button></a>' if u else '<a href="/login"><button class="user-btn">Đăng nhập</button></a>'
    admin_link = '<a href="/admin" style="font-size:12px;color:var(--text3);padding:4px 8px;background:var(--bg3);border-radius:4px;margin-right:4px">Admin</a>' if is_admin else ''
    return f"""
<nav class="nav">
  <a href="/" class="nav-brand">CHUBBY<span>LUNG</span></a>
  <div class="nav-links">
    <a href="/" class="{'active' if active=='home' else ''}">Trang chủ</a>
    <a href="/products" class="{'active' if active=='products' else ''}">Sản phẩm</a>
    <a href="/orders" class="{'active' if active=='orders' else ''}">Đơn hàng</a>
  </div>
  <div class="nav-right">
    <input class="nav-search" placeholder="Tìm Chubby Lung..." id="searchInput" onkeypress="if(event.key==='Enter')window.location='/products?q='+this.value">
    {admin_link}
    {user_html}
    <label class="theme-toggle" title="Chuyen sang/toi">
      <input type="checkbox" id="themeCheck" onchange="toggleTheme(this)">
      <div class="theme-track">
        <span class="t-moon">&#9790;</span>
        <span class="t-sun">&#9728;</span>
      </div>
      <div class="theme-thumb"></div>
    </label>
    <a href="/cart"><button class="cart-btn">Giỏ hàng <span class="cart-badge">0</span></button></a>
  </div>
</nav>
<script>
(function(){{
  const dark = localStorage.getItem('theme') === 'dark';
  if(dark) document.body.classList.add('dark');
  const cb = document.getElementById('themeCheck');
  if(cb) cb.checked = dark;
}})();
function toggleTheme(cb){{
  const isDark = cb.checked;
  document.body.classList.toggle('dark', isDark);
  localStorage.setItem('theme', isDark ? 'dark' : 'light');
}}
</script>"""

# === SERVE ẢNH SẢN PHẨM ===
import mimetypes
from pathlib import Path

UPLOAD_DIRS = [
    "./imgs",
    "./images",
    "/mnt/user-data/uploads",
]

@app.route('/imgs/<filename>')
def serve_image(filename):
    for d in UPLOAD_DIRS:
        p = Path(d) / filename
        if p.exists():
            mime = mimetypes.guess_type(filename)[0] or 'image/jpeg'
            with open(p, 'rb') as f:
                data = f.read()
            from flask import Response
            return Response(data, mimetype=mime)
    abort(404)

# =====================================================================
#   ROUTES — NGƯỜI DÙNG
# =====================================================================

@app.route('/')
@catch_errors
def home():
    products = get_products()
    hot = [p for p in products if 'hot' in p.get('tags', [])][:4]
    new = [p for p in products if 'mới' in p.get('tags', [])][:4]

    def product_card(p):
        disc = round((1 - p['price']/p['original_price'])*100)
        tags_html = ''.join([
            f'<span class="tag tag-{"new" if t=="mới" else "hot" if t=="hot" else "sale" if t=="sale" else "best"}">{t}</span>'
            for t in p.get('tags', [])
        ])
        img = card_img_html(p)
        imgf = p.get('img_file','')
        name_safe = p['name'].replace("'","")
        return f'''
        <div class="product-card" onclick="window.location='/product/{p["id"]}'">
          <div class="card-img">{img}
            <div class="card-overlay">
              <button onclick="addToCart('{p["id"]}','{name_safe}',{p["price"]},'{imgf}');event.stopPropagation()">+ Giỏ hàng</button>
              <button onclick="window.location='/product/{p["id"]}'">Xem</button>
            </div>
          </div>
          <div class="card-body">
            <div class="card-tags">{tags_html}</div>
            <div class="card-name">{p["name"]}</div>
            <div class="card-price">
              <span class="price-current">{fmt(p["price"])}</span>
              <span class="price-old">{fmt(p["original_price"])}</span>
              <span class="price-discount">-{disc}%</span>
            </div>
            <div class="card-meta">
              <span>Đã bán {p["sold"]}</span>
              <span class="card-stock">Còn {p["stock"]}</span>
            </div>
          </div>
        </div>'''

    hot_html = ''.join(product_card(p) for p in hot)
    new_html = ''.join(product_card(p) for p in new)

    return render_template_string(f"""<!DOCTYPE html><html lang="vi"><head>{BASE_STYLE}<title>Chubby Lung Store</title></head><body>
{nav('home')}
<div class="hero">
  <div class="hero-bg"></div>
  <div class="hero-content">
    <div class="hero-tag">Chubby Lung — 龙泡泡毛绒玩偶</div>
    <h1 class="hero-title">Hàng chính hãng<br><span>CHOEARTH × Hypergryph</span></h1>
    <p class="hero-desc">Bộ sưu tập thú bông Chubby Lung chính hãng từ game Arknights — Nian, Dusk, Ling, Chongyue, Shu. Đủ dòng: tiêu chuẩn, khổng lồ, móc khóa, gối ôm.</p>
    <div class="hero-actions">
      <a href="/products"><button class="btn-primary">Mua ngay</button></a>
      <a href="/products?cat=mockey"><button class="btn-secondary">Xem móc khóa</button></a>
    </div>
    <div class="hero-stats">
      <div class="hero-stat"><div class="hero-stat-num">5</div><div class="hero-stat-label">Nhân vật Sui</div></div>
      <div class="hero-stat"><div class="hero-stat-num">11</div><div class="hero-stat-label">Dòng sản phẩm</div></div>
      <div class="hero-stat"><div class="hero-stat-num">100%</div><div class="hero-stat-label">Chính hãng</div></div>
    </div>
  </div>
  <div class="hero-visual" style="font-size:100px;display:flex;gap:8px;flex-wrap:wrap;max-width:280px;justify-content:center"></div>
</div>

<div class="section">
  <div class="section-header">
    <div class="section-title">Sản phẩm <span>nổi bật</span></div>
    <a href="/products" class="see-all">Xem tất cả →</a>
  </div>
  <div class="product-grid">{hot_html}</div>
</div>

<div style="background:var(--bg2);border-top:1px solid var(--border);border-bottom:1px solid var(--border)">
<div class="section">
  <div class="section-header">
    <div class="section-title">Hàng <span>mới về</span></div>
    <a href="/products?filter=new" class="see-all">Xem tất cả →</a>
  </div>
  <div class="product-grid">{new_html}</div>
</div>
</div>

<div class="section" style="text-align:center">
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:20px">
    <div style="background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:28px">
      <div style="font-size:36px;margin-bottom:12px"></div>
      <div style="font-weight:600;margin-bottom:6px">100% Chính Hãng</div>
      <div style="font-size:13px;color:var(--text3)">Tag CHOEARTH / Hypergryph đầy đủ</div>
    </div>
    <div style="background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:28px">
      <div style="font-size:36px;margin-bottom:12px"></div>
      <div style="font-weight:600;margin-bottom:6px">Giao hàng toàn quốc</div>
      <div style="font-size:13px;color:var(--text3)">2-5 ngày làm việc</div>
    </div>
    <div style="background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:28px">
      <div style="font-size:36px;margin-bottom:12px"></div>
      <div style="font-weight:600;margin-bottom:6px">Đổi trả 7 ngày</div>
      <div style="font-size:13px;color:var(--text3)">Lỗi sản phẩm hoàn tiền 100%</div>
    </div>
    <div style="background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:28px">
      <div style="font-size:36px;margin-bottom:12px"></div>
      <div style="font-weight:600;margin-bottom:6px">Hỗ trợ Doctor</div>
      <div style="font-size:13px;color:var(--text3)">Tư vấn sản phẩm nhiệt tình</div>
    </div>
  </div>
</div>
{TOAST_JS}
</body></html>""")


@app.route('/products')
@catch_errors
def products_page():
    q = request.args.get('q', '').strip().lower()
    cat = request.args.get('cat', 'all')
    sort = request.args.get('sort', 'default')
    all_prods = get_products()

    filtered = all_prods
    if q:
        filtered = [p for p in filtered if q in p['name'].lower() or q in p.get('desc','').lower()]
    if cat == 'sale':
        filtered = [p for p in filtered if 'sale' in p.get('tags', [])]
    elif cat == 'new' or cat == 'filter':
        filtered = [p for p in filtered if 'mới' in p.get('tags', [])]
    elif cat != 'all':
        filtered = [p for p in filtered if p.get('category') == cat]

    if sort == 'price_asc':   filtered = sorted(filtered, key=lambda x: x['price'])
    elif sort == 'price_desc': filtered = sorted(filtered, key=lambda x: x['price'], reverse=True)
    elif sort == 'popular':    filtered = sorted(filtered, key=lambda x: x['sold'], reverse=True)

    def card(p):
        disc = round((1 - p['price']/p['original_price'])*100)
        tags_html = ''.join([f'<span class="tag tag-{"new" if t=="mới" else "hot" if t=="hot" else "sale" if t=="sale" else "best"}">{t}</span>' for t in p.get('tags', [])])
        em = p.get('image','')
        img = card_img_html(p)
        return f'''
        <div class="product-card" onclick="window.location='/product/{p["id"]}'">
          <div class="card-img">{img}
            <div class="card-overlay">
              <button onclick="addToCart('{p["id"]}','{p["name"].replace("'","")}',{p["price"]},'{p.get("img_file","")}');event.stopPropagation()">+ Giỏ hàng</button>
              <button onclick="window.location='/product/{p["id"]}'">Xem chi tiết</button>
            </div>
          </div>
          <div class="card-body">
            <div class="card-tags">{tags_html}</div>
            <div class="card-name">{p["name"]}</div>
            <div class="card-price">
              <span class="price-current">{fmt(p["price"])}</span>
              <span class="price-old">{fmt(p["original_price"])}</span>
              <span class="price-discount">-{disc}%</span>
            </div>
            <div class="card-meta"><span>Đã bán {p["sold"]}</span><span class="card-stock">Còn {p["stock"]}</span></div>
          </div>
        </div>'''

    cat_tabs = ''.join([
        f'<button class="cat-tab {"active" if (cat==k or (cat=="filter" and k=="new")) else ""}" onclick="window.location=\'/products?cat={k}\'">{v}</button>'
        for k,v in CATEGORIES.items()
    ] + [f'<button class="cat-tab {"active" if cat=="sale" else ""}" onclick="window.location=\'/products?cat=sale\'">Sale</button>'])

    sort_select = f'''
    <select onchange="window.location='/products?cat={cat}&sort='+this.value" style="background:var(--bg3);border:1px solid var(--border2);color:var(--text);padding:8px 14px;border-radius:var(--radius-sm);font-family:inherit;font-size:14px;outline:none">
      <option value="default" {"selected" if sort=="default" else ""}>Mặc định</option>
      <option value="popular" {"selected" if sort=="popular" else ""}>Bán chạy</option>
      <option value="price_asc" {"selected" if sort=="price_asc" else ""}>Giá tăng dần</option>
      <option value="price_desc" {"selected" if sort=="price_desc" else ""}>Giá giảm dần</option>
    </select>'''

    result_html = ''.join(card(p) for p in filtered) if filtered else '<div style="text-align:center;padding:60px;color:var(--text3);font-size:16px;grid-column:1/-1">Không tìm thấy sản phẩm nào</div>'
    search_val = f'value="{q}"' if q else ''

    return render_template_string(f"""<!DOCTYPE html><html lang="vi"><head>{BASE_STYLE}<title>Sản phẩm - URBANSTORE</title></head><body>
{nav('products')}
<div class="section">
  <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;margin-bottom:20px">
    <h1 style="font-size:24px;font-weight:700">{"Kết quả tìm kiếm: <span style='color:var(--accent)'>"+q+"</span>" if q else "Tất cả sản phẩm"}</h1>
    <div style="display:flex;align-items:center;gap:12px">
      <span style="font-size:14px;color:var(--text3)">{len(filtered)} sản phẩm</span>
      {sort_select}
    </div>
  </div>
  <div style="margin-bottom:20px">
    <input class="nav-search" style="width:100%;max-width:400px" placeholder="Tìm sản phẩm..." {search_val} id="searchInput" onkeypress="if(event.key==='Enter')window.location='/products?q='+this.value">
  </div>
  <div class="cat-tabs">{cat_tabs}</div>
  <div class="product-grid">{result_html}</div>
</div>
{TOAST_JS}
</body></html>""")


@app.route('/product/<pid>')
@catch_errors
def product_detail(pid):
    p = get_product(pid)
    if not p: abort(404)
    disc = round((1 - p['price']/p['original_price'])*100)
    tags_html = ''.join([f'<span class="tag tag-{"new" if t=="mới" else "hot" if t=="hot" else "sale" if t=="sale" else "best"}">{t}</span>' for t in p.get('tags', [])])

    # Ảnh chi tiết
    f = p.get("img_file","")
    em = p.get("image","")
    detail_img_inner = f'<img src="/images/{f}" alt="{p["name"]}" style="width:100%;height:100%;object-fit:contain;padding:16px" onerror="this.outerHTML=\'<span style=font-size:100px>{em}</span>\'">' if f else f'<span style="font-size:100px">{em}</span>'

    # Thông số đặc biệt
    nhan_vat   = p.get("nhan_vat","—")
    kich_thuoc = p.get("kich_thuoc","—")
    thuong_hieu= p.get("thuong_hieu","CHOEARTH / Hypergryph")

    # Related products
    related = [x for x in get_products() if x['category'] == p['category'] and x['id'] != pid][:4]
    rel_html = ''.join([f'''
    <div class="product-card" onclick="window.location='/product/{r["id"]}'">
      <div class="card-img" style="height:160px">{card_img_html(r)}</div>
      <div class="card-body">
        <div class="card-name" style="font-size:13px">{r["name"]}</div>
        <div class="price-current" style="font-size:15px">{fmt(r["price"])}</div>
      </div>
    </div>''' for r in related])

    return render_template_string(f"""<!DOCTYPE html><html lang="vi"><head>{BASE_STYLE}<title>{p["name"]} - Arknights Store</title></head><body>
{nav()}
<div class="section">
  <div style="font-size:13px;color:var(--text3);margin-bottom:24px">
    <a href="/" style="color:var(--accent)">Trang chủ</a> /
    <a href="/products" style="color:var(--accent)">Sản phẩm</a> / {p["name"]}
  </div>
  <div class="detail-layout">
    <div class="detail-img">{detail_img_inner}</div>
    <div>
      <div class="card-tags" style="margin-bottom:12px">{tags_html}</div>
      <h1 class="detail-name">{p["name"]}</h1>
      <div style="display:flex;align-items:baseline;gap:8px;flex-wrap:wrap">
        <span class="detail-price">{fmt(p["price"])}</span>
        <span class="detail-price-old">{fmt(p["original_price"])}</span>
        <span class="price-discount" style="font-size:14px;padding:4px 10px">-{disc}%</span>
      </div>

      <div class="detail-meta" style="margin-top:20px">
        <div class="meta-item"><div class="meta-item-label">Nhân vật</div><div class="meta-item-value" style="font-size:13px">{nhan_vat}</div></div>
        <div class="meta-item"><div class="meta-item-label">Kích thước</div><div class="meta-item-value" style="font-size:13px">{kich_thuoc}</div></div>
        <div class="meta-item"><div class="meta-item-label">Đã bán</div><div class="meta-item-value">{p["sold"]}</div></div>
        <div class="meta-item"><div class="meta-item-label">Còn lại</div><div class="meta-item-value" style="color:var(--success)">{p["stock"]}</div></div>
      </div>

      <div class="detail-desc">{p["desc"]}</div>

      <div style="background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius-sm);padding:14px;margin-bottom:20px;font-size:13px;color:var(--text2)">
        <b style="color:var(--text)">Thương hiệu:</b> {thuong_hieu}<br>
        <b style="color:var(--text)">Danh mục:</b> {CATEGORIES.get(p["category"],"—")}<br>
        <b style="color:var(--text)">Tiết kiệm:</b> <span style="color:var(--success)">{fmt(p["original_price"]-p["price"])}</span>
      </div>

      <div class="detail-qty">
        <span style="font-size:14px;color:var(--text2)">Số lượng:</span>
        <button class="qty-btn" onclick="changeQty(-1)">−</button>
        <input class="qty-input" type="number" id="qty" value="1" min="1" max="{p["stock"]}">
        <button class="qty-btn" onclick="changeQty(1)">+</button>
      </div>
      <button class="add-cart-btn" onclick="buyNow('{p["id"]}','{p["name"].replace("'","")}',{p["price"]},'{p.get("img_file","")}'">
        Thêm vào giỏ hàng
      </button>
      <a href="/cart" id="goCartBtn" style="display:none">
        <button class="add-cart-btn" style="margin-top:10px;background:var(--bg3);color:var(--text);border:1px solid var(--border2)">→ Xem giỏ hàng</button>
      </a>
    </div>
  </div>
  {"<div style='margin-top:60px'><div class='section-header'><div class='section-title'>Sản phẩm <span>tương tự</span></div></div><div class='product-grid'>"+rel_html+"</div></div>" if rel_html else ""}
</div>
{TOAST_JS}
<script>
function changeQty(d){{
  const i=document.getElementById('qty');
  i.value=Math.max(1,Math.min({p["stock"]},parseInt(i.value||1)+d));
}}
function buyNow(pid,name,price,imgFile){{
  const qty=parseInt(document.getElementById('qty').value||1);
  fetch('/api/cart/add',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{pid,name,price,imgFile,qty}})}})
  .then(r=>{{
    if(r.status===401){{
      showToast('Vui lòng đăng nhập để thêm vào giỏ hàng','error');
      setTimeout(()=>window.location='/login?next=/product/{p["id"]}',1200);
      return null;
    }}
    return r.json();
  }})
  .then(data=>{{
    if(!data) return;
    document.querySelectorAll('.cart-badge').forEach(b=>b.textContent=data.total_qty||0);
    showToast('Đã thêm '+qty+' sản phẩm vào giỏ');
    document.getElementById('goCartBtn').style.display='block';
  }})
  .catch(()=>showToast('Có lỗi xảy ra','error'));
}}
</script>
</body></html>""")


@app.route('/cart')
def cart_page():
    return render_template_string(f"""<!DOCTYPE html><html lang="vi"><head>{BASE_STYLE}<title>Giỏ hàng - URBANSTORE</title></head><body>
{nav('cart')}
<div class="section">
  <h1 style="font-size:26px;font-weight:700;margin-bottom:28px">Giỏ hàng</h1>
  <div class="cart-layout" id="cartLayout">
    <div id="cartItems">
      <div class="empty-cart">
        
        <h3>Giỏ hàng trống</h3>
        <p>Bạn chưa có sản phẩm nào trong giỏ hàng</p>
        <a href="/products"><button class="btn-primary">Mua sắm ngay</button></a>
      </div>
    </div>
    <div id="orderSummary" style="display:none" class="order-summary">
      <h3>Tóm tắt đơn hàng</h3>
      <div class="summary-row"><span>Tạm tính</span><span id="subtotal">0đ</span></div>
      <div class="summary-row"><span>Phí ship</span><span style="color:var(--success)">Miễn phí</span></div>
      <div class="summary-row"><span>Giảm giá</span><span id="discountRow">0đ</span></div>
      <div class="summary-total"><span>Tổng cộng</span><span id="total">0đ</span></div>
      <a href="/checkout"><button class="checkout-btn">Thanh toán →</button></a>
      <div style="text-align:center;margin-top:14px;font-size:12px;color:var(--text3)">Thanh toán bảo mật SSL</div>
    </div>
  </div>
</div>
{TOAST_JS}
<script>
function fmt(n){{return new Intl.NumberFormat('vi-VN').format(n)+'đ'}}
function renderCart(){{
  fetch('/api/cart')
  .then(r=>{{
    if(r.status===401){{
      document.getElementById('cartItems').innerHTML=`<div class="empty-cart"><h3>Vui lòng đăng nhập</h3><p>Bạn cần đăng nhập để xem giỏ hàng</p><a href="/login?next=/cart"><button class="btn-primary">Đăng nhập</button></a></div>`;
      document.getElementById('orderSummary').style.display='none';
      return null;
    }}
    return r.json();
  }})
  .then(cart=>{{
    if(!cart) return;
    const itemsDiv=document.getElementById('cartItems');
    const summaryDiv=document.getElementById('orderSummary');
    if(!cart.length){{
      itemsDiv.innerHTML=`<div class="empty-cart"><h3>Giỏ hàng trống</h3><p>Bạn chưa có sản phẩm nào trong giỏ hàng</p><a href="/products"><button class="btn-primary">Mua sắm ngay</button></a></div>`;
      summaryDiv.style.display='none';return;
    }}
    let html='',total=0;
    cart.forEach((item,i)=>{{
      total+=item.price*item.qty;
      const imgHtml=item.imgFile?`<img src="/imgs/${{item.imgFile}}" style="width:100%;height:100%;object-fit:cover;border-radius:var(--radius-sm)" onerror="this.style.display='none'">`:'' ;
      html+=`<div class="cart-item">
        <div class="cart-item-img">${{imgHtml}}</div>
        <div class="cart-item-info">
          <div class="cart-item-name">${{item.name}}</div>
          <div class="cart-item-price">${{fmt(item.price)}}</div>
          <div style="display:flex;align-items:center;gap:8px;margin-top:8px">
            <button class="qty-btn" onclick="updateQty('${{item.pid}}',${{item.qty-1}})">−</button>
            <span style="font-weight:600">${{item.qty}}</span>
            <button class="qty-btn" onclick="updateQty('${{item.pid}}',${{item.qty+1}})">+</button>
            <span style="font-size:13px;color:var(--text3);margin-left:8px">= ${{fmt(item.price*item.qty)}}</span>
          </div>
        </div>
        <button class="cart-item-remove" onclick="removeItem('${{item.pid}}')">×</button>
      </div>`;
    }});
    itemsDiv.innerHTML=html;
    summaryDiv.style.display='block';
    document.getElementById('subtotal').textContent=fmt(total);
    document.getElementById('discountRow').textContent='-0đ';
    document.getElementById('total').textContent=fmt(total);
    document.querySelectorAll('.cart-badge').forEach(b=>b.textContent=cart.reduce((s,x)=>s+x.qty,0)||0);
  }})
  .catch(()=>showToast('Không thể tải giỏ hàng','error'));
}}
function updateQty(pid,qty){{
  if(qty<1) return;
  fetch('/api/cart/update',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{pid,qty}})}})
  .then(r=>r.json()).then(()=>renderCart());
}}
function removeItem(pid){{
  fetch('/api/cart/remove',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{pid}})}})
  .then(r=>r.json()).then(()=>{{renderCart();showToast('Đã xóa khỏi giỏ hàng','error');}});
}}
document.addEventListener('DOMContentLoaded',renderCart);
</script>
</body></html>""")


@app.route('/checkout', methods=['GET', 'POST'])
@catch_errors
def checkout():
    if not session.get('user'):
        return redirect('/login?next=/checkout')
    if request.method == 'POST':
        data = request.form
        u = session.get('user', 'guest')
        cart = get_user_cart(u)
        if not cart:
            # fallback: thử đọc từ form nếu có
            cart = json.loads(data.get('cart_json', '[]'))
        if not cart:
            return redirect('/cart')

        db = load_db()
        order_id = f"ORD{int(time.time()*1000) % 10000000:07d}"
        total = sum(item['price'] * item['qty'] for item in cart)

        order = {
            "id": order_id,
            "user": session.get('user', 'guest'),
            "name": data.get('fullname'),
            "phone": data.get('phone'),
            "address": f"{data.get('address')}, {data.get('district')}, {data.get('city')}",
            "payment": data.get('payment', 'cod'),
            "items": cart,
            "total": total,
            "status": "pending",
            "time": int(time.time())
        }
        db['orders'].append(order)
        save_db(db)
        # Xóa giỏ hàng sau khi đặt hàng thành công
        save_user_cart(u, [])
        return redirect(f'/order/success/{order_id}')

    return render_template_string(f"""<!DOCTYPE html><html lang="vi"><head>{BASE_STYLE}<title>Thanh toán - URBANSTORE</title></head><body>
{nav()}
<div class="section">
  <h1 style="font-size:26px;font-weight:700;margin-bottom:28px"> Thanh toán</h1>
  <form method="POST" id="checkoutForm">
    <input type="hidden" name="cart_json" id="cartJsonInput">
    <div class="checkout-layout">
      <div>
        <div class="form-section">
          <h3>Thông tin giao hàng</h3>
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">Họ và tên *</label>
              <input name="fullname" class="form-input" required placeholder="Nguyễn Văn A">
            </div>
            <div class="form-group">
              <label class="form-label">Số điện thoại *</label>
              <input name="phone" class="form-input" required placeholder="0901 234 567" type="tel">
            </div>
          </div>
          <div class="form-group">
            <label class="form-label">Địa chỉ chi tiết *</label>
            <input name="address" class="form-input" required placeholder="Số nhà, tên đường...">
          </div>
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">Quận / Huyện</label>
              <input name="district" class="form-input" placeholder="Quận 1">
            </div>
            <div class="form-group">
              <label class="form-label">Tỉnh / Thành phố</label>
              <input name="city" class="form-input" placeholder="TP. Hồ Chí Minh">
            </div>
          </div>
          <div class="form-group">
            <label class="form-label">Ghi chú đơn hàng</label>
            <textarea name="note" class="form-input" rows="3" placeholder="Ghi chú (tùy chọn)..."></textarea>
          </div>
        </div>
        <div class="form-section">
          <h3>Phương thức thanh toán</h3>
          <div class="payment-methods" id="paymentMethods">
            <label class="payment-method active" onclick="selectPayment(this,'cod')">
              <input type="radio" name="payment" value="cod" checked>
              
              <div class="payment-method-name">Tiền mặt</div>
            </label>
            <label class="payment-method" onclick="selectPayment(this,'transfer')">
              <input type="radio" name="payment" value="transfer">
              
              <div class="payment-method-name">Chuyển khoản</div>
            </label>
            <label class="payment-method" onclick="selectPayment(this,'momo')">
              <input type="radio" name="payment" value="momo">
              
              <div class="payment-method-name">MoMo</div>
            </label>
          </div>
        </div>
      </div>
      <div>
        <div class="order-summary">
          <h3>Đơn hàng của bạn</h3>
          <div id="checkoutItems"></div>
          <div style="margin-top:16px;padding-top:14px;border-top:1px solid var(--border)">
            <div class="summary-row"><span>Tạm tính</span><span id="co-sub">0đ</span></div>
            <div class="summary-row"><span>Phí vận chuyển</span><span style="color:var(--success)">Miễn phí</span></div>
            <div class="summary-total"><span>Tổng</span><span id="co-total">0đ</span></div>
          </div>
          <button type="submit" class="place-order-btn" id="placeBtn">Đặt hàng ngay</button>
          <div style="text-align:center;margin-top:10px;font-size:12px;color:var(--text3)">Thông tin được bảo mật</div>
        </div>
      </div>
    </div>
  </form>
</div>
{TOAST_JS}
<script>
function fmt(n){{return new Intl.NumberFormat('vi-VN').format(n)+'đ'}}
function selectPayment(el,v){{
  document.querySelectorAll('.payment-method').forEach(x=>x.classList.remove('active'));
  el.classList.add('active');
}}
function loadCheckout(){{
  fetch('/api/cart')
  .then(r=>{{
    if(r.status===401){{window.location='/login?next=/checkout';return null;}}
    return r.json();
  }})
  .then(cart=>{{
    if(!cart) return;
    if(!cart.length){{window.location='/cart';return;}}
    document.getElementById('cartJsonInput').value=JSON.stringify(cart);
    let html='',total=0;
    cart.forEach(item=>{{
      total+=item.price*item.qty;
      const imgHtml=item.imgFile
        ?`<img src="/imgs/${{item.imgFile}}" style="width:48px;height:48px;object-fit:cover;border-radius:8px;border:1px solid var(--border)" onerror="this.style.display='none'">`
        :`<div style="width:48px;height:48px;background:var(--bg3);border-radius:8px;border:1px solid var(--border)"></div>`;
      html+=`<div style="display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid var(--border);font-size:14px">
        <div style="display:flex;align-items:center;gap:10px">
          ${{imgHtml}}
          <div><div style="font-weight:500">${{item.name}}</div><div style="color:var(--text3)">x${{item.qty}}</div></div>
        </div>
        <span style="font-weight:600;color:var(--accent)">${{fmt(item.price*item.qty)}}</span>
      </div>`;
    }});
    document.getElementById('checkoutItems').innerHTML=html;
    document.getElementById('co-sub').textContent=fmt(total);
    document.getElementById('co-total').textContent=fmt(total);
  }});
}}
document.getElementById('checkoutForm').addEventListener('submit',function(){{
  fetch('/api/cart/clear',{{method:'POST'}});
}});
document.addEventListener('DOMContentLoaded',loadCheckout);
</script>
</body></html>""")


@app.route('/order/success/<oid>')
def order_success(oid):
    db = load_db()
    order = next((o for o in db.get('orders', []) if o['id'] == oid), None)
    return render_template_string(f"""<!DOCTYPE html><html lang="vi"><head>{BASE_STYLE}<title>Đặt hàng thành công!</title></head><body>
{nav()}
<div class="section success-page">
  
  <h1 style="font-size:32px;font-weight:700;margin-bottom:8px">Đặt hàng thành công!</h1>
  <p style="color:var(--text2);margin-bottom:8px">Cảm ơn bạn đã mua hàng tại URBANSTORE</p>
  <p style="font-size:14px;color:var(--text3);margin-bottom:32px">Mã đơn hàng: <b style="color:var(--accent)">{oid}</b></p>
  {"<div style='background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:24px;max-width:480px;margin:0 auto 32px;text-align:left'><div style='font-size:14px;color:var(--text2)'><div style='display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border)'><span>Khách hàng</span><span style='color:var(--text)'>" + str(order.get('name','')) + "</span></div><div style='display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border)'><span>Địa chỉ</span><span style='color:var(--text);text-align:right;max-width:240px'>" + str(order.get('address','')) + "</span></div><div style='display:flex;justify-content:space-between;padding:8px 0'><span>Tổng tiền</span><span style='color:var(--accent);font-size:16px;font-weight:700'>" + fmt(order.get('total',0)) + "</span></div></div></div>" if order else ""}
  <div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap">
    <a href="/orders"><button class="btn-primary">Xem đơn hàng</button></a>
    <a href="/products"><button class="btn-secondary">Tiếp tục mua sắm</button></a>
  </div>
</div>
</body></html>""")


@app.route('/orders')
def orders_page():
    user = session.get('user', '')
    db = load_db()
    all_orders = db.get('orders', [])
    if user:
        user_orders = [o for o in all_orders if o.get('user') == user]
    else:
        user_orders = []

    STATUS_MAP = {'pending': ('Chờ xác nhận','status-pending'), 'processing': ('Đang xử lý','status-processing'), 'shipped': ('Đang giao','status-shipped'), 'done': ('Hoàn thành','status-done')}

    if not user_orders:
        orders_html = f'''
        <div class="empty-cart">
          
          <h3>{"Chưa có đơn hàng" if user else "Vui lòng đăng nhập"}</h3>
          <p>{"Bạn chưa đặt hàng nào" if user else "Đăng nhập để xem lịch sử đơn hàng"}</p>
          <a href="{"/" if not user else "/products"}"><button class="btn-primary">{"Đăng nhập" if not user else "Mua ngay"}</button></a>
        </div>'''
    else:
        orders_html = ''
        for o in reversed(user_orders):
            s_label, s_class = STATUS_MAP.get(o.get('status','pending'), ('--',''))
            items_preview = ''.join([f'<span class="order-item-chip">{it["name"]} x{it["qty"]}</span>' for it in o.get('items', [])[:3]])
            orders_html += f'''
            <div class="order-card">
              <div class="order-header">
                <div>
                  <div class="order-id">Đơn #{o["id"]}</div>
                  <div style="font-size:12px;color:var(--text3);margin-top:2px">{time.strftime("%d/%m/%Y %H:%M", time.localtime(o.get("time",0)))}</div>
                </div>
                <div style="text-align:right">
                  <span class="order-status {s_class}">{s_label}</span>
                  <div style="font-size:16px;font-weight:700;color:var(--accent);margin-top:4px">{fmt(o.get("total",0))}</div>
                </div>
              </div>
              <div class="order-items-preview">{items_preview}</div>
              <div style="margin-top:12px;font-size:13px;color:var(--text3)">{o.get("address","")}</div>
            </div>'''

    return render_template_string(f"""<!DOCTYPE html><html lang="vi"><head>{BASE_STYLE}<title>Đơn hàng - URBANSTORE</title></head><body>
{nav('orders')}
<div class="section">
  <h1 style="font-size:26px;font-weight:700;margin-bottom:28px">Đơn hàng của tôi</h1>
  {orders_html}
</div>
</body></html>""")


# === AUTH ===
@app.route('/login', methods=['GET', 'POST'])
def login_page():
    error = ''
    if request.method == 'POST':
        u = request.form.get('username', '').strip()
        p = request.form.get('password', '')
        db = load_db()
        users = db.get('users', {})
        if u in users and check_password_hash(users[u]['pw'], p):
            session['user'] = u
            return redirect(request.args.get('next', '/'))
        error = 'Tên đăng nhập hoặc mật khẩu không đúng'

    return render_template_string(f"""<!DOCTYPE html><html lang="vi"><head>{BASE_STYLE}<title>Đăng nhập</title></head><body>
<div class="auth-page">
  <div class="auth-card">
    
    <h1 class="auth-title">Chào mừng trở lại!</h1>
    <p class="auth-sub">Đăng nhập vào tài khoản của bạn</p>
    {"<div class='alert alert-error'>"+error+"</div>" if error else ""}
    <form method="POST">
      <div class="form-group">
        <label class="form-label">Tên đăng nhập</label>
        <input name="username" class="form-input" required placeholder="username" autocomplete="username">
      </div>
      <div class="form-group">
        <label class="form-label">Mật khẩu</label>
        <input name="password" type="password" class="form-input" required placeholder="••••••••" autocomplete="current-password">
      </div>
      <button type="submit" class="auth-btn">Đăng nhập</button>
    </form>
    <div class="auth-divider">hoặc</div>
    <div class="auth-link">Chưa có tài khoản? <a href="/register">Đăng ký ngay</a></div>
  </div>
</div>
</body></html>""")


@app.route('/register', methods=['GET', 'POST'])
def register():
    error = ''
    if request.method == 'POST':
        u = request.form.get('username', '').strip()
        p = request.form.get('password', '')
        p2 = request.form.get('password2', '')
        if not u or not p:
            error = 'Vui lòng nhập đầy đủ thông tin'
        elif p != p2:
            error = 'Mật khẩu không khớp'
        else:
            db = load_db()
            users = db.setdefault('users', {})
            if u in users:
                error = 'Tên đăng nhập đã tồn tại'
            else:
                users[u] = {'pw': generate_password_hash(p), 'created': int(time.time())}
                save_db(db)
                session['user'] = u
                return redirect('/')

    return render_template_string(f"""<!DOCTYPE html><html lang="vi"><head>{BASE_STYLE}<title>Đăng ký</title></head><body>
<div class="auth-page">
  <div class="auth-card">
    
    <h1 class="auth-title">Tạo tài khoản mới</h1>
    <p class="auth-sub">Tham gia URBANSTORE ngay hôm nay</p>
    {"<div class='alert alert-error'>"+error+"</div>" if error else ""}
    <form method="POST">
      <div class="form-group">
        <label class="form-label">Tên đăng nhập</label>
        <input name="username" class="form-input" required placeholder="username">
      </div>
      <div class="form-group">
        <label class="form-label">Mật khẩu</label>
        <input name="password" type="password" class="form-input" required placeholder="Ít nhất 6 ký tự">
      </div>
      <div class="form-group">
        <label class="form-label">Xác nhận mật khẩu</label>
        <input name="password2" type="password" class="form-input" required placeholder="Nhập lại mật khẩu">
      </div>
      <button type="submit" class="auth-btn">Đăng ký</button>
    </form>
    <div class="auth-link">Đã có tài khoản? <a href="/login">Đăng nhập</a></div>
  </div>
</div>
</body></html>""")


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


# =====================================================================
#   ADMIN ROUTES (học từ webtoon.py)
# =====================================================================

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    error = ''
    if request.method == 'POST':
        if request.form.get('username') == ADMIN_USER and request.form.get('password') == ADMIN_PASS:
            session['is_admin'] = True
            return redirect('/admin')
        error = 'Sai tên đăng nhập hoặc mật khẩu'
    return render_template_string(f"""<!DOCTYPE html><html lang="vi"><head>{BASE_STYLE}<title>Admin Login</title></head><body>
<div class="auth-page">
  <div class="auth-card">
    
    <h1 class="auth-title">Quản trị viên</h1>
    <p class="auth-sub">Đăng nhập vào bảng điều khiển</p>
    {"<div class='alert alert-error'>"+error+"</div>" if error else ""}
    <form method="POST">
      <div class="form-group"><label class="form-label">Tên đăng nhập</label><input name="username" class="form-input" required placeholder="admin"></div>
      <div class="form-group"><label class="form-label">Mật khẩu</label><input name="password" type="password" class="form-input" required placeholder="••••••••"></div>
      <button type="submit" class="auth-btn">Đăng nhập</button>
    </form>
  </div>
</div>
</body></html>""")


@app.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect('/')


@app.route('/admin')
@admin_required
@catch_errors
def admin_dashboard():
    db = load_db()
    orders = db.get('orders', [])
    users = db.get('users', {})
    products = get_products()
    revenue = sum(o.get('total', 0) for o in orders if o.get('status') != 'cancelled')
    pending = sum(1 for o in orders if o.get('status') == 'pending')

    STATUS_MAP = {'pending': ('Chờ xác nhận','status-pending'), 'processing': ('Đang xử lý','status-processing'), 'shipped': ('Đang giao','status-shipped'), 'done': ('Hoàn thành','status-done')}
    recent_orders = list(reversed(orders))[:10]
    rows = ''
    for o in recent_orders:
        s_label, s_class = STATUS_MAP.get(o.get('status','pending'), ('--',''))
        rows += f'''<tr>
          <td><b>{o["id"]}</b></td>
          <td>{o.get("name","")}</td>
          <td>{fmt(o.get("total",0))}</td>
          <td><span class="order-status {s_class}">{s_label}</span></td>
          <td>{time.strftime("%d/%m/%Y", time.localtime(o.get("time",0)))}</td>
          <td>
            <form method="POST" action="/admin/update_order" style="display:inline">
              <input type="hidden" name="oid" value="{o["id"]}">
              <select name="status" class="form-input" style="padding:4px 8px;font-size:12px;width:auto" onchange="this.form.submit()">
                {''.join(f'<option value="{k}" {"selected" if o.get("status")==k else ""}>{v[0]}</option>' for k,v in STATUS_MAP.items())}
              </select>
            </form>
          </td>
        </tr>'''

    return render_template_string(f"""<!DOCTYPE html><html lang="vi"><head>{BASE_STYLE}<title>Admin Dashboard</title></head><body>
{nav()}
<div class="admin-layout">
  <div class="admin-sidebar">
    <div class="admin-sidebar-title">Quản lý</div>
    <a href="/admin" class="admin-nav-item active">Dashboard</a>
    <a href="/admin/products" class="admin-nav-item">Sản phẩm</a>
    <a href="/admin/orders" class="admin-nav-item">Đơn hàng</a>
    <a href="/admin/users" class="admin-nav-item">Người dùng</a>
    <div style="margin-top:auto;padding-top:20px;border-top:1px solid var(--border)">
      <a href="/admin/logout" class="admin-nav-item" style="color:var(--danger)">Đăng xuất</a>
    </div>
  </div>
  <div class="admin-content">
    <h1 style="font-size:24px;font-weight:700;margin-bottom:24px">Tổng quan</h1>
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-icon"></div>
        <div class="stat-value">{fmt(revenue)}</div>
        <div class="stat-label">Doanh thu</div>
        <div class="stat-change">↑ Tất cả thời gian</div>
      </div>
      <div class="stat-card">
        <div class="stat-icon"></div>
        <div class="stat-value">{len(orders)}</div>
        <div class="stat-label">Tổng đơn hàng</div>
        <div class="stat-change" style="color:var(--info)">{pending} chờ xác nhận</div>
      </div>
      <div class="stat-card">
        <div class="stat-icon"></div>
        <div class="stat-value">{len(products)}</div>
        <div class="stat-label">Sản phẩm</div>
      </div>
      <div class="stat-card">
        <div class="stat-icon"></div>
        <div class="stat-value">{len(users)}</div>
        <div class="stat-label">Người dùng</div>
      </div>
    </div>
    <div class="table-card">
      <div class="table-header">
        <h3>Đơn hàng gần đây</h3>
        <a href="/admin/orders" style="font-size:13px;color:var(--accent)">Xem tất cả →</a>
      </div>
      <table class="admin-table">
        <thead><tr><th>Mã đơn</th><th>Khách hàng</th><th>Tổng tiền</th><th>Trạng thái</th><th>Ngày</th><th>Cập nhật</th></tr></thead>
        <tbody>{rows if rows else "<tr><td colspan='6' style='text-align:center;color:var(--text3);padding:32px'>Chưa có đơn hàng nào</td></tr>"}</tbody>
      </table>
    </div>
  </div>
</div>
</body></html>""")


@app.route('/admin/update_order', methods=['POST'])
@admin_required
def update_order():
    oid = request.form.get('oid')
    status = request.form.get('status')
    db = load_db()
    for o in db.get('orders', []):
        if o['id'] == oid:
            o['status'] = status
            break
    save_db(db)
    return redirect(request.referrer or '/admin')


@app.route('/admin/products')
@admin_required
def admin_products():
    products = get_products()
    rows = ''.join([f'''<tr>
      <td></td>
      <td><b>{p["name"]}</b><br><small style="color:var(--text3)">{p["id"]}</small></td>
      <td>{fmt(p["price"])}</td>
      <td>{CATEGORIES.get(p["category"],"--")}</td>
      <td>{p["stock"]}</td>
      <td>{p["sold"]}</td>
      <td>{"".join([f'<span class="tag tag-{"new" if t==(chr(109)+chr(7899)+chr(105)) else "hot" if t=="hot" else "sale"}">{t}</span>' for t in p.get("tags",[])])}</td>
    </tr>''' for p in products])

    return render_template_string(f"""<!DOCTYPE html><html lang="vi"><head>{BASE_STYLE}<title>Quản lý sản phẩm</title></head><body>
{nav()}
<div class="admin-layout">
  <div class="admin-sidebar">
    <div class="admin-sidebar-title">Quản lý</div>
    <a href="/admin" class="admin-nav-item">Dashboard</a>
    <a href="/admin/products" class="admin-nav-item active">Sản phẩm</a>
    <a href="/admin/orders" class="admin-nav-item">Đơn hàng</a>
    <a href="/admin/users" class="admin-nav-item">Người dùng</a>
    <a href="/admin/logout" class="admin-nav-item" style="color:var(--danger)">Đăng xuất</a>
  </div>
  <div class="admin-content">
    <h1 style="font-size:24px;font-weight:700;margin-bottom:24px">Quản lý sản phẩm</h1>
    <div class="table-card">
      <div class="table-header">
        <h3>Danh sách sản phẩm ({len(products)})</h3>
      </div>
      <table class="admin-table">
        <thead><tr><th>Ảnh</th><th>Tên sản phẩm</th><th>Giá</th><th>Danh mục</th><th>Tồn kho</th><th>Đã bán</th><th>Tags</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  </div>
</div>
</body></html>""")


@app.route('/admin/orders')
@admin_required
def admin_orders():
    db = load_db()
    orders = list(reversed(db.get('orders', [])))
    STATUS_MAP = {'pending': ('Chờ xác nhận','status-pending'), 'processing': ('Đang xử lý','status-processing'), 'shipped': ('Đang giao','status-shipped'), 'done': ('Hoàn thành','status-done')}

    rows = ''.join([f'''<tr>
      <td><b>{o["id"]}</b></td>
      <td>{o.get("name","")}<br><small style="color:var(--text3)">{o.get("phone","")}</small></td>
      <td style="font-size:12px;color:var(--text2);max-width:200px">{o.get("address","")}</td>
      <td><b style="color:var(--accent)">{fmt(o.get("total",0))}</b></td>
      <td><span class="order-status {STATUS_MAP.get(o.get("status","pending"),("",""))[1]}">{STATUS_MAP.get(o.get("status","pending"),("--",""))[0]}</span></td>
      <td>{time.strftime("%d/%m %H:%M", time.localtime(o.get("time",0)))}</td>
      <td>
        <form method="POST" action="/admin/update_order" style="display:inline">
          <input type="hidden" name="oid" value="{o["id"]}">
          <select name="status" class="form-input" style="padding:4px;font-size:12px;width:auto" onchange="this.form.submit()">
            {''.join(f'<option value="{k}" {"selected" if o.get("status")==k else ""}>{v[0]}</option>' for k,v in STATUS_MAP.items())}
          </select>
        </form>
      </td>
    </tr>''' for o in orders])

    return render_template_string(f"""<!DOCTYPE html><html lang="vi"><head>{BASE_STYLE}<title>Quản lý đơn hàng</title></head><body>
{nav()}
<div class="admin-layout">
  <div class="admin-sidebar">
    <div class="admin-sidebar-title">Quản lý</div>
    <a href="/admin" class="admin-nav-item">Dashboard</a>
    <a href="/admin/products" class="admin-nav-item">Sản phẩm</a>
    <a href="/admin/orders" class="admin-nav-item active">Đơn hàng</a>
    <a href="/admin/users" class="admin-nav-item">Người dùng</a>
    <a href="/admin/logout" class="admin-nav-item" style="color:var(--danger)">Đăng xuất</a>
  </div>
  <div class="admin-content">
    <h1 style="font-size:24px;font-weight:700;margin-bottom:24px">Quản lý đơn hàng ({len(orders)})</h1>
    <div class="table-card">
      <table class="admin-table">
        <thead><tr><th>Mã đơn</th><th>Khách hàng</th><th>Địa chỉ</th><th>Tổng tiền</th><th>Trạng thái</th><th>Thời gian</th><th>Cập nhật</th></tr></thead>
        <tbody>{rows if rows else "<tr><td colspan='7' style='text-align:center;color:var(--text3);padding:40px'>Chưa có đơn hàng</td></tr>"}</tbody>
      </table>
    </div>
  </div>
</div>
</body></html>""")


@app.route('/admin/users')
@admin_required
def admin_users():
    db = load_db()
    users = db.get('users', {})
    rows = ''.join([f'''<tr>
      <td><b>{u}</b></td>
      <td>{time.strftime("%d/%m/%Y", time.localtime(info.get("created",0)))}</td>
      <td>{sum(1 for o in db.get("orders",[]) if o.get("user")==u)}</td>
    </tr>''' for u, info in users.items()])

    return render_template_string(f"""<!DOCTYPE html><html lang="vi"><head>{BASE_STYLE}<title>Quản lý người dùng</title></head><body>
{nav()}
<div class="admin-layout">
  <div class="admin-sidebar">
    <div class="admin-sidebar-title">Quản lý</div>
    <a href="/admin" class="admin-nav-item">Dashboard</a>
    <a href="/admin/products" class="admin-nav-item">Sản phẩm</a>
    <a href="/admin/orders" class="admin-nav-item">Đơn hàng</a>
    <a href="/admin/users" class="admin-nav-item active">Người dùng</a>
    <a href="/admin/logout" class="admin-nav-item" style="color:var(--danger)">Đăng xuất</a>
  </div>
  <div class="admin-content">
    <h1 style="font-size:24px;font-weight:700;margin-bottom:24px">Người dùng ({len(users)})</h1>
    <div class="table-card">
      <table class="admin-table">
        <thead><tr><th>Tên đăng nhập</th><th>Ngày tạo</th><th>Số đơn hàng</th></tr></thead>
        <tbody>{rows if rows else "<tr><td colspan='3' style='text-align:center;color:var(--text3);padding:40px'>Chưa có người dùng nào</td></tr>"}</tbody>
      </table>
    </div>
  </div>
</div>
</body></html>""")


# === API (học từ webtoon.py) ===
@app.route('/api/products')
def api_products():
    return jsonify(get_products())

@app.route('/api/product/<pid>')
def api_product(pid):
    p = get_product(pid)
    return jsonify(p) if p else jsonify({"error": "Not found"}), 404

# === API GIỎ HÀNG (server-side, lưu theo user) ===

def get_user_cart(username):
    db = load_db()
    return db.get('carts', {}).get(username, [])

def save_user_cart(username, cart):
    db = load_db()
    db.setdefault('carts', {})[username] = cart
    save_db(db)

@app.route('/api/cart')
def api_cart_get():
    u = session.get('user')
    if not u:
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(get_user_cart(u))

@app.route('/api/cart/add', methods=['POST'])
def api_cart_add():
    u = session.get('user')
    if not u:
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json()
    pid      = data.get('pid')
    name     = data.get('name', '')
    price    = data.get('price', 0)
    img_file = data.get('imgFile', '')
    qty      = int(data.get('qty', 1))
    cart = get_user_cart(u)
    idx = next((i for i, x in enumerate(cart) if x['pid'] == pid), -1)
    if idx > -1:
        cart[idx]['qty'] += qty
    else:
        cart.append({'pid': pid, 'name': name, 'price': price, 'imgFile': img_file, 'qty': qty})
    save_user_cart(u, cart)
    total_qty = sum(x['qty'] for x in cart)
    return jsonify({"ok": True, "total_qty": total_qty, "cart": cart})

@app.route('/api/cart/update', methods=['POST'])
def api_cart_update():
    u = session.get('user')
    if not u:
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json()
    pid = data.get('pid')
    qty = int(data.get('qty', 1))
    cart = get_user_cart(u)
    for item in cart:
        if item['pid'] == pid:
            item['qty'] = max(1, qty)
            break
    save_user_cart(u, cart)
    return jsonify({"ok": True, "cart": cart})

@app.route('/api/cart/remove', methods=['POST'])
def api_cart_remove():
    u = session.get('user')
    if not u:
        return jsonify({"error": "unauthorized"}), 401
    pid = request.get_json().get('pid')
    cart = [x for x in get_user_cart(u) if x['pid'] != pid]
    save_user_cart(u, cart)
    return jsonify({"ok": True, "cart": cart})

@app.route('/api/cart/clear', methods=['POST'])
def api_cart_clear():
    u = session.get('user')
    if not u:
        return jsonify({"error": "unauthorized"}), 401
    save_user_cart(u, [])
    return jsonify({"ok": True})

# =====================================================================

if __name__ == '__main__':
    # Tự động copy ảnh từ /mnt/user-data/uploads vào ./imgs nếu có
    import shutil
    os.makedirs("./imgs", exist_ok=True)
    uploads_dir = "/mnt/user-data/uploads"
    if os.path.exists(uploads_dir):
        copied = 0
        for fname in os.listdir(uploads_dir):
            if fname.lower().endswith(('.webp','.jpg','.jpeg','.png','.gif')):
                src = os.path.join(uploads_dir, fname)
                dst = os.path.join("./imgs", fname)
                if not os.path.exists(dst):
                    shutil.copy2(src, dst)
                    copied += 1
        if copied:
            logger.info(f"Đã copy {copied} ảnh từ uploads → ./imgs/")

    # Khởi tạo DB nếu chưa có
    if not os.path.exists(DB_FILE):
        save_db({"users": {}, "orders": [], "products": SAMPLE_PRODUCTS})
        logger.info("Đã tạo DB mới với dữ liệu mẫu", extra={"file": DB_FILE})

    # Log thông tin khởi động
    db_info = load_db()
    logger.info("=" * 48)
    logger.info("ARKNIGHTS STORE — CHUBBY LUNG SHOP")
    logger.info(f"http://0.0.0.0:5000  |  host={socket.gethostname()}")
    logger.info(f"Sản phẩm: {len(db_info.get('products',[]))}  |   Users: {len(db_info.get('users',{}))}  |   Orders: {len(db_info.get('orders',[]))}")
    logger.info(f"Anh san pham: ./imgs/")
    logger.info(f"Log dir: {os.path.abspath(LOG_DIR)}")
    logger.info(f"Admin: /admin  (admin / admin123)")
    logger.info("=" * 48)

    app.run(host='0.0.0.0', port=5000, debug=False)
