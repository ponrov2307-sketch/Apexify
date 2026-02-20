import sqlite3
from datetime import datetime, timedelta

DB_NAME = "apexify.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # อัปเกรดตารางให้รองรับสถานะ VIP และวันหมดอายุ
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (user_id TEXT PRIMARY KEY, status TEXT, registered_date TEXT, role TEXT, expiry_date TEXT)''')
    conn.commit()
    conn.close()

def register_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # ตั้งค่าเริ่มต้นให้ทุกคนที่ทักมาเป็นสาย 'free' ก่อน
    c.execute("INSERT OR IGNORE INTO users (user_id, status, registered_date, role) VALUES (?, ?, ?, ?)", 
              (user_id, 'active', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'free'))
    conn.commit()
    conn.close()

def add_vip(user_id, days=30):
    """ฟังก์ชันสำหรับต่ออายุ VIP (แอดมินใช้)"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    expiry = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    c.execute("UPDATE users SET role='vip', expiry_date=? WHERE user_id=?", (expiry, str(user_id)))
    conn.commit()
    conn.close()
    return expiry

def check_vip(user_id):
    """ฟังก์ชันเช็คสิทธิ์ VIP ว่าหมดอายุหรือยัง"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT role, expiry_date FROM users WHERE user_id=?", (str(user_id),))
    result = c.fetchone()
    conn.close()
    
    if result:
        role, expiry_date = result
        if role == 'vip' and expiry_date:
            expiry = datetime.strptime(expiry_date, '%Y-%m-%d %H:%M:%S')
            # ถ้าเวลายังไม่ถึงกำหนดหมดอายุ ให้ผ่าน
            if datetime.now() < expiry:
                return True
    return False