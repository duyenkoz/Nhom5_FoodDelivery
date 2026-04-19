import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request
import uuid

PARTNER_CODE = os.getenv("MOMO_PARTNER_CODE", "MOMO")
ACCESS_KEY = os.getenv("MOMO_ACCESS_KEY", "F8BBA842ECF85")
SECRET_KEY = os.getenv("MOMO_SECRET_KEY", "K951B6PE1waDMi640xX08PD3vg6EkVlz")
ENDPOINT = os.getenv("MOMO_ENDPOINT", "https://test-payment.momo.vn/v2/gateway/api/create")


def create_momo_payment(amount, order_info, return_url, ipn_url, order_id=None, extra_data=None):
    momo_order_id = str(order_id or uuid.uuid4())
    request_id = str(uuid.uuid4())
    request_type = "captureWallet"
    extra_data_str = json.dumps(extra_data or {}, ensure_ascii=False) if extra_data else ""

    raw_signature = (
        f"accessKey={ACCESS_KEY}"
        f"&amount={int(amount)}"
        f"&extraData={extra_data_str}"
        f"&ipnUrl={ipn_url}"
        f"&orderId={momo_order_id}"
        f"&orderInfo={order_info}"
        f"&partnerCode={PARTNER_CODE}"
        f"&redirectUrl={return_url}"
        f"&requestId={request_id}"
        f"&requestType={request_type}"
    )

    signature = hmac.new(
        SECRET_KEY.encode("utf-8"),
        raw_signature.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    payload = {
        "partnerCode": PARTNER_CODE,
        "accessKey": ACCESS_KEY,
        "requestId": request_id,
        "amount": str(int(amount)),
        "orderId": momo_order_id,
        "orderInfo": order_info,
        "redirectUrl": return_url,
        "ipnUrl": ipn_url,
        "extraData": extra_data_str,
        "requestType": request_type,
        "signature": signature,
        "lang": "vi",
    }

    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw_body = response.read().decode("utf-8")
            return json.loads(raw_body)
    except urllib.error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        try:
            result = json.loads(raw_body) if raw_body else {}
        except json.JSONDecodeError:
            result = {"raw_body": raw_body}
        result.setdefault("resultCode", exc.code)
        result.setdefault("message", f"MoMo API trả về lỗi HTTP {exc.code}")
        result["http_status"] = exc.code
        result["request"] = payload
        return result
    except urllib.error.URLError as exc:
        return {
            "resultCode": -1,
            "message": f"Không kết nối được tới MoMo: {getattr(exc, 'reason', exc)}",
            "request": payload,
        }
    except TimeoutError:
        return {
            "resultCode": -1,
            "message": "MoMo phản hồi quá lâu, vui lòng thử lại.",
            "request": payload,
        }
    except json.JSONDecodeError:
        return {
            "resultCode": -1,
            "message": "MoMo trả về dữ liệu không hợp lệ.",
            "request": payload,
        }
