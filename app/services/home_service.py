from math import ceil
from urllib.parse import urlencode

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.data.home import get_home_page_data
from app.extensions import db
from app.models import Restaurant, Review
from app.services.location_service import format_distance_km, haversine_distance_km, location_sort_key, normalize_text


HOME_PREVIEW_SIZE = 8
COLLECTION_PAGE_SIZE = 12

SECTION_SUGGESTED = "suggested-dishes"
SECTION_NEARBY = "nearby-restaurants"
SECTION_TOP_RATED = "top-rated-restaurants"

SECTION_META = {
    SECTION_SUGGESTED: {
        "title": "Gợi ý món ăn",
        "empty_title": "Chưa có gợi ý món ăn",
        "empty_description": "Hãy quay lại sau khi có thêm món ăn mới.",
    },
    SECTION_NEARBY: {
        "title": "Quán ăn gần bạn",
        "empty_title": "Chưa tìm thấy quán gần bạn",
        "empty_description": "Hãy cập nhật địa chỉ để xem các nhà hàng gần nhất.",
    },
    SECTION_TOP_RATED: {
        "title": "Nhà hàng đánh giá cao",
        "empty_title": "Chưa có nhà hàng nổi bật",
        "empty_description": "Chưa có dữ liệu đánh giá phù hợp để hiển thị.",
    },
}

PRESENTATION_PRESETS = [
    {
        "rating": "4.8",
        "reviews": "500+",
        "corner_badge": "PROMO",
        "corner_badge_kind": "promo",
        "featured_label": "Hot",
        "featured_kind": "hot",
    },
    {
        "rating": "4.5",
        "reviews": "1.2k",
        "corner_badge": "",
        "corner_badge_kind": "",
        "featured_label": "Hot",
        "featured_kind": "hot",
    },
    {
        "rating": "4.9",
        "reviews": "2k",
        "corner_badge": "",
        "corner_badge_kind": "",
        "featured_label": "Best Seller",
        "featured_kind": "best",
    },
    {
        "rating": "4.7",
        "reviews": "3k",
        "corner_badge": "PROMO",
        "corner_badge_kind": "promo",
        "featured_label": "Hot",
        "featured_kind": "hot",
    },
    {
        "rating": "4.9",
        "reviews": "5k",
        "corner_badge": "",
        "corner_badge_kind": "",
        "featured_label": "Best Seller",
        "featured_kind": "best",
    },
    {
        "rating": "4.3",
        "reviews": "800",
        "corner_badge": "",
        "corner_badge_kind": "",
        "featured_label": "Hot",
        "featured_kind": "hot",
    },
    {
        "rating": "4.6",
        "reviews": "1.5k",
        "corner_badge": "",
        "corner_badge_kind": "",
        "featured_label": "Best Seller",
        "featured_kind": "best",
    },
    {
        "rating": "4.7",
        "reviews": "2.2k",
        "corner_badge": "PROMO",
        "corner_badge_kind": "promo",
        "featured_label": "Hot",
        "featured_kind": "hot",
    },
    {
        "rating": "4.4",
        "reviews": "120",
        "corner_badge": "",
        "corner_badge_kind": "",
        "featured_label": "Best Seller",
        "featured_kind": "best",
    },
    {
        "rating": "5.0",
        "reviews": "10k+",
        "corner_badge": "PROMO",
        "corner_badge_kind": "promo",
        "featured_label": "Hot",
        "featured_kind": "hot",
    },
]


def _clean(value):
    return value.strip() if isinstance(value, str) else ""


def _format_price(value):
    if value is None:
        return "Liên hệ"
    return f"{int(value):,}".replace(",", ".") + " đ"


def _format_address(restaurant):
    address = _clean(restaurant.address)
    area = _clean(restaurant.area)

    if address and area:
        parts = [part.strip() for part in address.split(",") if part.strip()]
        area_aliases = {
            "ho chi minh": ("ho chi minh", "thanh pho ho chi minh", "tp hcm", "tphcm", "hcm"),
            "ha noi": ("ha noi", "thanh pho ha noi", "tp ha noi", "hanoi", "tphn"),
            "da nang": ("da nang", "thanh pho da nang", "tp da nang", "danang", "tpdn"),
            "can tho": ("can tho", "thanh pho can tho", "tp can tho", "cantho", "tpct"),
        }.get(normalize_text(area), (normalize_text(area),))

        while parts:
            tail = normalize_text(parts[-1])
            if any(alias and alias in tail for alias in area_aliases) or "thanh pho" in tail:
                parts.pop()
                continue
            break

        address = ", ".join(parts) if parts else address

    return ", ".join(part for part in [address, area] if part)


def _normalize_image_path(image_value):
    image_value = _clean(image_value)
    if not image_value:
        return "images/restaurant-default.svg"
    if image_value.startswith("/static/"):
        return image_value[len("/static/") :]
    if image_value.startswith(("http://", "https://")):
        return image_value
    if image_value.startswith("/"):
        return image_value.lstrip("/")
    if "/" in image_value:
        return image_value
    return f"uploads/{image_value}"


def _restaurant_title(restaurant):
    if restaurant.user and restaurant.user.display_name:
        return restaurant.user.display_name
    if restaurant.user and restaurant.user.username:
        return restaurant.user.username
    return f"Nhà hàng {restaurant.restaurant_id}"


def _active_dishes(restaurant):
    return [dish for dish in restaurant.dishes if dish.status]


def _first_active_dish(restaurant):
    dishes = _active_dishes(restaurant)
    return dishes[0] if dishes else None


def _restaurant_distance(user_location, restaurant):
    if not user_location:
        return None

    return haversine_distance_km(
        user_location.get("latitude"),
        user_location.get("longitude"),
        restaurant.latitude,
        restaurant.longitude,
    )


def _review_stats_by_restaurant():
    rows = (
        db.session.query(
            Review.restaurant_id.label("restaurant_id"),
            func.avg(Review.rating).label("average_rating"),
            func.count(Review.review_id).label("review_count"),
        )
        .filter(Review.restaurant_id.isnot(None))
        .filter(Review.rating.isnot(None))
        .group_by(Review.restaurant_id)
        .all()
    )
    return {
        row.restaurant_id: {
            "average_rating": round(float(row.average_rating or 0), 1) if row.average_rating is not None else None,
            "review_count": int(row.review_count or 0),
        }
        for row in rows
    }


def _format_review_count(value):
    count = int(value or 0)
    if count >= 1000:
        formatted = f"{count / 1000:.1f}".rstrip("0").rstrip(".")
        return f"{formatted}k"
    return str(count)


def _display_rating(index, review_stats, active_dish_count):
    if review_stats and review_stats.get("review_count"):
        return f"{review_stats['average_rating']:.1f}", _format_review_count(review_stats["review_count"])

    preset = PRESENTATION_PRESETS[index % len(PRESENTATION_PRESETS)]
    synthetic_rating = min(5.0, 4.1 + min(active_dish_count, 9) * 0.1)
    synthetic_reviews = max(60, active_dish_count * 35)
    return f"{synthetic_rating:.1f}", _format_review_count(synthetic_reviews) or preset["reviews"]


def _build_card(restaurant, index, distance_km=None, review_stats=None):
    preset = PRESENTATION_PRESETS[index % len(PRESENTATION_PRESETS)]
    featured_dish = _first_active_dish(restaurant)
    image_value = featured_dish.image if featured_dish and featured_dish.image else restaurant.image
    rating, reviews = _display_rating(index, review_stats, len(_active_dishes(restaurant)))

    return {
        "name": _restaurant_title(restaurant),
        "href": f"/restaurants/{restaurant.restaurant_id}",
        "image_path": _normalize_image_path(image_value),
        "rating": rating,
        "reviews": reviews,
        "distance": format_distance_km(distance_km),
        "address": _format_address(restaurant),
        "corner_badge": preset["corner_badge"],
        "corner_badge_kind": preset["corner_badge_kind"],
        "featured_label": preset["featured_label"],
        "featured_kind": preset["featured_kind"],
        "featured_name": featured_dish.dish_name if featured_dish else "Món đang cập nhật",
        "price": _format_price(featured_dish.price) if featured_dish else "Liên hệ",
        "footer_visible": True,
    }


def _load_restaurant_payloads(user_location=None):
    restaurants = (
        Restaurant.query.options(joinedload(Restaurant.user), joinedload(Restaurant.dishes))
        .order_by(Restaurant.restaurant_id.asc())
        .all()
    )
    review_stats_map = _review_stats_by_restaurant()

    payloads = []
    for index, restaurant in enumerate(restaurants):
        distance_km = _restaurant_distance(user_location, restaurant)
        review_stats = review_stats_map.get(restaurant.restaurant_id)
        payloads.append(
            {
                "restaurant": restaurant,
                "distance_km": distance_km,
                "review_stats": review_stats,
                "card": _build_card(restaurant, index, distance_km=distance_km, review_stats=review_stats),
                "active_dish_count": len(_active_dishes(restaurant)),
            }
        )
    return payloads


def _sorted_suggested_cards(payloads):
    payloads = [payload for payload in payloads if payload["active_dish_count"] > 0]
    payloads.sort(
        key=lambda payload: (
            -(payload["active_dish_count"]),
            location_sort_key(payload["distance_km"], payload["restaurant"].restaurant_id),
        )
    )
    return [payload["card"] for payload in payloads]


def _sorted_nearby_cards(payloads):
    payloads.sort(key=lambda payload: location_sort_key(payload["distance_km"], payload["restaurant"].restaurant_id))
    return [payload["card"] for payload in payloads]


def _sorted_top_rated_cards(payloads):
    payloads = [payload for payload in payloads if payload["active_dish_count"] > 0]
    payloads.sort(
        key=lambda payload: (
            -(payload["review_stats"]["average_rating"] if payload["review_stats"] and payload["review_stats"]["review_count"] else 0),
            -(payload["review_stats"]["review_count"] if payload["review_stats"] else 0),
            -(payload["active_dish_count"]),
            location_sort_key(payload["distance_km"], payload["restaurant"].restaurant_id),
        )
    )
    return [payload["card"] for payload in payloads]


def _build_location_params(user_location):
    params = {}
    if not user_location:
        return params

    if user_location.get("address"):
        params["address"] = user_location["address"]
    if user_location.get("latitude") is not None:
        params["lat"] = user_location["latitude"]
    if user_location.get("longitude") is not None:
        params["lon"] = user_location["longitude"]
    if user_location.get("area"):
        params["area"] = user_location["area"]
    return params


def _build_url(base_path, params=None):
    return f"{base_path}?{urlencode(params)}" if params else base_path


def _paginate_cards(cards, page_number, page_size):
    total_count = len(cards)
    total_pages = max(1, ceil(total_count / page_size)) if total_count else 1
    current_page = max(1, min(int(page_number or 1), total_pages))
    start = (current_page - 1) * page_size
    end = start + page_size
    page_cards = cards[start:end]
    has_more = current_page < total_pages
    return page_cards, current_page, total_count, has_more


def _cards_for_section(section_key, user_location=None):
    payloads = _load_restaurant_payloads(user_location=user_location)
    if section_key == SECTION_NEARBY:
        return _sorted_nearby_cards(payloads)
    if section_key == SECTION_TOP_RATED:
        return _sorted_top_rated_cards(payloads)
    return _sorted_suggested_cards(payloads)


def get_home_page_context(query="", page_number=1, user_location=None, hero_address=""):
    page = get_home_page_data()
    location_params = _build_location_params(user_location)

    sections = []
    for section in page["sections"]:
        cards = _cards_for_section(section["key"], user_location=user_location)
        preview_cards = cards[:HOME_PREVIEW_SIZE]
        load_more_href = None
        if section["key"] in {SECTION_NEARBY, SECTION_TOP_RATED}:
            load_more_href = _build_url(section["browse_path"], location_params)

        sections.append(
            {
                **section,
                "items": preview_cards,
                "show_load_more": bool(section.get("show_load_more") and load_more_href),
                "load_more_href": load_more_href,
            }
        )

    page["search_query"] = query
    page["current_page"] = max(1, int(page_number or 1))
    page["results_count"] = sum(len(section["items"]) for section in sections)
    page["hero_value"] = hero_address or ""
    page["sections"] = sections
    return page


def get_restaurant_collection_context(section_key, page_number=1, user_location=None, hero_address=""):
    meta = SECTION_META.get(section_key)
    if not meta:
        return None

    cards = _cards_for_section(section_key, user_location=user_location)
    page_cards, current_page, total_count, has_more = _paginate_cards(cards, page_number=page_number, page_size=COLLECTION_PAGE_SIZE)
    location_params = _build_location_params(user_location)
    base_path = f"/collections/{section_key}/load-more"

    return {
        "section_key": section_key,
        "title": meta["title"],
        "empty_title": meta["empty_title"],
        "empty_description": meta["empty_description"],
        "items": page_cards,
        "current_page": current_page,
        "total_count": total_count,
        "has_more": has_more,
        "load_more_url": _build_url(base_path, {**location_params, "page": current_page + 1}) if has_more else None,
        "hero_value": hero_address or "",
        "location_storage_key": None,
        "location_persist": True,
        "location_clear_storage_key": None,
    }
