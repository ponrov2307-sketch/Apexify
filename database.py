import sqlite3
from datetime import datetime, timedelta

DB_NAME = "apexify.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # เพิ่ม usage_count เพื่อเก็บจำนวนครั้งที่ใช้ไปแล้ว (ค่าเริ่มต้น 0)
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (user_id TEXT PRIMARY KEY, status TEXT, registered_date TEXT, role TEXT, expiry_date TEXT, usage_count INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

def register_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, status, registered_date, role, usage_count) VALUES (?, ?, ?, ?, ?)", 
              (user_id, 'active', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'free', 0))
    conn.commit()
    conn.close()

def add_vip(user_id, days=30):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    expiry = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    c.execute("UPDATE users SET role='vip', expiry_date=? WHERE user_id=?", (expiry, str(user_id)))
    conn.commit()
    conn.close()
    return expiry

def check_vip(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT role, expiry_date FROM users WHERE user_id=?", (str(user_id),))
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
    """ดึงจำนวนครั้งที่ใช้ไปแล้ว"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT usage_count FROM users WHERE user_id=?", (str(user_id),))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

def increment_usage(user_id):
    """บวกจำนวนการใช้งานเพิ่ม 1 ครั้ง"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET usage_count = usage_count + 1 WHERE user_id=?", (str(user_id),))
    conn.commit()
    conn.close()