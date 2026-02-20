import sqlite3
from datetime import datetime, timedelta

DB_NAME = "apexify.db"

def init_db():
    conn = conn = sqlite3.connect(DB_NAME, timeout=10, check_same_thread=False)
    c = conn.cursor()
    # ตารางข้อมูลผู้ใช้งาน
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (user_id TEXT PRIMARY KEY, status TEXT, registered_date TEXT, role TEXT, expiry_date TEXT, usage_count INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()
    init_watchlist_db() # เรียกสร้างตาราง Watchlist ด้วย

def init_watchlist_db():
    conn = sqlite3.connect(DB_NAME, timeout=10, check_same_thread=False)
    c = conn.cursor()
    # ตารางเก็บหุ้นที่ลูกค้าเฝ้าดู
    c.execute('''CREATE TABLE IF NOT EXISTS watchlists 
                 (user_id TEXT, symbol TEXT, PRIMARY KEY (user_id, symbol))''')
    conn.commit()
    conn.close()

def register_user(user_id):
    conn = sqlite3.connect(DB_NAME, timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, status, registered_date, role, usage_count) VALUES (?, ?, ?, ?, ?)", 
              (user_id, 'active', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'free', 0))
    conn.commit()
    conn.close()

def add_vip(user_id, days=30):
    conn = sqlite3.connect(DB_NAME, timeout=10, check_same_thread=False)
    c = conn.cursor()
    expiry = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    c.execute("UPDATE users SET role='vip', expiry_date=? WHERE user_id=?", (expiry, str(user_id)))
    conn.commit()
    conn.close()
    return expiry

def check_vip(user_id):
    conn = sqlite3.connect(DB_NAME, timeout=10, check_same_thread=False)
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
    conn = sqlite3.connect(DB_NAME, timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT usage_count FROM users WHERE user_id=?", (str(user_id),))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

def increment_usage(user_id):
    conn = sqlite3.connect(DB_NAME, timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute("UPDATE users SET usage_count = usage_count + 1 WHERE user_id=?", (str(user_id),))
    conn.commit()
    conn.close()

# --- ระบบ Watchlist ---
def add_watch(user_id, symbol):
    conn = sqlite3.connect(DB_NAME, timeout=10, check_same_thread=False)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO watchlists (user_id, symbol) VALUES (?, ?)", (str(user_id), symbol.upper()))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False # มีหุ้นตัวนี้ในลิสต์อยู่แล้ว
    finally:
        conn.close()

def get_user_watch(user_id):
    conn = sqlite3.connect(DB_NAME, timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT symbol FROM watchlists WHERE user_id=?", (str(user_id),))
    result = c.fetchall()
    conn.close()
    return [row[0] for row in result]

def get_users_watching(symbol):
    conn = sqlite3.connect(DB_NAME, timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT user_id FROM watchlists WHERE symbol=?", (symbol.upper(),))
    result = c.fetchall()
    conn.close()
    return [row[0] for row in result]

def get_all_active_symbols():
    conn = sqlite3.connect(DB_NAME, timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT DISTINCT symbol FROM watchlists")
    result = c.fetchall()
    conn.close()
    return [row[0] for row in result]