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
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (user_id TEXT PRIMARY KEY, status TEXT, registered_date TEXT, role TEXT, expiry_date TEXT, usage_count INTEGER DEFAULT 0)''')
    
    # 🌟 อัปเดตโครงสร้างตารางโค้ด รองรับการใช้หลายคน
    c.execute('''CREATE TABLE IF NOT EXISTS promo_codes 
                 (code TEXT PRIMARY KEY, days INTEGER, max_uses INTEGER DEFAULT 1, current_uses INTEGER DEFAULT 0, used_by TEXT DEFAULT '')''')
    conn.commit()
    conn.close()
    init_watchlist_db() 

def init_watchlist_db():
    conn = get_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS watchlists 
                 (user_id TEXT, symbol TEXT, PRIMARY KEY (user_id, symbol))''')
    conn.commit()
    conn.close()

def register_user(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO users (user_id, status, registered_date, role, usage_count) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (user_id) DO NOTHING", 
              (str(user_id), 'active', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'free', 0))
    conn.commit()
    conn.close()

def add_vip(user_id, days=30):
    conn = get_connection()
    c = conn.cursor()
    
    # เช็คว่ามีวันหมดอายุเดิมไหม เพื่อทบยอดวันถ้ายังไม่หมดอายุ
    c.execute("SELECT expiry_date FROM users WHERE user_id=%s", (str(user_id),))
    result = c.fetchone()
    
    now = datetime.now()
    new_expiry = now + timedelta(days=days)
    
    if result and result[0]:
        try:
            old_expiry = datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S')
            if old_expiry > now:
                new_expiry = old_expiry + timedelta(days=days) # ทบวันเดิม
        except:
            pass
            
    expiry_str = new_expiry.strftime('%Y-%m-%d %H:%M:%S')
    c.execute("UPDATE users SET role='vip', expiry_date=%s WHERE user_id=%s", (expiry_str, str(user_id)))
    conn.commit()
    conn.close()
    return expiry_str

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

def add_watch(user_id, symbol):
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO watchlists (user_id, symbol) VALUES (%s, %s)", (str(user_id), symbol.upper()))
        conn.commit()
        return True
    except psycopg2.IntegrityError:
        conn.rollback() 
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

def remove_watch_db(user_id, symbol):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM watchlists WHERE user_id=%s AND symbol=%s", (str(user_id), symbol))
    conn.commit()
    conn.close()

def get_user_profile(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT role, expiry_date, usage_count, registered_date FROM users WHERE user_id=%s", (str(user_id),))
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

# --- 🌟 ระบบจัดการโค้ดโปรโมชั่น (แบบ 1 โค้ดใช้ได้หลายคน) 🌟 ---
def add_promo_code(code, days, max_uses):
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO promo_codes (code, days, max_uses, current_uses, used_by) VALUES (%s, %s, %s, 0, '')", (code, days, max_uses))
        conn.commit()
        return True
    except psycopg2.IntegrityError:
        conn.rollback()
        return False
    finally:
        conn.close()

def redeem_code(user_id, code):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT days, max_uses, current_uses, used_by FROM promo_codes WHERE code=%s", (code,))
    result = c.fetchone()
    
    if result:
        days, max_uses, current_uses, used_by = result
        used_by_list = used_by.split(',') if used_by else []
        
        # 1. เช็กว่าคนนี้เคยใช้โค้ดนี้ไปแล้วหรือยัง
        if str(user_id) in used_by_list:
            conn.close()
            return False, "already_used_by_you", None
            
        # 2. เช็กว่าโควต้าโค้ดนี้เต็มหรือยัง
        if current_uses < max_uses:
            new_used_by = used_by + f"{user_id},"
            # อัปเดตยอดคนใช้ และรายชื่อคนใช้
            c.execute("UPDATE promo_codes SET current_uses = current_uses + 1, used_by=%s WHERE code=%s", (new_used_by, code))
            conn.commit()
            
            # เติมวัน VIP ทันที
            expiry = add_vip(user_id, days)
            conn.close()
            return True, days, expiry
        else:
            conn.close()
            return False, "fully_used", None
            
    conn.close()
    return False, "invalid", None
