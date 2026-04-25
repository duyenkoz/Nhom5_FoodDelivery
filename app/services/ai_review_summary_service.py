import json
from typing import Any

from flask import current_app
from sqlalchemy.orm import selectinload

from app.models import Customer, Review

try:
    from google import genai
    from google.genai import types
except ImportError:  # pragma: no cover - optional dependency in local env
    genai = None
    types = None


SUMMARY_ERROR_MESSAGE = "Chưa thể tạo tóm tắt AI lúc này. Vui lòng thử lại sau."
SUMMARY_CONFIG_ERROR_MESSAGE = "Tính năng tóm tắt AI hiện chưa được cấu hình đầy đủ."


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


def _query_reviews_for_summary(restaurant_id, limit):
    reviews = (
        Review.query.options(selectinload(Review.customer).selectinload(Customer.user))
        .filter(Review.restaurant_id == restaurant_id)
        .filter(Review.rating.isnot(None))
        .order_by(Review.review_date.desc(), Review.review_id.desc())
        .limit(limit)
        .all()
    )

    rows = []
    for review in reviews:
        customer_name = "Khách ẩn danh"
        if review.customer and review.customer.user:
            customer_name = (
                _clean(review.customer.user.display_name)
                or _clean(review.customer.user.username)
                or customer_name
            )

        rows.append(
            {
                "rating": int(review.rating or 0),
                "comment": _clean(review.comment),
                "review_date_text": review.review_date.strftime("%H:%M %d/%m/%Y") if review.review_date else "",
                "customer_name": customer_name,
            }
        )
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
        overview = "Các đánh giá gần đây cho thấy trải nghiệm của khách hàng có cả điểm tích cực lẫn vài góp ý cần lưu ý."

    return {
        "overview": overview,
        "strengths": normalized_strengths,
        "improvements": normalized_improvements,
    }


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
                    "Nhiệm vụ của bạn là tóm tắt các đánh giá được cung cấp, chỉ sử dụng dữ liệu trong input, "
                    "không suy diễn thêm thông tin không có. Viết tiếng Việt ngắn gọn, trung tính, hữu ích cho chủ nhà hàng. "
                    "Trả về JSON hợp lệ với đúng các khóa: overview, strengths, improvements. "
                    "overview là chuỗi ngắn 1-2 câu. strengths và improvements là mảng chuỗi ngắn, tối đa 3 ý mỗi mảng. "
                    "Nếu chưa đủ dữ liệu cho một mảng thì trả mảng rỗng."
                ),
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )
    except Exception as exc:  # pragma: no cover - network dependent
        current_app.logger.exception("Gemini review summary request failed: %s", exc)
        raise ReviewSummaryRequestError(SUMMARY_ERROR_MESSAGE) from exc

    response_text = _clean(getattr(response, "text", ""))
    if not response_text:
        raise ReviewSummaryRequestError(SUMMARY_ERROR_MESSAGE)

    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        current_app.logger.exception("Gemini review summary returned invalid JSON: %s", exc)
        raise ReviewSummaryRequestError(SUMMARY_ERROR_MESSAGE) from exc

    return {
        "summary": _normalize_summary_payload(payload),
        "review_count_used": len(reviews),
        "threshold": settings["min_reviews"],
        "model": settings["model"],
    }
