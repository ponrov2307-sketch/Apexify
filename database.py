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
                 (user_id TEXT PRIMARY KEY, status TEXT, registered_date TEXT, role TEXT, expiry_date TEXT, usage_count INTEGER DEFAULT 0, username TEXT DEFAULT 'Unknown')''')
    # Keep old deployments compatible by adding missing column if table already exists.
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT DEFAULT 'Unknown'")
    
    # 🌟 อัปเดตตารางเพิ่ม role_type เพื่อแยกโค้ดโปรโมชั่น VIP / PRO
    c.execute('''CREATE TABLE IF NOT EXISTS promo_codes 
                 (code TEXT PRIMARY KEY, days INTEGER, max_uses INTEGER DEFAULT 1, current_uses INTEGER DEFAULT 0, used_by TEXT DEFAULT '', role_type TEXT DEFAULT 'vip')''')
                 
    # 🌟 ฐานข้อมูลเก็บสลิปที่ใช้แล้ว ป้องกันการส่งซ้ำ
    c.execute('''CREATE TABLE IF NOT EXISTS used_slips 
                 (ref_no TEXT PRIMARY KEY, user_id TEXT, date_used TEXT)''')

    # 🌟 ตารางใหม่: เก็บประวัติสัญญาณเพื่อใช้วัดความแม่นยำ (Accuracy Log)
    c.execute('''CREATE TABLE IF NOT EXISTS alert_logs 
                 (id SERIAL PRIMARY KEY, symbol TEXT, alert_type TEXT, price_at_alert REAL, timestamp TEXT)''')
                 
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

def register_user(user_id, username="Unknown"):
    """ลงทะเบียนผู้ใช้ใหม่ พร้อมอัปเดตชื่อล่าสุด (ถ้ามี)"""
    conn = get_connection()
    c = conn.cursor()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        # 🌟 ใช้ ON CONFLICT DO UPDATE เพื่อให้คนเก่าที่เคยกด /start ไปแล้ว ถ้ากดซ้ำ ชื่อจะถูกอัปเดตเข้า DB ทันที
        c.execute("""
            INSERT INTO users (user_id, status, registered_date, role, usage_count, username) 
            VALUES (%s, %s, %s, %s, %s, %s) 
            ON CONFLICT (user_id) 
            DO UPDATE SET username = EXCLUDED.username
        """, (str(user_id), 'active', now_str, 'free', 0, username))
        conn.commit()
    except Exception as e:
        print(f"❌ Error registering user: {e}")
        conn.rollback()
    finally:
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

# ==========================================
# 🌟 ฟังก์ชันจัดการแบนผู้ใช้ (Blacklist)
# ==========================================
def ban_user(user_id):
    """แบนผู้ใช้โดยเปลี่ยน status เป็น 'banned'"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE users SET status='banned' WHERE user_id=%s", (str(user_id),))
    conn.commit()
    conn.close()

def unban_user(user_id):
    """ปลดแบนผู้ใช้โดยเปลี่ยน status กลับเป็น 'active'"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE users SET status='active' WHERE user_id=%s", (str(user_id),))
    conn.commit()
    conn.close()

def is_user_banned(user_id):
    """ตรวจสอบว่าผู้ใช้นี้ถูกแบนหรือไม่"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT status FROM users WHERE user_id=%s", (str(user_id),))
    result = c.fetchone()
    conn.close()
    if result and result[0] == 'banned':
        return True
    return False

# ==========================================
# 🌟 ฟังก์ชันจัดการประวัติสัญญาณ (Alert Logs) - ใช้สรุปความแม่นยำ
# ==========================================
def log_alert(symbol, alert_type, price):
    """บันทึกสัญญาณที่ส่งออกไปเพื่อใช้วัดผลความแม่นยำภายหลัง"""
    conn = get_connection()
    c = conn.cursor()
    try:
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute("INSERT INTO alert_logs (symbol, alert_type, price_at_alert, timestamp) VALUES (%s, %s, %s, %s)",
                  (str(symbol), str(alert_type), float(price), now_str))
        conn.commit()
    except psycopg2.Error as e:
        print(f"❌ Error logging alert: {e}")
        conn.rollback()
    finally:
        conn.close()
# ==========================================
# 🌟 ระบบชวนเพื่อน (Referral System)
# ==========================================
def init_new_features_db():
    """สร้างตารางใหม่สำหรับ PostgreSQL"""
    conn = get_connection()
    c = conn.cursor()
    # เปลี่ยน AUTOINCREMENT เป็น SERIAL
    c.execute('''CREATE TABLE IF NOT EXISTS user_price_alerts
                 (id SERIAL PRIMARY KEY,
                  user_id TEXT,
                  symbol TEXT,
                  target_price REAL,
                  condition TEXT, 
                  is_active INTEGER DEFAULT 1)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS referrals
                 (id SERIAL PRIMARY KEY,
                  referrer_id TEXT,
                  referred_id TEXT UNIQUE,
                  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    # 🌟 [เพิ่มใหม่ตรงนี้] สร้างตารางเก็บพอร์ตหุ้น Apex Wealth Master
    c.execute('''CREATE TABLE IF NOT EXISTS portfolios 
                 (id SERIAL PRIMARY KEY,
                  user_id TEXT REFERENCES users(user_id) ON DELETE CASCADE,
                  ticker TEXT NOT NULL,
                  shares NUMERIC NOT NULL,
                  avg_cost NUMERIC NOT NULL,
                  asset_group TEXT DEFAULT 'ALL',
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

def process_referral(referrer_id, new_user_id):
    """จัดการเมื่อมีคนกดลิงก์ชวนเพื่อนเข้ามาใช้งานบอทครั้งแรก"""
    conn = get_connection()
    c = conn.cursor()
    try:
        # ใช้ %s แทน ? สำหรับ PostgreSQL
        c.execute("SELECT user_id FROM users WHERE user_id = %s", (new_user_id,))
        if c.fetchone(): 
            return False 
        
        c.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (%s, %s)", (referrer_id, new_user_id))
        
        c.execute("SELECT role, expiry_date FROM users WHERE user_id = %s", (referrer_id,))
        row = c.fetchone()
        if row:
            role = row[0]
            if role in ['vip', 'pro']:
                # บวกเวลา 1 วัน สำหรับ PostgreSQL
                c.execute("UPDATE users SET expiry_date = expiry_date + INTERVAL '1 day' WHERE user_id = %s", (referrer_id,))
            else:
                # ใช้ GREATEST แทน MAX
                c.execute("UPDATE users SET usage_count = GREATEST(0, usage_count - 3) WHERE user_id = %s", (referrer_id,))
        conn.commit()
        return True
    except Exception as e:
        print(f"Referral Error: {e}")
        return False
    finally:
        conn.close()

def get_referral_stats(user_id):
    """ดูว่าชวนเพื่อนไปแล้วกี่คน"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = %s", (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count

# ==========================================
# 🌟 ระบบตั้งเตือนราคาส่วนตัว (Custom Price Alerts)
# ==========================================
def add_price_alert_db(user_id, symbol, target_price, condition):
    """เพิ่มการตั้งเตือนราคา"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO user_price_alerts (user_id, symbol, target_price, condition) VALUES (%s, %s, %s, %s)",
              (user_id, symbol, target_price, condition))
    conn.commit()
    conn.close()

def get_user_price_alerts_db(user_id):
    """ดึงรายการตั้งเตือนราคา"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, symbol, target_price, condition FROM user_price_alerts WHERE user_id = %s AND is_active = 1", (user_id,))
    alerts = c.fetchall()
    conn.close()
    return alerts

def remove_price_alert_db(user_id, alert_id):
    """ลบการตั้งเตือนราคา"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE user_price_alerts SET is_active = 0 WHERE id = %s AND user_id = %s", (alert_id, user_id))
    conn.commit()
    conn.close()

def get_all_active_price_alerts():
    """ดึงการตั้งเตือนทั้งหมดให้ระบบ alert_system คอยเช็คราคา"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, user_id, symbol, target_price, condition FROM user_price_alerts WHERE is_active = 1")
    alerts = c.fetchall()
    conn.close()
    return alerts

def deactivate_price_alert(alert_id):
    """ปิดการแจ้งเตือนเมื่อราคาถึงเป้าหมายแล้ว"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE user_price_alerts SET is_active = 0 WHERE id = %s", (alert_id,))
    conn.commit()
    conn.close()
# ==========================================
# 🌟 ระบบ Auto-Downgrade (ลดขั้นคนหมดอายุอัตโนมัติ)
# ==========================================
def auto_downgrade_expired_users():
    """ปรับสถานะคนที่หมดอายุให้กลับเป็นสายฟรีอัตโนมัติ"""
    conn = get_connection()
    c = conn.cursor()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        # สั่งเปลี่ยน role เป็น free สำหรับคนที่หมดอายุแล้ว
        c.execute("UPDATE users SET role = 'free' WHERE role IN ('vip', 'pro') AND expiry_date < %s", (now_str,))
        conn.commit()
    except Exception as e:
        print(f"❌ Auto-Downgrade Error: {e}")
        conn.rollback()
    finally:
        conn.close()
# ==========================================
# 🌟 [เพิ่มใหม่] ระบบจัดการพอร์ตลงทุน (Apex Wealth Master)
# ==========================================
def add_portfolio_stock(user_id, ticker, shares, avg_cost):
    """บันทึกหุ้นเข้าพอร์ต"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO portfolios (user_id, ticker, shares, avg_cost) VALUES (%s, %s, %s, %s)",
              (str(user_id), ticker.upper(), float(shares), float(avg_cost)))
    conn.commit()
    conn.close()

def get_user_portfolio(user_id):
    """ดึงหุ้นทั้งหมดในพอร์ตของลูกค้ารายนั้น"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT ticker, shares, avg_cost FROM portfolios WHERE user_id = %s", (str(user_id),))
    res = c.fetchall()
    conn.close()
    
    # แปลงผลลัพธ์ให้ออกมาเป็น List of Dict (เพื่อให้ดึงค่าง่ายๆ)
    portfolio = []
    for row in res:
        portfolio.append({
            'ticker': row[0],
            'shares': float(row[1]),
            'avg_cost': float(row[2])
        })
    return portfolio
