import sqlite3
from datetime import datetime

DB_NAME = "apexify.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (user_id TEXT PRIMARY KEY, status TEXT, registered_date TEXT)''')
    conn.commit()
    conn.close()

def register_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, status, registered_date) VALUES (?, ?, ?)", 
              (user_id, 'active', datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()