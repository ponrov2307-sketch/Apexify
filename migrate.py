import sqlite3
import psycopg2
import os
from dotenv import load_dotenv

# โหลดค่า DATABASE_URL ของ Supabase จากไฟล์ .env
load_dotenv()
SUPABASE_URL = os.getenv("DATABASE_URL")
SQLITE_DB = "apexify.db"

def migrate_data():
    if not SUPABASE_URL:
        print("❌ Error: ไม่พบ DATABASE_URL ในไฟล์ .env")
        return

    print("🚀 เริ่มต้นการเตรียมพร้อมและย้ายข้อมูล...")

    # 1. เชื่อมต่อฐานข้อมูล
    try:
        sqlite_conn = sqlite3.connect(SQLITE_DB)
        sqlite_c = sqlite_conn.cursor()
        pg_conn = psycopg2.connect(SUPABASE_URL)
        pg_c = pg_conn.cursor()
        print("✅ เชื่อมต่อฐานข้อมูลสำเร็จ")
    except Exception as e:
        print(f"❌ เชื่อมต่อล้มเหลว: {e}")
        return

    # 2. สร้างตารางบน Supabase (ถ้ายังไม่มี)
    print("\n🛠️ กำลังสร้างโครงสร้างตารางบน Cloud...")
    try:
        pg_c.execute('''CREATE TABLE IF NOT EXISTS users 
                     (user_id TEXT PRIMARY KEY, status TEXT, registered_date TEXT, role TEXT, expiry_date TEXT, usage_count INTEGER DEFAULT 0)''')
        pg_c.execute('''CREATE TABLE IF NOT EXISTS watchlists 
                     (user_id TEXT, symbol TEXT, PRIMARY KEY (user_id, symbol))''')
        pg_conn.commit()
        print("✅ สร้างตาราง Users และ Watchlists สำเร็จ!")
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดตอนสร้างตาราง: {e}")
        pg_conn.rollback()
        return

    # 3. ย้ายข้อมูล Users
    print("\n📦 กำลังย้ายข้อมูล Users...")
    try:
        sqlite_c.execute("SELECT user_id, status, registered_date, role, expiry_date, usage_count FROM users")
        users = sqlite_c.fetchall()
        
        count = 0
        for user in users:
            pg_c.execute("""
                INSERT INTO users (user_id, status, registered_date, role, expiry_date, usage_count)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
            """, user)
            count += 1
        pg_conn.commit()
        print(f"✅ ย้าย Users สำเร็จ: {count} รายการ")
    except Exception as e:
        print(f"⚠️ เกิดข้อผิดพลาดตอนย้าย Users: {e}")
        pg_conn.rollback()

    # 4. ย้ายข้อมูล Watchlists
    print("\n📦 กำลังย้ายข้อมูล Watchlists...")
    try:
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
        pg_conn.commit()
        print(f"✅ ย้าย Watchlists สำเร็จ: {count} รายการ")
    except Exception as e:
        print(f"⚠️ เกิดข้อผิดพลาดตอนย้าย Watchlists: {e}")
        pg_conn.rollback()

    # 5. ปิดการเชื่อมต่อ
    sqlite_conn.close()
    pg_conn.close()
    print("\n🎉 เสร็จสิ้น! ข้อมูลทั้งหมดถูกย้ายขึ้น Cloud เรียบร้อยแล้ว")

if __name__ == "__main__":
    migrate_data()