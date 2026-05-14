"""
init_db.py — Công cụ khởi tạo & quản lý Database cho URBANSTORE
Chạy: python init_db.py
"""

import sys
import subprocess
import importlib.util

REQUIRED_MODULES = ["werkzeug"]

def check_and_install():
    missing = [m for m in REQUIRED_MODULES if importlib.util.find_spec(m) is None]
    if missing:
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])

check_and_install()

import os
import json
import time
from werkzeug.security import generate_password_hash

DB_FILE = "./shop_db.json"

# ==============================================================
#  DỮ LIỆU MẪU
# ==============================================================

PRODUCTS = [
    {"id": "p001", "name": "Áo Thun Basic Trắng",       "price": 189000,  "original_price": 250000, "category": "ao",   "stock": 50, "sold": 128, "image": "👕", "desc": "Chất liệu cotton 100%, thoáng mát, phù hợp mọi dịp. Form regular fit chuẩn, không co rút sau khi giặt.", "tags": ["mới","bán chạy"]},
    {"id": "p002", "name": "Quần Jean Slim Fit",          "price": 450000,  "original_price": 580000, "category": "quan", "stock": 30, "sold": 87,  "image": "👖", "desc": "Chất liệu denim cao cấp, co giãn 4 chiều, form slim hiện đại. Phù hợp đi làm và dạo phố.", "tags": ["hot"]},
    {"id": "p003", "name": "Giày Sneaker Trắng",          "price": 750000,  "original_price": 950000, "category": "giay", "stock": 20, "sold": 214, "image": "👟", "desc": "Đế cao su chống trơn, thiết kế tối giản thời thượng. Phù hợp mix đồ casual hoặc sporty.", "tags": ["bán chạy","sale"]},
    {"id": "p004", "name": "Túi Tote Canvas",             "price": 220000,  "original_price": 280000, "category": "phu",  "stock": 45, "sold": 63,  "image": "👜", "desc": "Vải canvas bền chắc, dây đeo chắc chắn, nhiều màu sắc. Sức chứa lớn, thích hợp đi học, đi chợ.", "tags": ["mới"]},
    {"id": "p005", "name": "Kính Mắt Vuông Retro",        "price": 320000,  "original_price": 420000, "category": "phu",  "stock": 15, "sold": 45,  "image": "🕶️","desc": "Gọng kim loại nhẹ, tròng chống UV400. Thiết kế retro phù hợp nhiều khuôn mặt.", "tags": ["mới","hot"]},
    {"id": "p006", "name": "Áo Khoác Bomber Đen",         "price": 680000,  "original_price": 850000, "category": "ao",   "stock": 18, "sold": 39,  "image": "🧥", "desc": "Vải dù chống gió nhẹ, lót lông ấm, nhiều túi tiện dụng. Phong cách streetwear hiện đại.", "tags": ["hot","sale"]},
    {"id": "p007", "name": "Mũ Bucket Vải Twill",         "price": 150000,  "original_price": 200000, "category": "phu",  "stock": 60, "sold": 96,  "image": "🧢", "desc": "Vải twill mịn, vành rộng che nắng, dây điều chỉnh phía sau. Có nhiều màu: đen, be, xanh rêu.", "tags": ["mới"]},
    {"id": "p008", "name": "Quần Shorts Thể Thao",        "price": 280000,  "original_price": 350000, "category": "quan", "stock": 35, "sold": 72,  "image": "🩳", "desc": "Chất vải thun lạnh thoát nhiệt nhanh, dây rút tiện lợi. Phù hợp tập gym, chạy bộ, mặc nhà.", "tags": ["bán chạy"]},
    {"id": "p009", "name": "Áo Hoodie Oversize",          "price": 520000,  "original_price": 650000, "category": "ao",   "stock": 25, "sold": 105, "image": "👕", "desc": "Cotton fleece dày, form rộng thoải mái, túi kangaroo phía trước. Mặc mùa lạnh hoặc phong cách Y2K.", "tags": ["hot","bán chạy"]},
    {"id": "p010", "name": "Dép Sandal Da Bò",            "price": 480000,  "original_price": 600000, "category": "giay", "stock": 22, "sold": 58,  "image": "👡", "desc": "Da bò thật nguyên miếng, đế cao su đúc siêu bền. Thiết kế tối giản, phù hợp đi biển hoặc dạo phố.", "tags": ["sale"]},
    {"id": "p011", "name": "Balo Laptop 15 inch",         "price": 890000,  "original_price": 1100000,"category": "phu",  "stock": 12, "sold": 34,  "image": "🎒", "desc": "Ngăn laptop đệm êm, cổng USB charging tích hợp, chất liệu chống thấm nước. Dung tích 25L.", "tags": ["mới","hot"]},
    {"id": "p012", "name": "Thắt Lưng Da Tổng Hợp",      "price": 180000,  "original_price": 250000, "category": "phu",  "stock": 40, "sold": 88,  "image": "🔗", "desc": "Da PU cao cấp, khóa kim loại mạ bạc bền chắc, điều chỉnh linh hoạt từ 70-120cm.", "tags": ["sale"]},
]

SAMPLE_USERS = [
    {"username": "khachhang1", "password": "123456",   "email": "khach1@gmail.com",   "full_name": "Nguyễn Văn An"},
    {"username": "trang_dep",  "password": "123456",   "email": "trang@gmail.com",    "full_name": "Trần Thị Trang"},
    {"username": "minh_pro",   "password": "123456",   "email": "minh@gmail.com",     "full_name": "Lê Minh Tuấn"},
]

SAMPLE_ORDERS = [
    {
        "id": "ORD0000001", "user": "khachhang1",
        "name": "Nguyễn Văn An", "phone": "0901234567",
        "address": "123 Nguyễn Huệ, Quận 1, TP. Hồ Chí Minh",
        "payment": "cod",
        "items": [
            {"pid": "p001", "name": "Áo Thun Basic Trắng", "price": 189000, "img": "👕", "qty": 2},
            {"pid": "p007", "name": "Mũ Bucket Vải Twill",  "price": 150000, "img": "🧢", "qty": 1},
        ],
        "total": 528000, "status": "done", "time": int(time.time()) - 86400 * 10
    },
    {
        "id": "ORD0000002", "user": "trang_dep",
        "name": "Trần Thị Trang", "phone": "0912345678",
        "address": "45 Lê Lợi, Hải Châu, Đà Nẵng",
        "payment": "momo",
        "items": [
            {"pid": "p003", "name": "Giày Sneaker Trắng", "price": 750000, "img": "👟", "qty": 1},
            {"pid": "p004", "name": "Túi Tote Canvas",    "price": 220000, "img": "👜", "qty": 1},
        ],
        "total": 970000, "status": "shipped", "time": int(time.time()) - 86400 * 7
    },
    {
        "id": "ORD0000003", "user": "minh_pro",
        "name": "Lê Minh Tuấn", "phone": "0987654321",
        "address": "78 Trần Phú, Buôn Ma Thuột, Đắk Lắk",
        "payment": "transfer",
        "items": [
            {"pid": "p002", "name": "Quần Jean Slim Fit",  "price": 450000, "img": "👖", "qty": 1},
            {"pid": "p006", "name": "Áo Khoác Bomber Đen", "price": 680000, "img": "🧥", "qty": 1},
            {"pid": "p011", "name": "Balo Laptop 15 inch", "price": 890000, "img": "🎒", "qty": 1},
        ],
        "total": 2020000, "status": "processing", "time": int(time.time()) - 86400 * 4
    },
    {
        "id": "ORD0000004", "user": "khachhang1",
        "name": "Nguyễn Văn An", "phone": "0901234567",
        "address": "123 Nguyễn Huệ, Quận 1, TP. Hồ Chí Minh",
        "payment": "cod",
        "items": [
            {"pid": "p009", "name": "Áo Hoodie Oversize",  "price": 520000, "img": "👕", "qty": 1},
            {"pid": "p008", "name": "Quần Shorts Thể Thao", "price": 280000, "img": "🩳", "qty": 2},
        ],
        "total": 1080000, "status": "pending", "time": int(time.time()) - 86400 * 1
    },
    {
        "id": "ORD0000005", "user": "trang_dep",
        "name": "Trần Thị Trang", "phone": "0912345678",
        "address": "45 Lê Lợi, Hải Châu, Đà Nẵng",
        "payment": "momo",
        "items": [
            {"pid": "p005", "name": "Kính Mắt Vuông Retro",  "price": 320000, "img": "🕶️", "qty": 1},
            {"pid": "p012", "name": "Thắt Lưng Da Tổng Hợp", "price": 180000, "img": "🔗", "qty": 1},
            {"pid": "p010", "name": "Dép Sandal Da Bò",       "price": 480000, "img": "👡", "qty": 1},
        ],
        "total": 980000, "status": "done", "time": int(time.time()) - 86400 * 2
    },
]

# ==============================================================
#  CÁC HÀM TIỆN ÍCH
# ==============================================================

def load():
    if not os.path.exists(DB_FILE):
        return {"products": [], "users": {}, "orders": []}
    with open(DB_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  ✅ Đã lưu → {DB_FILE}")

def fmt(n):
    return f"{int(n):,}đ".replace(",", ".")

def separator(title=""):
    print("\n" + "─" * 50)
    if title:
        print(f"  {title}")
        print("─" * 50)

# ==============================================================
#  CHỨC NĂNG CHÍNH
# ==============================================================

def init_database(force=False):
    """Khởi tạo database với dữ liệu mẫu."""
    separator("🚀 KHỞI TẠO DATABASE")
    
    if os.path.exists(DB_FILE) and not force:
        print(f"  ⚠️  File '{DB_FILE}' đã tồn tại.")
        ans = input("  Ghi đè toàn bộ? (y/N): ").strip().lower()
        if ans != 'y':
            print("  ❌ Hủy. Database giữ nguyên.")
            return

    # Build users dict với password được hash
    users = {}
    for u in SAMPLE_USERS:
        users[u["username"]] = {
            "pw":        generate_password_hash(u["password"]),
            "created":   int(time.time()),
            "email":     u["email"],
            "full_name": u["full_name"],
        }

    data = {
        "products": PRODUCTS,
        "users":    users,
        "orders":   SAMPLE_ORDERS,
    }
    save(data)

    print(f"\n  📦 Sản phẩm : {len(PRODUCTS)}")
    print(f"  👥 Người dùng: {len(users)} (mật khẩu mặc định: 123456)")
    print(f"  📋 Đơn hàng : {len(SAMPLE_ORDERS)}")
    print("\n  🎉 Database sẵn sàng! Chạy shop.py để khởi động server.")


def show_stats():
    """Hiển thị thống kê database."""
    separator("📊 THỐNG KÊ DATABASE")
    db = load()

    products = db.get("products", [])
    users    = db.get("users", {})
    orders   = db.get("orders", [])

    total_revenue = sum(o.get("total", 0) for o in orders)
    status_count  = {}
    for o in orders:
        s = o.get("status", "unknown")
        status_count[s] = status_count.get(s, 0) + 1

    print(f"\n  📦 Tổng sản phẩm : {len(products)}")
    print(f"  👥 Tổng người dùng: {len(users)}")
    print(f"  📋 Tổng đơn hàng : {len(orders)}")
    print(f"  💰 Tổng doanh thu : {fmt(total_revenue)}")
    print(f"\n  Trạng thái đơn hàng:")
    STATUS_VN = {"pending": "Chờ xác nhận", "processing": "Đang xử lý", "shipped": "Đang giao", "done": "Hoàn thành"}
    for k, v in status_count.items():
        print(f"    • {STATUS_VN.get(k, k):<18}: {v} đơn")


def list_users():
    """Liệt kê tất cả người dùng."""
    separator("👥 DANH SÁCH NGƯỜI DÙNG")
    db = load()
    users = db.get("users", {})
    orders = db.get("orders", [])

    if not users:
        print("  (trống)")
        return

    print(f"  {'Tên đăng nhập':<20} {'Họ tên':<22} {'Email':<28} {'Số đơn'}")
    print("  " + "-" * 80)
    for uname, info in users.items():
        order_count = sum(1 for o in orders if o.get("user") == uname)
        print(f"  {uname:<20} {info.get('full_name',''):<22} {info.get('email',''):<28} {order_count}")


def list_products():
    """Liệt kê tất cả sản phẩm."""
    separator("📦 DANH SÁCH SẢN PHẨM")
    db = load()
    products = db.get("products", [])

    print(f"  {'ID':<8} {'Tên sản phẩm':<30} {'Giá':<14} {'Danh mục':<10} {'Tồn':<6} {'Đã bán'}")
    print("  " + "-" * 82)
    for p in products:
        print(f"  {p['id']:<8} {p['name']:<30} {fmt(p['price']):<14} {p.get('category',''):<10} {p['stock']:<6} {p['sold']}")


def list_orders():
    """Liệt kê tất cả đơn hàng."""
    separator("📋 DANH SÁCH ĐƠN HÀNG")
    db = load()
    orders = db.get("orders", [])

    STATUS_VN = {"pending": "Chờ xác nhận", "processing": "Đang xử lý", "shipped": "Đang giao", "done": "Hoàn thành"}
    print(f"  {'Mã đơn':<14} {'Khách hàng':<22} {'Tổng tiền':<14} {'Trạng thái':<18} {'Thời gian'}")
    print("  " + "-" * 82)
    for o in reversed(orders):
        t = time.strftime("%d/%m/%Y %H:%M", time.localtime(o.get("time", 0)))
        s = STATUS_VN.get(o.get("status", ""), o.get("status", ""))
        print(f"  {o['id']:<14} {o.get('name',''):<22} {fmt(o.get('total',0)):<14} {s:<18} {t}")


def add_user():
    """Thêm người dùng mới."""
    separator("➕ THÊM NGƯỜI DÙNG MỚI")
    db = load()
    users = db.setdefault("users", {})

    uname = input("  Tên đăng nhập: ").strip()
    if not uname:
        print("  ❌ Tên đăng nhập không được để trống.")
        return
    if uname in users:
        print(f"  ❌ '{uname}' đã tồn tại.")
        return

    pw        = input("  Mật khẩu     : ").strip()
    email     = input("  Email        : ").strip()
    full_name = input("  Họ và tên   : ").strip()

    users[uname] = {
        "pw":        generate_password_hash(pw or "123456"),
        "created":   int(time.time()),
        "email":     email,
        "full_name": full_name,
    }
    save(db)
    print(f"  ✅ Đã thêm người dùng '{uname}'")


def reset_password():
    """Đặt lại mật khẩu người dùng."""
    separator("🔑 ĐẶT LẠI MẬT KHẨU")
    db = load()
    users = db.get("users", {})

    uname = input("  Tên đăng nhập: ").strip()
    if uname not in users:
        print(f"  ❌ Không tìm thấy '{uname}'.")
        return

    new_pw = input("  Mật khẩu mới : ").strip()
    if not new_pw:
        print("  ❌ Mật khẩu không được để trống.")
        return

    users[uname]["pw"] = generate_password_hash(new_pw)
    save(db)
    print(f"  ✅ Đã cập nhật mật khẩu cho '{uname}'")


def update_order_status():
    """Cập nhật trạng thái đơn hàng."""
    separator("✏️  CẬP NHẬT TRẠNG THÁI ĐƠN HÀNG")
    db = load()
    orders = db.get("orders", [])

    oid = input("  Mã đơn hàng (vd: ORD0000001): ").strip()
    order = next((o for o in orders if o["id"] == oid), None)
    if not order:
        print(f"  ❌ Không tìm thấy đơn '{oid}'.")
        return

    print(f"  Trạng thái hiện tại: {order.get('status')}")
    print("  Các trạng thái: pending / processing / shipped / done")
    new_status = input("  Trạng thái mới    : ").strip()

    valid = {"pending", "processing", "shipped", "done"}
    if new_status not in valid:
        print(f"  ❌ Trạng thái không hợp lệ. Chọn: {', '.join(valid)}")
        return

    order["status"] = new_status
    save(db)
    STATUS_VN = {"pending": "Chờ xác nhận", "processing": "Đang xử lý", "shipped": "Đang giao", "done": "Hoàn thành"}
    print(f"  ✅ Đơn {oid} → {STATUS_VN[new_status]}")


def backup_db():
    """Sao lưu database."""
    separator("💾 SAO LƯU DATABASE")
    if not os.path.exists(DB_FILE):
        print("  ❌ Chưa có database để backup.")
        return
    backup_name = f"shop_db_backup_{time.strftime('%Y%m%d_%H%M%S')}.json"
    import shutil
    shutil.copy2(DB_FILE, backup_name)
    size = os.path.getsize(backup_name)
    print(f"  ✅ Đã sao lưu → {backup_name}  ({size:,} bytes)")


def delete_user():
    """Xóa người dùng."""
    separator("🗑️  XÓA NGƯỜI DÙNG")
    db = load()
    users = db.get("users", {})

    uname = input("  Tên đăng nhập cần xóa: ").strip()
    if uname not in users:
        print(f"  ❌ Không tìm thấy '{uname}'.")
        return

    confirm = input(f"  Xác nhận xóa '{uname}'? (y/N): ").strip().lower()
    if confirm != 'y':
        print("  ❌ Hủy.")
        return

    del users[uname]
    save(db)
    print(f"  ✅ Đã xóa '{uname}'")


# ==============================================================
#  MENU CHÍNH
# ==============================================================

MENU = [
    ("Xem thống kê tổng quan",        show_stats),
    ("Khởi tạo / Reset database",     lambda: init_database()),
    ("Danh sách sản phẩm",            list_products),
    ("Danh sách người dùng",          list_users),
    ("Danh sách đơn hàng",            list_orders),
    ("Thêm người dùng mới",           add_user),
    ("Đặt lại mật khẩu",              reset_password),
    ("Xóa người dùng",                delete_user),
    ("Cập nhật trạng thái đơn hàng",  update_order_status),
    ("Sao lưu database",              backup_db),
]

def main():
    print("\n" + "═" * 50)
    print("  🏪  URBANSTORE — QUẢN LÝ DATABASE")
    print("═" * 50)

    # Tự động init nếu chưa có DB
    if not os.path.exists(DB_FILE):
        print(f"\n  ⚠️  Chưa tìm thấy '{DB_FILE}'")
        ans = input("  Khởi tạo database mới với dữ liệu mẫu? (Y/n): ").strip().lower()
        if ans != 'n':
            init_database(force=True)

    while True:
        separator("MENU CHÍNH")
        for i, (label, _) in enumerate(MENU, 1):
            print(f"  {i:2}. {label}")
        print("   0. Thoát")
        print()

        choice = input("  Chọn [0-{}]: ".format(len(MENU))).strip()

        if choice == '0':
            print("\n  👋 Tạm biệt!\n")
            break
        elif choice.isdigit() and 1 <= int(choice) <= len(MENU):
            try:
                MENU[int(choice) - 1][1]()
            except KeyboardInterrupt:
                print("\n  (đã hủy)")
            except Exception as e:
                print(f"\n  ❌ Lỗi: {e}")
            input("\n  [Nhấn Enter để tiếp tục...]")
        else:
            print("  ❌ Lựa chọn không hợp lệ.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  👋 Tạm biệt!\n")
