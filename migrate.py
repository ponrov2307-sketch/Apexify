import sqlite3
import psycopg2
import os
from dotenv import load_dotenv

# โหลดค่า DATABASE_URL ของ Supabase จากไฟล์ .env
load_dotenv()
SUPABASE_URL = os.getenv("DATABASE_URL")

# ชื่อไฟล์ฐานข้อมูลเก่า
SQLITE_DB = "apexify.db"

def migrate_data():
    if not SUPABASE_URL:
        print("❌ Error: ไม่พบ DATABASE_URL ในไฟล์ .env")
        return

    print("🚀 เริ่มต้นการย้ายข้อมูลจาก SQLite ไปยัง Supabase...")

    # 1. เชื่อมต่อฐานข้อมูลทั้งสองตัว
    try:
        sqlite_conn = sqlite3.connect(SQLITE_DB)
        sqlite_c = sqlite_conn.cursor()
        print("✅ เชื่อมต่อ SQLite สำเร็จ")

        pg_conn = psycopg2.connect(SUPABASE_URL)
        pg_c = pg_conn.cursor()
        print("✅ เชื่อมต่อ Supabase สำเร็จ")
    except Exception as e:
        print(f"❌ เชื่อมต่อฐานข้อมูลล้มเหลว: {e}")
        return

    # 2. ย้ายข้อมูลตาราง Users (สมาชิก)
    print("\n📦 กำลังย้ายข้อมูล Users...")
    try:
        # อ่านข้อมูลจาก SQLite
        sqlite_c.execute("SELECT user_id, status, registered_date, role, expiry_date, usage_count FROM users")
        users = sqlite_c.fetchall()
        
        count = 0
        for user in users:
            # เพิ่มลง Supabase (ใช้ ON CONFLICT เพื่อข้ามถ้ามีอยู่แล้ว)
            pg_c.execute("""
                INSERT INTO users (user_id, status, registered_date, role, expiry_date, usage_count)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
            """, user)
            count += 1
        
        print(f"✅ ย้าย Users สำเร็จ: {count} รายการ")

    except Exception as e:
        print(f"⚠️ เกิดข้อผิดพลาดตอนย้าย Users: {e}")

    # 3. ย้ายข้อมูลตาราง Watchlists (หุ้นที่เฝ้าดู)
    print("\n📦 กำลังย้ายข้อมูล Watchlists...")
    try:
        # อ่านข้อมูลจาก SQLite
        sqlite_c.execute("SELECT user_id, symbol FROM watchlists")
        items = sqlite_c.fetchall()
        
        count = 0
        for item in items:
            pg_c.execute("""
                INSERT INTO watchlists (user_id, symbol)
                VALUES (%s, %s)
                ON CONFLICT (user_id, symbol) DO NOTHING
            """, item)
            count += 1
            
        print(f"✅ ย้าย Watchlists สำเร็จ: {count} รายการ")

    except Exception as e:
        print(f"⚠️ เกิดข้อผิดพลาดตอนย้าย Watchlists: {e}")

    # 4. บันทึกและปิดการเชื่อมต่อ
    pg_conn.commit()
    sqlite_conn.close()
    pg_conn.close()
    print("\n🎉 เสร็จสิ้น! ข้อมูลทั้งหมดถูกย้ายขึ้น Cloud เรียบร้อยแล้ว")

if __name__ == "__main__":
    migrate_data()