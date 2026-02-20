import os
import psycopg2
from datetime import datetime, timedelta

# ดึง URL จาก Environment Variable
DB_URL = os.getenv("DATABASE_URL")

def get_connection():
    """สร้างการเชื่อมต่อกับ PostgreSQL"""
    conn = psycopg2.connect(DB_URL)
    return conn

def init_db():
    conn = get_connection()
    c = conn.cursor()
    
    # PostgreSQL ใช้ SERIAL แทน AUTOINCREMENT ในบางกรณี แต่สำหรับ TEXT PRIMARY KEY ใช้แบบเดิมได้
    # สร้างตาราง users
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (user_id TEXT PRIMARY KEY, status TEXT, registered_date TEXT, role TEXT, expiry_date TEXT, usage_count INTEGER DEFAULT 0)''')
    
    conn.commit()
    conn.close()
    init_watchlist_db() 

def init_watchlist_db():
    conn = get_connection()
    c = conn.cursor()
    # สร้างตาราง watchlists
    c.execute('''CREATE TABLE IF NOT EXISTS watchlists 
                 (user_id TEXT, symbol TEXT, PRIMARY KEY (user_id, symbol))''')
    conn.commit()
    conn.close()

def register_user(user_id):
    conn = get_connection()
    c = conn.cursor()
    # ⚠️ เปลี่ยน ? เป็น %s สำหรับ PostgreSQL
    c.execute("INSERT INTO users (user_id, status, registered_date, role, usage_count) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (user_id) DO NOTHING", 
              (str(user_id), 'active', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'free', 0))
    conn.commit()
    conn.close()

def add_vip(user_id, days=30):
    conn = get_connection()
    c = conn.cursor()
    expiry = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    # ⚠️ เปลี่ยน ? เป็น %s
    c.execute("UPDATE users SET role='vip', expiry_date=%s WHERE user_id=%s", (expiry, str(user_id)))
    conn.commit()
    conn.close()
    return expiry

def check_vip(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT role, expiry_date FROM users WHERE user_id=%s", (str(user_id),))
    result = c.fetchone()
    conn.close()
    if result:
        role, expiry_date = result
        if role == 'vip' and expiry_date:
            expiry = datetime.strptime(expiry_date, '%Y-%m-%d %H:%M:%S')
            if datetime.now() < expiry:
                return True
    return False

def get_usage(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT usage_count FROM users WHERE user_id=%s", (str(user_id),))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

def increment_usage(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE users SET usage_count = usage_count + 1 WHERE user_id=%s", (str(user_id),))
    conn.commit()
    conn.close()

# --- ระบบ Watchlist ---
def add_watch(user_id, symbol):
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO watchlists (user_id, symbol) VALUES (%s, %s)", (str(user_id), symbol.upper()))
        conn.commit()
        return True
    except psycopg2.IntegrityError: # เปลี่ยนจาก sqlite3.IntegrityError
        conn.rollback() # ต้อง Rollback ก่อนถ้า Error
        return False 
    finally:
        conn.close()

def get_user_watch(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT symbol FROM watchlists WHERE user_id=%s", (str(user_id),))
    result = c.fetchall()
    conn.close()
    return [row[0] for row in result]

def get_users_watching(symbol):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT user_id FROM watchlists WHERE symbol=%s", (symbol.upper(),))
    result = c.fetchall()
    conn.close()
    return [row[0] for row in result]

def get_all_active_symbols():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT DISTINCT symbol FROM watchlists")
    result = c.fetchall()
    conn.close()
    return [row[0] for row in result]

# ฟังก์ชัน Helper ใน main.py (ต้องแก้ด้วย หรือย้ายมาไว้ที่นี่)
def remove_watch_db(user_id, symbol):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM watchlists WHERE user_id=%s AND symbol=%s", (str(user_id), symbol))
    conn.commit()
    conn.close()

def get_user_profile(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT role, expiry_date, usage_count FROM users WHERE user_id=%s", (str(user_id),))
    res = c.fetchone()
    conn.close()
    return res
def get_all_users():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    result = c.fetchall()
    conn.close()
    return [row[0] for row in result]