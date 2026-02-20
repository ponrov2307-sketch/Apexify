import os
from dotenv import load_dotenv

# โหลดค่าจากไฟล์ .env (ถ้ารันบนเครื่องตัวเอง)
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = os.getenv("ADMIN_ID")

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    raise ValueError("❌ Error: กรุณาตั้งค่า TELEGRAM_TOKEN และ GEMINI_API_KEY ในไฟล์ .env หรือ Environment Variables")