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
    
    # 🌟 อัปเดตตารางเพิ่ม role_type เพื่อแยกโค้ดโปรโมชั่น VIP / PRO
    c.execute('''CREATE TABLE IF NOT EXISTS promo_codes 
                 (code TEXT PRIMARY KEY, days INTEGER, max_uses INTEGER DEFAULT 1, current_uses INTEGER DEFAULT 0, used_by TEXT DEFAULT '', role_type TEXT DEFAULT 'vip')''')
                 
    # 🌟 ฐานข้อมูลเก็บสลิปที่ใช้แล้ว ป้องกันการส่งซ้ำ
    c.execute('''CREATE TABLE IF NOT EXISTS used_slips 
                 (ref_no TEXT PRIMARY KEY, user_id TEXT, date_used TEXT)''')
                 
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

def add_subscription(user_id, role='vip', days=30):
    conn = get_connection()
    c = conn.cursor()
    
    c.execute("SELECT role, expiry_date FROM users WHERE user_id=%s", (str(user_id),))
    result = c.fetchone()
    
    now = datetime.now()
    new_expiry = now + timedelta(days=days)
    
    if result and result[1]:
        old_role = result[0]
        try:
            old_expiry = datetime.strptime(result[1], '%Y-%m-%d %H:%M:%S')
            # ทบวันให้ถ้าเป็นการต่ออายุแพ็กเกจเดิม หรืออัปเกรดจาก VIP ไป PRO
            if old_expiry > now and (old_role == role or role == 'pro'):
                new_expiry = old_expiry + timedelta(days=days) 
        except:
            pass
            
    expiry_str = new_expiry.strftime('%Y-%m-%d %H:%M:%S')
    c.execute("UPDATE users SET role=%s, expiry_date=%s WHERE user_id=%s", (role, expiry_str, str(user_id)))
    conn.commit()
    conn.close()
    return expiry_str

def check_subscription(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT role, expiry_date FROM users WHERE user_id=%s", (str(user_id),))
    result = c.fetchone()
    conn.close()
    if result:
        role, expiry_date = result
        if role in ['vip', 'pro'] and expiry_date:
            expiry = datetime.strptime(expiry_date, '%Y-%m-%d %H:%M:%S')
            if datetime.now() < expiry:
                return role
    return 'free'

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

def add_promo_code(code, days, max_uses, role_type='vip'):
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO promo_codes (code, days, max_uses, current_uses, used_by, role_type) VALUES (%s, %s, %s, 0, '', %s)", (code, days, max_uses, role_type))
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
    c.execute("SELECT days, max_uses, current_uses, used_by, role_type FROM promo_codes WHERE code=%s", (code,))
    result = c.fetchone()
    
    if result:
        days, max_uses, current_uses, used_by, role_type = result
        used_by_list = used_by.split(',') if used_by else []
        
        if str(user_id) in used_by_list:
            conn.close()
            return False, "already_used_by_you", None, None
            
        if current_uses < max_uses:
            new_used_by = used_by + f"{user_id},"
            c.execute("UPDATE promo_codes SET current_uses = current_uses + 1, used_by=%s WHERE code=%s", (new_used_by, code))
            conn.commit()
            
            expiry = add_subscription(user_id, role_type, days)
            conn.close()
            return True, days, expiry, role_type
        else:
            conn.close()
            return False, "fully_used", None, None
            
    conn.close()

def get_user_stats():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT role, COUNT(*) FROM users GROUP BY role")
    results = c.fetchall()
    conn.close()
    
    stats = {'free': 0, 'vip': 0, 'pro': 0}
    total = 0
    for row in results:
        role = row[0]
        count = row[1]
        if role in stats:
            stats[role] = count
        total += count
        
    return stats, total

# ==========================================
# 🌟 ฟังก์ชันจัดการสลิปซ้ำ
# ==========================================
def check_slip_used(ref_no):
    """ตรวจสอบว่าเลขที่อ้างอิงนี้เคยถูกใช้หรือยัง"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT user_id FROM used_slips WHERE ref_no=%s", (str(ref_no),))
    result = c.fetchone()
    conn.close()
    return result is not None

def mark_slip_used(ref_no, user_id):
    """บันทึกเลขที่อ้างอิงสลิปลงฐานข้อมูลเมื่อใช้สำเร็จ"""
    conn = get_connection()
    c = conn.cursor()
    try:
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute("INSERT INTO used_slips (ref_no, user_id, date_used) VALUES (%s, %s, %s)", (str(ref_no), str(user_id), now_str))
        conn.commit()
        return True
    except psycopg2.IntegrityError:
        conn.rollback()
        return False
    finally:
        conn.close()
