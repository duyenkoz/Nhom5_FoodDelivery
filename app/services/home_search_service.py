from datetime import datetime, timedelta
from math import ceil
from urllib.parse import urlencode

from sqlalchemy import desc, func
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import Dish, Order, OrderItem, Review
from app.models import Restaurant
from app.services.home_service import get_home_page_context as get_legacy_home_page_context
from app.services.location_service import (
    area_matches,
    format_distance_km,
    haversine_distance_km,
    location_sort_key,
    normalize_text,
)


PAGE_SIZE = 8
SEARCH_RADIUS_KM = 5.0
SEARCH_TAB_ALL = "all"
SEARCH_TAB_RESTAURANT = "restaurant"
SEARCH_TAB_DISH = "dish"
SEARCH_SORT_RELEVANCE = "relevance"
SEARCH_SORT_NEAR = "near"
SEARCH_SORT_FAR = "far"
SEARCH_SORT_RATING = "rating"
SEARCH_SORT_PRICE_LOW = "price_low"
SEARCH_SORT_PRICE_HIGH = "price_high"

SEARCH_SORT_OPTIONS = [
    {"value": SEARCH_SORT_RELEVANCE, "label": "Đề xuất (Mặc định)"},
    {"value": SEARCH_SORT_NEAR, "label": "Gần nhất"},
    {"value": SEARCH_SORT_FAR, "label": "Xa nhất"},
    {"value": SEARCH_SORT_RATING, "label": "Đánh giá tốt"},
    {"value": SEARCH_SORT_PRICE_LOW, "label": "Giá thấp"},
    {"value": SEARCH_SORT_PRICE_HIGH, "label": "Giá cao"},
]

SEARCH_RATING_OPTIONS = [3.5, 4.0, 4.5]

SEARCH_PRICE_PRESETS = [
    {"value": "0-30000", "label": "0đ - 30.000đ", "min": 0, "max": 30000},
    {"value": "30000-50000", "label": "30.000đ - 50.000đ", "min": 30000, "max": 50000},
    {"value": "50000-70000", "label": "50.000đ - 70.000đ", "min": 50000, "max": 70000},
    {"value": "70000-100000", "label": "70.000đ - 100.000đ", "min": 70000, "max": 100000},
    {"value": "100000-150000", "label": "100.000đ - 150.000đ", "min": 100000, "max": 150000},
    {"value": "150000-250000", "label": "150.000đ - 250.000đ", "min": 150000, "max": 250000},
    {"value": "250000+", "label": "Từ 250.000đ trở lên", "min": 250000, "max": None},
]

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


def _normalized(value):
    return normalize_text(value or "")


def _safe_int(value, default=None):
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value, default=None):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _format_price(value):
    if value is None:
        return "Liên hệ"
    return f"{int(value):,}".replace(",", ".") + " đ"


def _format_review_count(value):
    count = int(value or 0)
    if count >= 1000:
        formatted = f"{count / 1000:.1f}".rstrip("0").rstrip(".")
        return f"{formatted}k"
    return str(count)


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


def _display_rating(index, review_stats, active_dish_count):
    if review_stats and review_stats.get("review_count"):
        rating_value = float(review_stats["average_rating"] or 0)
        return f"{rating_value:.1f}", _format_review_count(review_stats["review_count"]), rating_value

    preset = PRESENTATION_PRESETS[index % len(PRESENTATION_PRESETS)]
    synthetic_rating = min(5.0, 4.1 + min(active_dish_count, 9) * 0.1)
    synthetic_reviews = max(60, active_dish_count * 35)
    return f"{synthetic_rating:.1f}", _format_review_count(synthetic_reviews) or preset["reviews"], synthetic_rating


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
        }.get(_normalized(area), (_normalized(area),))

        while parts:
            tail = _normalized(parts[-1])
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
    if image_value.startswith("/"):
        return image_value.lstrip("/")
    if image_value.startswith(("http://", "https://")):
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


def _restaurant_search_text(restaurant):
    return " ".join(
        part
        for part in [
            restaurant.user.display_name if restaurant.user else "",
            restaurant.user.username if restaurant.user else "",
        ]
        if part
    )


def _active_dishes(restaurant):
    return [dish for dish in restaurant.dishes if dish.status]


def _restaurant_matches_query(restaurant, normalized_query):
    if not normalized_query:
        return True

    return normalized_query in _normalized(_restaurant_search_text(restaurant))


def _dish_matches_query(dish, normalized_query):
    if not normalized_query:
        return True

    return normalized_query in _normalized(dish.dish_name or "")


def _matching_dishes(restaurant, normalized_query):
    dishes = _active_dishes(restaurant)
    if not normalized_query:
        return dishes
    return [dish for dish in dishes if _dish_matches_query(dish, normalized_query)]


def _first_active_dish(restaurant):
    dishes = _active_dishes(restaurant)
    return dishes[0] if dishes else None


def _build_card(
    restaurant,
    index,
    distance_km=None,
    featured_dish=None,
    footer_visible=True,
    rating_text=None,
    reviews_text=None,
    price_text=None,
    rating_value=None,
    price_value=None,
):
    preset = PRESENTATION_PRESETS[index % len(PRESENTATION_PRESETS)]
    if featured_dish is None:
        featured_dish = _first_active_dish(restaurant)

    display_rating = rating_text or preset["rating"]
    display_reviews = reviews_text or preset["reviews"]
    display_price = price_text if price_text is not None else (_format_price(featured_dish.price) if featured_dish else "Liên hệ")

    return {
        "name": _restaurant_title(restaurant),
        "href": f"/restaurants/{restaurant.restaurant_id}",
        "image_path": _normalize_image_path(restaurant.image),
        "rating": display_rating,
        "reviews": display_reviews,
        "distance": format_distance_km(distance_km),
        "distance_value": distance_km,
        "address": _format_address(restaurant),
        "corner_badge": preset["corner_badge"],
        "corner_badge_kind": preset["corner_badge_kind"],
        "featured_label": preset["featured_label"],
        "featured_kind": preset["featured_kind"],
        "featured_name": featured_dish.dish_name if featured_dish else "Món đang cập nhật",
        "price": display_price,
        "price_value": price_value if price_value is not None else (int(featured_dish.price) if featured_dish and featured_dish.price is not None else None),
        "rating_value": rating_value if rating_value is not None else None,
        "footer_visible": footer_visible,
    }


def _restaurant_distance(user_location, restaurant):
    if not user_location:
        return None

    return haversine_distance_km(
        user_location.get("latitude"),
        user_location.get("longitude"),
        restaurant.latitude,
        restaurant.longitude,
    )


def _restaurant_matches_selected_area(restaurant, user_location=None):
    selected_area = _clean((user_location or {}).get("filter_area") or (user_location or {}).get("area"))
    if not selected_area:
        return True

    for candidate in (restaurant.area, restaurant.address):
        if area_matches(candidate, selected_area):
            return True
    return False


def _within_search_radius(distance_km):
    if distance_km is None:
        return True
    return distance_km <= SEARCH_RADIUS_KM


def _parse_search_filters(filters):
    filters = filters if isinstance(filters, dict) else {}

    sort_value = _clean(filters.get("sort")).lower() or SEARCH_SORT_RELEVANCE
    valid_sort_values = {option["value"] for option in SEARCH_SORT_OPTIONS}
    if sort_value not in valid_sort_values:
        sort_value = SEARCH_SORT_RELEVANCE

    min_rating = _safe_float(filters.get("min_rating"))
    if min_rating is not None:
        min_rating = max(0.0, min(min_rating, 5.0))

    price_min = _safe_int(filters.get("price_min"))
    price_max = _safe_int(filters.get("price_max"))
    price_range_value = _clean(filters.get("price_range"))

    valid_price_ranges = {item["value"] for item in SEARCH_PRICE_PRESETS}
    if price_min is None and price_max is None and price_range_value in valid_price_ranges:
        preset = next(item for item in SEARCH_PRICE_PRESETS if item["value"] == price_range_value)
        price_min = preset["min"]
        price_max = preset["max"]

    if price_min is not None and price_max is not None and price_max < price_min:
        price_min, price_max = price_max, price_min

    return {
        "sort": sort_value,
        "min_rating": min_rating,
        "price_min": price_min,
        "price_max": price_max,
        "price_range": price_range_value if price_range_value in valid_price_ranges else "",
    }


def _build_search_query_params(query, user_location, tab, filters=None):
    params = {"q": query, **_build_location_params(user_location), "tab": tab}
    filters = _parse_search_filters(filters)

    if filters["sort"] != SEARCH_SORT_RELEVANCE:
        params["sort"] = filters["sort"]
    if filters["min_rating"] is not None:
        params["min_rating"] = filters["min_rating"]
    if filters["price_min"] is not None:
        params["price_min"] = filters["price_min"]
    if filters["price_max"] is not None:
        params["price_max"] = filters["price_max"]
    if filters["price_range"]:
        params["price_range"] = filters["price_range"]
    return params


def _rating_passes_filter(rating_value, min_rating):
    if min_rating is None:
        return True
    if rating_value is None:
        return False
    return rating_value >= min_rating


def _price_passes_filter(price_value, price_min, price_max):
    if price_min is not None and (price_value is None or price_value < price_min):
        return False
    if price_max is not None and (price_value is None or price_value > price_max):
        return False
    return True


def _search_sort_key(payload, sort_value):
    distance_km = payload["distance_km"]
    rating_value = payload["rating_value"] if payload["rating_value"] is not None else 0
    review_count = payload["review_count"] if payload["review_count"] is not None else 0
    price_value = payload["price_value"]
    priority = payload["priority"]
    restaurant_id = payload["restaurant_id"]

    if sort_value == SEARCH_SORT_NEAR:
        return (distance_km is None, distance_km or 0, priority, restaurant_id)

    if sort_value == SEARCH_SORT_FAR:
        return (distance_km is None, -(distance_km or 0), priority, restaurant_id)

    if sort_value == SEARCH_SORT_RATING:
        return (-rating_value, -review_count, distance_km is None, distance_km or 0, priority, restaurant_id)

    if sort_value == SEARCH_SORT_PRICE_LOW:
        return (price_value is None, price_value if price_value is not None else 0, distance_km is None, distance_km or 0, priority, restaurant_id)

    if sort_value == SEARCH_SORT_PRICE_HIGH:
        return (price_value is None, -(price_value if price_value is not None else 0), distance_km is None, distance_km or 0, priority, restaurant_id)

    return (distance_km is None, distance_km or 0, priority, restaurant_id)


def _paginate_cards(cards, page_number):
    total_count = len(cards)
    total_pages = max(1, ceil(total_count / PAGE_SIZE)) if total_count else 1
    current_page = max(1, min(int(page_number or 1), total_pages))
    start = (current_page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE
    page_cards = cards[start:end]
    has_more = current_page < total_pages
    return page_cards, current_page, total_count, has_more


def _load_restaurant_cards(query, user_location=None):
    restaurants = (
        Restaurant.query.options(joinedload(Restaurant.user), joinedload(Restaurant.dishes))
        .order_by(Restaurant.restaurant_id.asc())
        .all()
    )

    pairs = []
    normalized_query = _normalized(query)

    for index, restaurant in enumerate(restaurants):
        if not _restaurant_matches_selected_area(restaurant, user_location=user_location):
            continue

        distance_km = _restaurant_distance(user_location, restaurant)
        pairs.append((_build_card(restaurant, index, distance_km=distance_km), restaurant, distance_km))

    if normalized_query:
        pairs = [
            (card, restaurant, distance_km)
            for card, restaurant, distance_km in pairs
            if normalized_query in _normalized(
                " ".join(
                    [
                        restaurant.user.display_name if restaurant.user else "",
                        restaurant.user.username if restaurant.user else "",
                        restaurant.address or "",
                        restaurant.area or "",
                        " ".join(dish.dish_name or "" for dish in restaurant.dishes),
                    ]
                )
            )
        ]

    pairs.sort(key=lambda item: location_sort_key(item[2], item[1].restaurant_id))
    return [card for card, _, _ in pairs]


def _build_search_cards(query, tab, user_location=None, filters=None):
    normalized_query = _normalized(query)
    search_filters = _parse_search_filters(filters)
    review_stats_map = _review_stats_by_restaurant()
    restaurants = (
        Restaurant.query.options(joinedload(Restaurant.user), joinedload(Restaurant.dishes))
        .order_by(Restaurant.restaurant_id.asc())
        .all()
    )

    cards = []
    has_location = user_location is not None
    for index, restaurant in enumerate(restaurants):
        if not _restaurant_matches_selected_area(restaurant, user_location=user_location):
            continue

        distance_km = _restaurant_distance(user_location, restaurant)
        if has_location and not _within_search_radius(distance_km):
            continue

        restaurant_matches = _restaurant_matches_query(restaurant, normalized_query)
        matching_dishes = _matching_dishes(restaurant, normalized_query)
        featured_dish = matching_dishes[0] if matching_dishes else _first_active_dish(restaurant)
        candidate_dishes = matching_dishes if matching_dishes else _active_dishes(restaurant)
        candidate_prices = [int(dish.price) for dish in candidate_dishes if dish.price is not None]
        review_stats = review_stats_map.get(restaurant.restaurant_id)
        rating_text, reviews_text, rating_value = _display_rating(index, review_stats, len(_active_dishes(restaurant)))
        price_value = min(candidate_prices) if candidate_prices else (int(featured_dish.price) if featured_dish and featured_dish.price is not None else None)

        if not _rating_passes_filter(rating_value, search_filters["min_rating"]):
            continue

        if not _price_passes_filter(price_value, search_filters["price_min"], search_filters["price_max"]):
            continue

        if tab == SEARCH_TAB_RESTAURANT:
            if not restaurant_matches:
                continue
            cards.append(
                {
                    "card": _build_card(
                        restaurant,
                        index,
                        distance_km=distance_km,
                        featured_dish=_first_active_dish(restaurant),
                        footer_visible=False,
                        rating_text=rating_text,
                        reviews_text=reviews_text,
                        rating_value=rating_value,
                    ),
                    "distance_km": distance_km,
                    "restaurant_id": restaurant.restaurant_id,
                    "rating_value": rating_value,
                    "review_count": review_stats["review_count"] if review_stats else 0,
                    "price_value": price_value,
                    "priority": 0,
                }
            )
            continue

        if tab == SEARCH_TAB_DISH:
            if not matching_dishes:
                continue
            cards.append(
                {
                    "card": _build_card(
                        restaurant,
                        index,
                        distance_km=distance_km,
                        featured_dish=featured_dish,
                        footer_visible=True,
                        rating_text=rating_text,
                        reviews_text=reviews_text,
                        price_value=price_value,
                        rating_value=rating_value,
                    ),
                    "distance_km": distance_km,
                    "restaurant_id": restaurant.restaurant_id,
                    "rating_value": rating_value,
                    "review_count": review_stats["review_count"] if review_stats else 0,
                    "price_value": price_value,
                    "priority": 1,
                }
            )
            continue

        if not restaurant_matches and not matching_dishes:
            continue

        cards.append(
            {
                "card": _build_card(
                    restaurant,
                    index,
                    distance_km=distance_km,
                    featured_dish=featured_dish,
                    footer_visible=True,
                    rating_text=rating_text,
                    reviews_text=reviews_text,
                    price_value=price_value,
                    rating_value=rating_value,
                ),
                "distance_km": distance_km,
                "restaurant_id": restaurant.restaurant_id,
                "rating_value": rating_value,
                "review_count": review_stats["review_count"] if review_stats else 0,
                "price_value": price_value,
                "priority": 0 if restaurant_matches else 1,
            }
        )

    cards.sort(key=lambda item: _search_sort_key(item, search_filters["sort"]))
    return [item["card"] for item in cards]


def build_search_suggestions(query, limit=8):
    normalized_query = _normalized(query)
    if not normalized_query:
        return []

    restaurants = (
        Restaurant.query.options(joinedload(Restaurant.user), joinedload(Restaurant.dishes))
        .order_by(Restaurant.restaurant_id.asc())
        .all()
    )

    suggestions = []
    for restaurant in restaurants:
        matching_dishes = _matching_dishes(restaurant, normalized_query)

        for dish in matching_dishes[:2]:
            dish_name = dish.dish_name or ""
            suggestions.append(
                {
                    "label": dish_name,
                    "value": dish_name,
                    "kind": "dish",
                    "priority": 0 if _normalized(dish_name).startswith(normalized_query) else 1,
                }
            )

    suggestions = [item for item in suggestions if item["label"]]
    suggestions.sort(
        key=lambda item: (
            item["priority"],
            _normalized(item["label"]),
        )
    )

    deduped = []
    seen = set()
    max_items = max(1, min(int(limit or 8), 12))
    for item in suggestions:
        key = (item["kind"], _normalized(item["label"]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= max_items:
            break
    return deduped


def build_hot_search_keywords(limit=10, days=7):
    try:
        limit = max(1, min(int(limit or 10), 10))
    except (TypeError, ValueError):
        limit = 10

    try:
        days = max(1, int(days or 7))
    except (TypeError, ValueError):
        days = 7

    cutoff = datetime.utcnow() - timedelta(days=days)
    excluded_statuses = {"cancel", "canceled", "cancelled", "failed", "refund", "refund_pending", "pending_refund", "refunded", "rejected"}
    status_expr = func.lower(func.coalesce(Order.status, ""))

    rows = (
        db.session.query(
            Dish.dish_id.label("dish_id"),
            func.coalesce(func.sum(func.coalesce(OrderItem.quantity, 1)), 0).label("score"),
            func.max(Order.order_date).label("last_ordered"),
        )
        .join(OrderItem, OrderItem.dish_id == Dish.dish_id)
        .join(Order, Order.order_id == OrderItem.order_id)
        .filter(Order.order_date.isnot(None))
        .filter(Order.order_date >= cutoff)
        .filter(~status_expr.in_(excluded_statuses))
        .group_by(Dish.dish_id)
        .order_by(desc("score"), desc("last_ordered"))
        .limit(limit)
        .all()
    )

    if not rows:
        return []

    dish_ids = [row.dish_id for row in rows if row.dish_id is not None]
    if not dish_ids:
        return []

    dishes = (
        Dish.query.options(joinedload(Dish.restaurant).joinedload(Restaurant.user))
        .filter(Dish.dish_id.in_(dish_ids))
        .all()
    )
    dish_by_id = {dish.dish_id: dish for dish in dishes}

    hot_keywords = []
    for row in rows:
        dish = dish_by_id.get(row.dish_id)
        if not dish or not _clean(dish.dish_name):
            continue

        restaurant_name = _restaurant_title(dish.restaurant) if dish.restaurant else "Nhà hàng"
        hot_keywords.append(
            {
                "label": dish.dish_name,
                "value": dish.dish_name,
                "meta": restaurant_name,
                "kind": "hot",
                "score": int(row.score or 0),
            }
        )

    return hot_keywords[:limit]


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


def _build_url(params):
    return f"/?{urlencode(params)}" if params else "/"


def get_home_page_context(query="", page_number=1, user_location=None, hero_address="", tab="all", filters=None):
    search_mode = bool(_clean(query))
    if not search_mode:
        return get_legacy_home_page_context(query, page_number=page_number, user_location=user_location, hero_address=hero_address)

    base_page = get_legacy_home_page_context("", page_number=page_number, user_location=user_location, hero_address=hero_address)
    normalized_tab = tab if tab in {SEARCH_TAB_ALL, SEARCH_TAB_RESTAURANT, SEARCH_TAB_DISH} else SEARCH_TAB_ALL
    search_filters = _parse_search_filters(filters)
    search_cards = _build_search_cards(query, normalized_tab, user_location=user_location, filters=search_filters)
    page_cards, current_page, total_count, has_more = _paginate_cards(search_cards, page_number)

    query_params = _build_search_query_params(query, user_location, normalized_tab, search_filters)
    clear_filters_params = _build_search_query_params(query, user_location, normalized_tab, {})

    base_page["search_mode"] = True
    base_page["search_query"] = query
    base_page["search_tab"] = normalized_tab
    base_page["search_results"] = page_cards
    base_page["search_results_count"] = total_count
    base_page["search_current_page"] = current_page
    base_page["search_has_more"] = has_more
    base_page["search_load_more_href"] = _build_url({**query_params, "page": current_page + 1}) if has_more else None
    base_page["search_empty_title"] = "Không tìm thấy"
    base_page["search_empty_description"] = "Không tìm thấy món ăn hoặc nhà hàng phù hợp."
    base_page["search_filters"] = search_filters
    base_page["search_sort_options"] = SEARCH_SORT_OPTIONS
    base_page["search_rating_options"] = SEARCH_RATING_OPTIONS
    base_page["search_price_presets"] = SEARCH_PRICE_PRESETS
    base_page["search_filter_active_count"] = sum(
        1
        for item in [
            search_filters["sort"] != SEARCH_SORT_RELEVANCE,
            search_filters["min_rating"] is not None,
            search_filters["price_min"] is not None or search_filters["price_max"] is not None,
        ]
        if item
    )
    base_page["search_has_location"] = bool(user_location and user_location.get("latitude") is not None and user_location.get("longitude") is not None)
    base_page["search_location_params"] = _build_location_params(user_location)
    base_page["search_clear_filters_href"] = _build_url(clear_filters_params)
    base_page["search_tabs"] = [
        {
            "label": "Tất cả",
            "value": SEARCH_TAB_ALL,
            "active": normalized_tab == SEARCH_TAB_ALL,
            "href": _build_url({**query_params, "tab": SEARCH_TAB_ALL}),
        },
        {
            "label": "Nhà hàng",
            "value": SEARCH_TAB_RESTAURANT,
            "active": normalized_tab == SEARCH_TAB_RESTAURANT,
            "href": _build_url({**query_params, "tab": SEARCH_TAB_RESTAURANT}),
        },
        {
            "label": "Món ăn",
            "value": SEARCH_TAB_DISH,
            "active": normalized_tab == SEARCH_TAB_DISH,
            "href": _build_url({**query_params, "tab": SEARCH_TAB_DISH}),
        },
    ]
    base_page["sections"] = []
    base_page["results_count"] = total_count
    base_page["current_page"] = current_page
    base_page["hero_value"] = hero_address or ""
    return base_page
