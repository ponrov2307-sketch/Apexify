import subprocess
import time
from datetime import datetime

# ตั้งค่าเวลา (วินาที) เช่น 600 วินาที = 10 นาที
SYNC_INTERVAL = 600 

def auto_git_push():
    try:
        # 1. Add ไฟล์ที่มีการเปลี่ยนแปลงทั้งหมด
        subprocess.run(["git", "add", "."], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # ตรวจสอบว่ามีการเปลี่ยนแปลงหรือไม่ (ถ้าไม่มีจะได้ไม่ error)
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if not status.stdout.strip():
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⏳ ไม่มีไฟล์เปลี่ยนแปลง ข้ามการอัปโหลด...")
            return

        # 2. Commit พร้อมแนบเวลาปัจจุบัน
        commit_message = f"Apexify Auto Sync: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        subprocess.run(["git", "commit", "-m", commit_message], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # 3. Push ขึ้น GitHub
        subprocess.run(["git", "push"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        print(f"✅ [{datetime.now().strftime('%H:%M:%S')}] อัปโหลดโค้ด Apexify ขึ้น GitHub สำเร็จ!")
    except subprocess.CalledProcessError as e:
        print(f"❌ [{datetime.now().strftime('%H:%M:%S')}] เกิดข้อผิดพลาดในการอัปโหลด: โปรดตรวจสอบ Git ของคุณ")

if __name__ == "__main__":
    print(f"🚀 เริ่มระบบ Auto Git Push สำหรับ Apexify (อัปเดตทุกๆ {SYNC_INTERVAL//60} นาที)")
    print("กด Ctrl+C เพื่อหยุดการทำงาน")
    print("-" * 50)
    
    while True:
        auto_git_push()
        time.sleep(SYNC_INTERVAL)