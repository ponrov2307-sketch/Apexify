import re
from typing import Any

import requests

from config import SLIPOK_API_KEY, SLIPOK_BRANCH_ID, SLIPOK_TIMEOUT_SECONDS


SLIPOK_ENDPOINT_TEMPLATE = "https://api.slipok.com/api/line/apikey/{branch_id}"


def _blank_result(status: str, message: str, provider_code: int | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "provider_code": provider_code,
        "message": message,
        "trans_ref": "",
        "amount": 0.0,
        "receiver_display_name": "",
        "sender_display_name": "",
        "receiving_bank": "",
        "sending_bank": "",
        "trans_timestamp": "",
        "retry_after_minutes": None,
        "http_status": None,
    }


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _extract_retry_after_minutes(message: str, payload: dict[str, Any]) -> int | None:
    delay = payload.get("delay")
    if delay is not None:
        try:
            return int(delay)
        except (TypeError, ValueError):
            pass

    match = re.search(r"(\d+)", str(message or ""))
    if not match:
        return None

    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _normalize_slip_data(result: dict[str, Any], slip_data: dict[str, Any]) -> dict[str, Any]:
    sender = slip_data.get("sender") or {}
    receiver = slip_data.get("receiver") or {}

    result["trans_ref"] = str(slip_data.get("transRef") or "").strip()
    result["amount"] = _as_float(slip_data.get("amount"))
    result["receiver_display_name"] = str(receiver.get("displayName") or receiver.get("name") or "").strip()
    result["sender_display_name"] = str(sender.get("displayName") or sender.get("name") or "").strip()
    result["receiving_bank"] = str(slip_data.get("receivingBank") or "").strip()
    result["sending_bank"] = str(slip_data.get("sendingBank") or "").strip()
    result["trans_timestamp"] = str(slip_data.get("transTimestamp") or "").strip()
    return result


def _classify_error(code: int | None, message: str, payload: dict[str, Any]) -> tuple[str, int | None]:
    if code == 1012:
        return "duplicate", None
    if code == 1014:
        return "receiver_mismatch", None
    if code == 1010:
        return "delayed", _extract_retry_after_minutes(message, payload)
    if code in {1006, 1007, 1008, 1011, 1005, 1000}:
        return "invalid_slip", None
    if code == 1013:
        return "amount_mismatch", None
    if code in {1002, 1003, 1004}:
        return "auth_or_quota_error", None
    if code == 1009:
        return "provider_error", None
    return "provider_error", None


def verify_payment_slip(image_bytes: bytes, filename: str = "slip.jpg") -> dict[str, Any]:
    if not SLIPOK_BRANCH_ID or not SLIPOK_API_KEY:
        return _blank_result(
            "config_error",
            "SlipOK configuration is missing. Please set SLIPOK_BRANCH_ID and SLIPOK_API_KEY.",
        )

    result = _blank_result("provider_error", "SlipOK verification failed.")
    url = SLIPOK_ENDPOINT_TEMPLATE.format(branch_id=SLIPOK_BRANCH_ID)
    headers = {"x-authorization": SLIPOK_API_KEY}
    files = {"files": (filename, image_bytes, "image/jpeg")}
    data = {"log": "true"}

    try:
        response = requests.post(
            url,
            headers=headers,
            files=files,
            data=data,
            timeout=SLIPOK_TIMEOUT_SECONDS,
        )
    except requests.Timeout:
        return _blank_result("network_error", "SlipOK verification timed out.")
    except requests.RequestException as exc:
        return _blank_result("network_error", f"SlipOK verification failed: {exc}")

    result["http_status"] = response.status_code

    try:
        payload = response.json()
    except ValueError:
        result["status"] = "provider_error"
        result["message"] = "SlipOK returned an invalid response."
        return result

    if response.ok and payload.get("success") and isinstance(payload.get("data"), dict):
        result["status"] = "verified"
        result["message"] = str(payload["data"].get("message") or "Verified")
        return _normalize_slip_data(result, payload["data"])

    provider_code = payload.get("code")
    try:
        provider_code = int(provider_code)
    except (TypeError, ValueError):
        provider_code = None

    message = str(payload.get("message") or "Slip verification failed.")
    status, retry_after_minutes = _classify_error(provider_code, message, payload.get("data") or {})
    result["status"] = status
    result["provider_code"] = provider_code
    result["message"] = message
    result["retry_after_minutes"] = retry_after_minutes

    if isinstance(payload.get("data"), dict):
        _normalize_slip_data(result, payload["data"])

    return result
