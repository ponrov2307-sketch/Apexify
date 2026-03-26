"""สร้าง PromptPay QR Code ตาม EMVCo Standard"""
import io
from typing import Optional

import qrcode


def _crc16(data: bytes) -> str:
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF)"""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return f"{crc:04X}"


def _tlv(tag: str, value: str) -> str:
    return f"{tag}{len(value):02d}{value}"


def _format_promptpay_id(raw_id: str) -> str:
    """แปลง PromptPay ID → รูปแบบ EMVCo (phone: 0066..., citizen: 13 digit)"""
    cleaned = raw_id.replace("-", "").replace(" ", "")
    if len(cleaned) == 10 and cleaned.startswith("0"):
        # Thai phone: 0812345678 → 0066812345678
        return "0066" + cleaned[1:]
    if len(cleaned) == 13:
        # Citizen ID (13 digits) → as-is
        return cleaned
    return cleaned


def generate_promptpay_qr(promptpay_id: str, amount: Optional[float] = None) -> Optional[io.BytesIO]:
    """สร้าง PromptPay QR Code → BytesIO (PNG)

    Args:
        promptpay_id: เบอร์โทร (0812345678) หรือเลขบัตรปชช. (13 หลัก)
        amount: จำนวนเงิน (None = ไม่ระบุจำนวน)

    Returns:
        BytesIO containing QR PNG image, or None on error
    """
    if not promptpay_id:
        return None

    formatted_id = _format_promptpay_id(promptpay_id)

    # Merchant Account Information (tag 29)
    aid = _tlv("00", "A000000677010111")  # PromptPay AID
    if len(formatted_id) == 13:
        # phone number (0066...)
        merchant_data = aid + _tlv("01", formatted_id)
    else:
        # citizen/tax ID
        merchant_data = aid + _tlv("02", formatted_id)

    # Build payload (without CRC)
    payload = ""
    payload += _tlv("00", "01")           # Payload Format Indicator
    payload += _tlv("01", "11")           # Static QR (11) or Dynamic (12)
    payload += _tlv("29", merchant_data)  # Merchant Account Info
    payload += _tlv("53", "764")          # Transaction Currency (THB)
    payload += _tlv("58", "TH")           # Country Code

    if amount is not None and amount > 0:
        payload += _tlv("01", "12")[:0]   # noop — rewrite tag 01 to dynamic
        # Rebuild with dynamic QR indicator
        payload = ""
        payload += _tlv("00", "01")
        payload += _tlv("01", "12")       # Dynamic QR
        payload += _tlv("29", merchant_data)
        payload += _tlv("53", "764")
        payload += _tlv("54", f"{amount:.2f}")  # Transaction Amount
        payload += _tlv("58", "TH")

    payload += "6304"  # CRC tag + length placeholder
    crc = _crc16(payload.encode("ascii"))
    payload = payload[:-4] + _tlv("63", crc)

    # Generate QR Code image
    try:
        qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=3)
        qr.add_data(payload)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf
    except Exception as e:
        print(f"[PromptPay QR] Error: {e}")
        return None
