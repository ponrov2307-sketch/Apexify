import subprocess
from datetime import datetime

def auto_git_push():
    try:
        # 1. เพิ่มไฟล์ทั้งหมด
        subprocess.run(["git", "add", "."], check=True)
        
        # 2. Commit พร้อมใส่เวลาปัจจุบันเพื่อให้รู้ว่าอัปเดตตอนไหน
        commit_message = f"Apexify Auto Update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        subprocess.run(["git", "commit", "-m", commit_message], check=True)
        
        # 3. Push ขึ้น GitHub
        subprocess.run(["git", "push"], check=True)
        
        print(f"✅ [Apexify] อัปโหลดโค้ดเรียบร้อยแล้วเมื่อเวลา: {datetime.now().strftime('%H:%M:%S')}")
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาด: {e}")

if __name__ == "__main__":
    auto_git_push()