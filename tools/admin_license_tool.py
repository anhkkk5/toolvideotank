#!/usr/bin/env python3
"""TankVideo Admin License Key Generator Tool.

Dành cho Admin (Chủ sở hữu TankVideo):
Chạy công cụ này để tạo mã bản quyền (License Key) bán cho khách hàng thuê theo tháng.
"""

import sys
import os

# Thêm thư mục gốc vào sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.license_service import LicenseService


def main():
    print("=" * 65)
    print("     👑 TANKVIDEO - CÔNG CỤ TẠO KEY BẢN QUYỀN (ADMIN TOOL) 👑")
    print("=" * 65)

    email = input("\n1. Nhập Gmail của khách hàng: ").strip().lower()
    while not email or "@" not in email:
        print("❌ Email không hợp lệ, vui lòng nhập lại!")
        email = input("1. Nhập Gmail của khách hàng: ").strip().lower()

    days_str = input("2. Số ngày thuê (Mặc định 30 ngày): ").strip()
    try:
        days = int(days_str) if days_str else 30
    except ValueError:
        days = 30

    machine_id = input("3. Mã máy của khách (Để trống nếu cho phép kích hoạt máy bất kỳ): ").strip().upper()

    plan_choice = input("4. Gói bản quyền [1: VIP Hàng Tháng, 2: PRO 3 Tháng, 3: Vĩnh viễn] (Mặc định 1): ").strip()
    if plan_choice == "2":
        plan = "PRO"
    elif plan_choice == "3":
        plan = "LIFETIME"
        days = 3650  # 10 năm
    else:
        plan = "VIP"

    key = LicenseService.generate_license_key(
        email=email,
        days=days,
        machine_id=machine_id,
        plan=plan,
    )

    print("\n" + "=" * 65)
    print("✅ TẠO KEY BẢN QUYỀN THÀNH CÔNG!")
    print("=" * 65)
    print(f"📧 Khách hàng : {email}")
    print(f"⏱️ Thời hạn    : {days} ngày")
    print(f"💻 Mã máy khóa : {machine_id if machine_id else 'Không khóa (Tự khóa máy đầu tiên)'}")
    print(f"👑 Gói dịch vụ: {plan}")
    print("-" * 65)
    print(f"🔑 LICENSE KEY : {key}")
    print("-" * 65)
    print("👉 Hãy copy toàn bộ chuỗi KEY bên trên gửi cho khách hàng.")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
