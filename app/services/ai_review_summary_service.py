import json
from typing import Any

from flask import current_app
from sqlalchemy.orm import selectinload

from app.models import Customer, Review
from app.utils.time_utils import format_vietnam_datetime, to_vietnam_datetime, vietnam_today

try:
    from google import genai
    from google.genai import types
except ImportError:  # pragma: no cover - optional dependency in local env
    genai = None
    types = None


SUMMARY_ERROR_MESSAGE = "Chưa thể tạo tóm tắt AI lúc này. Vui lòng thử lại sau."
SUMMARY_CONFIG_ERROR_MESSAGE = "Tính năng tóm tắt AI hiện chưa được cấu hình đầy đủ."
IMPROVEMENT_ERROR_MESSAGE = "Chưa thể tạo gợi ý cải thiện bằng AI lúc này. Vui lòng thử lại sau."


class ReviewSummaryConfigError(RuntimeError):
    pass


class ReviewSummaryRequestError(RuntimeError):
    pass


def _clean(value):
    return value.strip() if isinstance(value, str) else ""


def _safe_positive_int(value, default):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return parsed if parsed > 0 else default


def _safe_positive_float(value, default):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return parsed if parsed > 0 else default


def get_ai_review_summary_settings():
    min_reviews = _safe_positive_int(current_app.config.get("AI_REVIEW_SUMMARY_MIN_REVIEWS"), 5)
    max_reviews = _safe_positive_int(current_app.config.get("AI_REVIEW_SUMMARY_MAX_REVIEWS"), 30)
    timeout_seconds = _safe_positive_float(current_app.config.get("AI_REVIEW_SUMMARY_TIMEOUT_SECONDS"), 15)
    api_key = _clean(current_app.config.get("GEMINI_API_KEY"))
    model = _clean(current_app.config.get("GEMINI_MODEL"))
    sdk_available = bool(genai and types)

    if max_reviews < min_reviews:
        max_reviews = min_reviews

    return {
        "api_key": api_key,
        "model": model,
        "sdk_available": sdk_available,
        "enabled": bool(api_key and model and sdk_available),
        "min_reviews": min_reviews,
        "max_reviews": max_reviews,
        "timeout_seconds": timeout_seconds,
    }


def _resolve_customer_name(review):
    customer_name = "Khách ẩn danh"
    if review.customer and review.customer.user:
        customer_name = (
            _clean(review.customer.user.display_name)
            or _clean(review.customer.user.username)
            or customer_name
        )
    return customer_name


def _serialize_review(review):
    return {
        "rating": int(review.rating or 0),
        "comment": _clean(review.comment),
        "review_date_text": format_vietnam_datetime(review.review_date, "%H:%M %d/%m/%Y") if review.review_date else "",
        "customer_name": _resolve_customer_name(review),
    }


def _is_negative_review(review):
    rating = int(review.rating or 0)
    return 1 <= rating <= 2


def _is_in_month(review, year, month):
    local_dt = to_vietnam_datetime(getattr(review, "review_date", None))
    return bool(local_dt and local_dt.year == year and local_dt.month == month)


def _query_reviews_for_summary(restaurant_id, limit):
    reviews = (
        Review.query.options(selectinload(Review.customer).selectinload(Customer.user))
        .filter(Review.restaurant_id == restaurant_id)
        .filter(Review.rating.isnot(None))
        .order_by(Review.review_date.desc(), Review.review_id.desc())
        .limit(limit)
        .all()
    )
    return [_serialize_review(review) for review in reviews]


def query_negative_reviews_for_improvement_insights(restaurant_id, limit, year=None, month=None):
    reference_today = vietnam_today()
    target_year = int(year or reference_today.year)
    target_month = int(month or reference_today.month)

    reviews = (
        Review.query.options(selectinload(Review.customer).selectinload(Customer.user))
        .filter(Review.restaurant_id == restaurant_id)
        .filter(Review.rating.isnot(None))
        .order_by(Review.review_date.desc(), Review.review_id.desc())
        .all()
    )

    rows = []
    for review in reviews:
        if not _is_negative_review(review):
            continue
        if not _is_in_month(review, target_year, target_month):
            continue
        rows.append(_serialize_review(review))
        if len(rows) >= limit:
            break

    return rows


def _build_summary_prompt(restaurant_name, review_rows):
    serialized_reviews = []
    for index, review in enumerate(review_rows, start=1):
        comment_text = review["comment"] or "Không có bình luận chi tiết."
        serialized_reviews.append(
            (
                f"{index}. {review['rating']} sao | "
                f"Khách: {review['customer_name']} | "
                f"Thời gian: {review['review_date_text'] or 'Không rõ'} | "
                f"Nhận xét: {comment_text}"
            )
        )

    return "\n".join(
        [
            f"Nhà hàng: {restaurant_name or 'Nhà hàng hiện tại'}",
            f"Số lượng đánh giá dùng để tóm tắt: {len(review_rows)}",
            "Dữ liệu đánh giá:",
            *serialized_reviews,
        ]
    )


def _build_improvement_prompt(restaurant_name, review_rows, month_label):
    serialized_reviews = []
    for index, review in enumerate(review_rows, start=1):
        comment_text = review["comment"] or "Không có bình luận chi tiết."
        serialized_reviews.append(
            (
                f"{index}. {review['rating']} sao | "
                f"Khách: {review['customer_name']} | "
                f"Thời gian: {review['review_date_text'] or 'Không rõ'} | "
                f"Nhận xét: {comment_text}"
            )
        )

    return "\n".join(
        [
            f"Nhà hàng: {restaurant_name or 'Nhà hàng hiện tại'}",
            f"Giai đoạn phân tích: {month_label}",
            f"Số lượng đánh giá xấu dùng để phân tích: {len(review_rows)}",
            "Dữ liệu đánh giá xấu:",
            *serialized_reviews,
        ]
    )


def _build_client(settings):
    if not settings["sdk_available"]:
        raise ReviewSummaryConfigError(SUMMARY_CONFIG_ERROR_MESSAGE)
    if not settings["api_key"] or not settings["model"]:
        raise ReviewSummaryConfigError(SUMMARY_CONFIG_ERROR_MESSAGE)

    http_options = types.HttpOptions(timeout=int(settings["timeout_seconds"] * 1000))
    return genai.Client(api_key=settings["api_key"], http_options=http_options)


def _normalize_summary_payload(payload: Any):
    if not isinstance(payload, dict):
        raise ReviewSummaryRequestError(SUMMARY_ERROR_MESSAGE)

    overview = _clean(payload.get("overview"))
    strengths = payload.get("strengths") if isinstance(payload.get("strengths"), list) else []
    improvements = payload.get("improvements") if isinstance(payload.get("improvements"), list) else []

    normalized_strengths = [_clean(item) for item in strengths if _clean(item)][:3]
    normalized_improvements = [_clean(item) for item in improvements if _clean(item)][:3]

    if not overview:
        overview = "Đánh giá gần đây cho thấy trải nghiệm của khách hàng có cả điểm tích cực lẫn những nội dung cần lưu ý."

    return {
        "overview": overview,
        "strengths": normalized_strengths,
        "improvements": normalized_improvements,
    }


def _normalize_improvement_payload(payload: Any):
    if not isinstance(payload, dict):
        raise ReviewSummaryRequestError(IMPROVEMENT_ERROR_MESSAGE)

    overview = _clean(payload.get("overview"))
    issues = payload.get("issues") if isinstance(payload.get("issues"), list) else []
    actions = payload.get("actions") if isinstance(payload.get("actions"), list) else []

    normalized_issues = [_clean(item) for item in issues if _clean(item)][:3]
    normalized_actions = [_clean(item) for item in actions if _clean(item)][:3]

    if not overview:
        overview = "Đánh giá xấu trong tháng này cho thấy nhà hàng cần ưu tiên xử lý một vài vấn đề lặp lại."

    return {
        "overview": overview,
        "issues": normalized_issues,
        "actions": normalized_actions,
    }


def _parse_json_response(response_text, error_message):
    text = _clean(response_text)
    if not text:
        raise ReviewSummaryRequestError(error_message)

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        current_app.logger.exception("Gemini review AI returned invalid JSON: %s", exc)
        raise ReviewSummaryRequestError(error_message) from exc


def generate_restaurant_review_summary(restaurant_id, restaurant_name=""):
    settings = get_ai_review_summary_settings()
    reviews = _query_reviews_for_summary(restaurant_id, settings["max_reviews"])
    if len(reviews) < settings["min_reviews"]:
        raise ReviewSummaryRequestError(
            f"Cần ít nhất {settings['min_reviews']} đánh giá để tạo tóm tắt AI."
        )

    prompt = _build_summary_prompt(restaurant_name, reviews)
    client = _build_client(settings)

    try:
        response = client.models.generate_content(
            model=settings["model"],
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "Bạn là trợ lý phân tích phản hồi khách hàng cho nhà hàng. "
                    "Chỉ sử dụng dữ liệu trong input, không suy diễn thêm thông tin không có. "
                    "Trả về JSON hợp lệ với các khóa: overview, strengths, improvements. "
                    "overview là 1-2 câu ngắn. strengths và improvements là mảng chuỗi ngắn, tối đa 3 ý mỗi mảng. "
                    "Nếu chưa đủ dữ liệu cho một mảng thì trả mảng rỗng."
                ),
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )
    except Exception as exc:  # pragma: no cover - network dependent
        current_app.logger.exception("Gemini review summary request failed: %s", exc)
        raise ReviewSummaryRequestError(SUMMARY_ERROR_MESSAGE) from exc

    payload = _parse_json_response(getattr(response, "text", ""), SUMMARY_ERROR_MESSAGE)
    return {
        "summary": _normalize_summary_payload(payload),
        "review_count_used": len(reviews),
        "threshold": settings["min_reviews"],
        "model": settings["model"],
    }


def generate_restaurant_review_improvement_insights(restaurant_id, restaurant_name="", year=None, month=None):
    settings = get_ai_review_summary_settings()
    review_rows = query_negative_reviews_for_improvement_insights(
        restaurant_id,
        settings["max_reviews"],
        year=year,
        month=month,
    )
    if len(review_rows) < settings["min_reviews"]:
        raise ReviewSummaryRequestError(
            f"Cần ít nhất {settings['min_reviews']} đánh giá xấu để tạo gợi ý AI."
        )

    reference_today = vietnam_today()
    target_year = int(year or reference_today.year)
    target_month = int(month or reference_today.month)
    month_label = f"Tháng {target_month}/{target_year}"
    prompt = _build_improvement_prompt(restaurant_name, review_rows, month_label)
    client = _build_client(settings)

    try:
        response = client.models.generate_content(
            model=settings["model"],
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "Bạn là trợ lý phân tích đánh giá xấu cho nhà hàng. "
                    "Chỉ sử dụng dữ liệu trong input, không suy diễn thêm thông tin không có. "
                    "Trả về JSON hợp lệ với các khóa: overview, issues, actions. "
                    "overview là 1-2 câu ngắn. issues là tối đa 3 vấn đề nổi bật lặp lại trong đánh giá xấu. "
                    "actions là tối đa 3 đề xuất cải thiện cụ thể, ưu tiên cách thực hiện rõ ràng cho chủ nhà hàng."
                ),
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )
    except Exception as exc:  # pragma: no cover - network dependent
        current_app.logger.exception("Gemini review improvement request failed: %s", exc)
        raise ReviewSummaryRequestError(IMPROVEMENT_ERROR_MESSAGE) from exc

    payload = _parse_json_response(getattr(response, "text", ""), IMPROVEMENT_ERROR_MESSAGE)
    return {
        "insights": _normalize_improvement_payload(payload),
        "review_count_used": len(review_rows),
        "threshold": settings["min_reviews"],
        "model": settings["model"],
        "month": f"{target_year:04d}-{target_month:02d}",
    }
