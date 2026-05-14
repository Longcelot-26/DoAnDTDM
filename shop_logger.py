"""
shop_logger.py — Hệ thống ghi log nâng cao cho URBANSTORE
Import vào shop.py: from shop_logger import setup_logger, log_request, log_error

Cấu trúc log:
  logs/
  ├── shop_error.log     ← Chỉ lỗi ERROR trở lên (quan trọng nhất)
  ├── shop_access.log    ← Mọi HTTP request (GET/POST...)
  ├── shop_debug.log     ← Toàn bộ DEBUG (dùng khi dev)
  └── shop_YYYY-MM.log   ← Log tổng hợp theo tháng (rotate)
"""

import sys
import subprocess
import importlib.util

REQUIRED = ["flask", "werkzeug"]
missing = [m for m in REQUIRED if importlib.util.find_spec(m) is None]
if missing:
    subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])

import os
import logging
import traceback
import json
import time
import socket
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from collections import deque
from datetime import datetime
from functools import wraps

# ============================================================
#  CẤU HÌNH
# ============================================================

LOG_DIR      = "./logs"
MAX_BYTES    = 5 * 1024 * 1024   # 5 MB mỗi file trước khi rotate
BACKUP_COUNT = 10                 # Giữ tối đa 10 file cũ
CONSOLE_LINES = 20                # Số dòng hiển thị trên console

os.makedirs(LOG_DIR, exist_ok=True)

# ============================================================
#  ANSI MÀU SẮC CHO CONSOLE
# ============================================================

class AnsiColor:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    RED     = "\033[31m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    BLUE    = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN    = "\033[36m"
    WHITE   = "\033[37m"
    GRAY    = "\033[90m"
    BG_RED  = "\033[41m"

LEVEL_COLOR = {
    "DEBUG":    AnsiColor.GRAY,
    "INFO":     AnsiColor.GREEN,
    "WARNING":  AnsiColor.YELLOW,
    "ERROR":    AnsiColor.RED,
    "CRITICAL": AnsiColor.BG_RED + AnsiColor.WHITE,
}

LEVEL_ICON = {
    "DEBUG":    "🔍",
    "INFO":     "✅",
    "WARNING":  "⚠️ ",
    "ERROR":    "❌",
    "CRITICAL": "🚨",
}

# ============================================================
#  FORMATTER: Console có màu
# ============================================================

class ColorConsoleFormatter(logging.Formatter):
    def format(self, record):
        color   = LEVEL_COLOR.get(record.levelname, "")
        icon    = LEVEL_ICON.get(record.levelname, "  ")
        reset   = AnsiColor.RESET
        gray    = AnsiColor.GRAY
        bold    = AnsiColor.BOLD

        ts      = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        name    = record.name[:16].ljust(16)
        level   = f"{color}{bold}{record.levelname:<8}{reset}"
        message = f"{color}{record.getMessage()}{reset}"

        line = f"{gray}[{ts}]{reset} {icon} {level} {gray}{name}{reset} {message}"

        if record.exc_info:
            tb = self.formatException(record.exc_info)
            line += f"\n{gray}{'─'*60}{reset}\n{AnsiColor.RED}{tb}{reset}\n{gray}{'─'*60}{reset}"

        return line

# ============================================================
#  FORMATTER: File — có cấu trúc rõ ràng
# ============================================================

class FileFormatter(logging.Formatter):
    def format(self, record):
        ts      = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        level   = record.levelname
        module  = record.module
        func    = record.funcName
        lineno  = record.lineno
        message = record.getMessage()

        lines = [
            f"[{ts}] {level} | {module}.{func}():{lineno}",
            f"MSG  : {message}",
        ]

        # Thêm extra fields nếu có
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

# ============================================================
#  HANDLER: Console 20 dòng (học từ webtoon.py, nâng cấp)
# ============================================================

class SmartConsoleHandler(logging.Handler):
    def __init__(self, max_lines=CONSOLE_LINES):
        super().__init__()
        self.queue = deque(maxlen=max_lines)
        self.setFormatter(ColorConsoleFormatter())

    def emit(self, record):
        try:
            msg = self.format(record)
            for line in msg.split("\n"):
                self.queue.append(line)
            # Xóa màn hình và in lại
            print("\033[2J\033[H", end="", flush=True)
            print("\n".join(self.queue), flush=True)
        except Exception:
            self.handleError(record)

# ============================================================
#  HANDLER: Access log đặc biệt (chỉ HTTP request)
# ============================================================

class AccessFileHandler(RotatingFileHandler):
    """Chỉ ghi các HTTP request (werkzeug access log)."""
    ACCESS_FMT = logging.Formatter(
        fmt="%(asctime)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    def __init__(self, path):
        super().__init__(path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8")
        self.setLevel(logging.INFO)
        self.setFormatter(self.ACCESS_FMT)

# ============================================================
#  SETUP CHÍNH
# ============================================================

_loggers = {}

def setup_logger(app=None):
    """
    Gọi hàm này một lần duy nhất khi khởi động shop.py.
    Trả về logger chính để dùng: logger.info(), logger.error()...
    """

    # --- 1. Console handler (màu, 20 dòng) ---
    console = SmartConsoleHandler()
    console.setLevel(logging.INFO)

    # --- 2. Error file (chỉ ERROR+, rotate 5MB × 10) ---
    error_path = os.path.join(LOG_DIR, "shop_error.log")
    error_fh   = RotatingFileHandler(error_path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8")
    error_fh.setLevel(logging.ERROR)
    error_fh.setFormatter(FileFormatter())

    # --- 3. Access log (HTTP requests, rotate theo ngày) ---
    access_path = os.path.join(LOG_DIR, "shop_access.log")
    access_fh   = TimedRotatingFileHandler(access_path, when="midnight", interval=1, backupCount=30, encoding="utf-8")
    access_fh.setLevel(logging.INFO)
    access_fh.setFormatter(logging.Formatter("%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    access_fh.suffix = "%Y-%m-%d"

    # --- 4. Monthly combined log (rotate 5MB × 10) ---
    month_name  = datetime.now().strftime("%Y-%m")
    monthly_path = os.path.join(LOG_DIR, f"shop_{month_name}.log")
    monthly_fh  = RotatingFileHandler(monthly_path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8")
    monthly_fh.setLevel(logging.DEBUG)
    monthly_fh.setFormatter(FileFormatter())

    # --- Gắn vào werkzeug (HTTP access) ---
    wz = logging.getLogger("werkzeug")
    wz.setLevel(logging.INFO)
    wz.handlers = []
    wz.addHandler(console)
    wz.addHandler(access_fh)

    # --- Logger chính của app ---
    main_logger = logging.getLogger("urbanstore")
    main_logger.setLevel(logging.DEBUG)
    main_logger.handlers = []
    main_logger.addHandler(console)
    main_logger.addHandler(error_fh)
    main_logger.addHandler(monthly_fh)
    main_logger.propagate = False

    # --- Gắn vào Flask app nếu có ---
    if app is not None:
        app.logger.handlers = []
        app.logger.addHandler(console)
        app.logger.addHandler(error_fh)
        app.logger.addHandler(monthly_fh)
        app.logger.setLevel(logging.DEBUG)

    _loggers["main"]    = main_logger
    _loggers["console"] = console
    _loggers["error"]   = error_fh
    _loggers["access"]  = access_fh

    main_logger.info(f"Logger khởi động — thư mục log: {os.path.abspath(LOG_DIR)}")
    main_logger.info(f"Máy chủ: {socket.gethostname()} | PID: {os.getpid()}")

    return main_logger


def get_logger():
    """Lấy logger chính từ bất cứ đâu trong app."""
    return _loggers.get("main") or logging.getLogger("urbanstore")

# ============================================================
#  DECORATOR: Tự động log lỗi cho Flask route
# ============================================================

def catch_errors(f):
    """
    Decorator bọc Flask route, tự động log traceback khi có exception.
    Dùng: @catch_errors trước @app.route
    
    Ví dụ:
        @app.route('/cart')
        @catch_errors
        def cart_page():
            ...
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        logger = get_logger()
        try:
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(
                f"Unhandled exception in {f.__name__}(): {type(e).__name__}: {e}",
                exc_info=True,
                extra={
                    "route":    f.__name__,
                    "url":      _safe_request_url(),
                    "method":   _safe_request_method(),
                    "user":     _safe_session_user(),
                }
            )
            raise   # Re-raise để Flask xử lý 500 bình thường
    return wrapper

# ============================================================
#  HÀM TIỆN ÍCH LOG
# ============================================================

def log_request(response=None):
    """
    Ghi HTTP request vào access log.
    Dùng trong @app.after_request:
        @app.after_request
        def after(response):
            log_request(response)
            return response
    """
    logger = get_logger()
    try:
        from flask import request, session
        status  = response.status_code if response else "???"
        method  = request.method
        path    = request.path
        ip      = request.remote_addr or "unknown"
        user    = session.get("user", "-")
        ua      = request.user_agent.string[:60] if request.user_agent else "-"
        size    = response.content_length or 0

        # Màu theo status code
        if status < 300:   flag = "OK "
        elif status < 400: flag = "RDR"
        elif status < 500: flag = "ERR"
        else:              flag = "SRV"

        msg = f"{flag} {status} | {method:<6} {path:<40} | {ip:<15} | user={user:<12} | {size}B"
        if status >= 500:
            logger.error(msg)
        elif status >= 400:
            logger.warning(msg)
        else:
            logger.info(msg)
    except Exception:
        pass
    return response


def log_error(message, exc=None, **extra):
    """
    Ghi lỗi thủ công từ bất cứ đâu trong code.
    
    Ví dụ:
        log_error("Không lưu được DB", exc=e, user="minh", action="checkout")
    """
    logger = get_logger()
    if exc:
        logger.error(message, exc_info=exc, extra=extra)
    else:
        logger.error(message, extra=extra)


def log_info(message, **extra):
    get_logger().info(message, extra=extra or None)


def log_warning(message, **extra):
    get_logger().warning(message, extra=extra or None)


def log_debug(message, **extra):
    get_logger().debug(message, extra=extra or None)

# ============================================================
#  HÀM HELPER NỘI BỘ
# ============================================================

def _safe_request_url():
    try:
        from flask import request
        return request.url
    except Exception:
        return "N/A"

def _safe_request_method():
    try:
        from flask import request
        return request.method
    except Exception:
        return "N/A"

def _safe_session_user():
    try:
        from flask import session
        return session.get("user", "guest")
    except Exception:
        return "unknown"

# ============================================================
#  XEM LOG NHANH (chạy trực tiếp: python shop_logger.py)
# ============================================================

def view_logs(n=40):
    """In n dòng cuối của error log ra terminal."""
    path = os.path.join(LOG_DIR, "shop_error.log")
    if not os.path.exists(path):
        print(f"[!] Chưa có file log: {path}")
        return
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    print(f"\n{'═'*60}")
    print(f"  📋 {n} dòng cuối — {path}")
    print(f"{'═'*60}\n")
    for line in lines[-n:]:
        line = line.rstrip()
        if "ERROR" in line or "CRITICAL" in line:
            print(f"\033[31m{line}\033[0m")
        elif "WARNING" in line:
            print(f"\033[33m{line}\033[0m")
        elif "─"*10 in line:
            print(f"\033[90m{line}\033[0m")
        else:
            print(line)
    print()


def generate_test_logs():
    """Sinh dữ liệu log mẫu để test."""
    logger = setup_logger()
    print("\nSinh log mẫu...\n")

    logger.info("Server URBANSTORE khởi động thành công")
    logger.info("Database loaded: 12 sản phẩm, 3 users, 5 đơn hàng",
                extra={"products": 12, "users": 3, "orders": 5})

    logger.info("GET /products 200 | 127.0.0.1 | user=khachhang1")
    logger.info("POST /checkout 200 | 192.168.1.5 | user=trang_dep | total=970000")
    logger.info("GET /admin 200 | 127.0.0.1 | is_admin=True")

    logger.warning("Sản phẩm p010 sắp hết hàng: còn 2",
                   extra={"pid": "p010", "stock": 2})
    logger.warning("Đăng nhập thất bại 3 lần liên tiếp",
                   extra={"ip": "203.0.113.55", "username": "unknown"})

    try:
        data = {}
        _ = data["missing_key"]
    except KeyError as e:
        logger.error(f"KeyError khi đọc dữ liệu sản phẩm: {e}",
                     exc_info=True,
                     extra={"pid": "p099", "route": "product_detail"})

    try:
        raise PermissionError("Permission denied: './shop_db.json'")
    except PermissionError as e:
        logger.error(f"Không thể ghi database: {e}",
                     exc_info=True,
                     extra={"file": "shop_db.json", "action": "save_db"})

    try:
        raise ConnectionError("OSError: [Errno 98] Address already in use")
    except ConnectionError as e:
        logger.critical(f"Server không thể khởi động: {e}",
                        exc_info=True,
                        extra={"port": 5000})

    print(f"\n✅ Log đã ghi vào thư mục: {os.path.abspath(LOG_DIR)}/")
    print("   shop_error.log  — chỉ ERROR+")
    print(f"   shop_{datetime.now().strftime('%Y-%m')}.log  — tổng hợp")
    view_logs(30)


if __name__ == "__main__":
    generate_test_logs()
