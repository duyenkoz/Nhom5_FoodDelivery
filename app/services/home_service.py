from math import ceil
from urllib.parse import urlencode

from sqlalchemy.orm import joinedload

from app.data.home import get_home_page_data
from app.models import Restaurant
from app.services.location_service import (
    format_distance_km,
    haversine_distance_km,
    normalize_text,
    location_sort_key,
)


PAGE_SIZE = 8

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


def _format_price(value):
    if value is None:
        return "Liên hệ"
    return f"{int(value):,}".replace(",", ".") + " đ"


def _format_address(restaurant):
    address = (restaurant.address or "").strip()
    area = (restaurant.area or "").strip()

    if address and area:
        parts = [part.strip() for part in address.split(",") if part.strip()]
        area_aliases = {
            "hồ chí minh": ("hồ chí minh", "thành phố hồ chí minh", "tp hcm", "tphcm", "hcm"),
            "hà nội": ("hà nội", "thành phố hà nội", "tp hà nội", "hanoi", "tphn"),
            "đà nẵng": ("đà nẵng", "thành phố đà nẵng", "tp đà nẵng", "danang", "tpdn"),
            "cần thơ": ("cần thơ", "thành phố cần thơ", "tp cần thơ", "cantho", "tpct"),
        }.get(normalize_text(area), (normalize_text(area),))
        while parts:
            tail = normalize_text(parts[-1])
            if any(alias and alias in tail for alias in area_aliases) or "thanh pho" in tail:
                parts.pop()
                continue
            break
        address = ", ".join(parts) if parts else address

    parts = [address, area]
    return ", ".join(part for part in parts if part)


def _normalize_image_path(image_value):
    image_value = (image_value or "").strip()
    if not image_value:
        return "images/restaurant-default.svg"
    if image_value.startswith("/static/"):
        return image_value[len("/static/") :]
    if image_value.startswith("/"):
        return image_value.lstrip("/")
    if image_value.startswith(("http://", "https://", "/")):
        return image_value.lstrip("/")
    if "/" in image_value:
        return image_value
    return f"uploads/{image_value}"


def _searchable_text(restaurant):
    values = [
        restaurant.user.display_name if restaurant.user else "",
        restaurant.user.username if restaurant.user else "",
        restaurant.address or "",
        restaurant.area or "",
    ]
    values.extend(dish.dish_name or "" for dish in restaurant.dishes)
    return " ".join(values).casefold()


def _build_card(restaurant, index, distance_km=None):
    preset = PRESENTATION_PRESETS[index % len(PRESENTATION_PRESETS)]
    dishes = sorted(restaurant.dishes, key=lambda dish: dish.dish_id)
    featured_dish = dishes[0] if dishes else None
    distance_text = format_distance_km(distance_km)

    return {
        "name": restaurant.user.display_name
        if restaurant.user and restaurant.user.display_name
        else (restaurant.user.username if restaurant.user else f"Nhà hàng {restaurant.restaurant_id}"),
        "image_path": _normalize_image_path(restaurant.image),
        "rating": preset["rating"],
        "reviews": preset["reviews"],
        "distance": distance_text,
        "address": _format_address(restaurant),
        "corner_badge": preset["corner_badge"],
        "corner_badge_kind": preset["corner_badge_kind"],
        "featured_label": preset["featured_label"],
        "featured_kind": preset["featured_kind"],
        "featured_name": featured_dish.dish_name if featured_dish else "Món đang cập nhật",
        "price": _format_price(featured_dish.price) if featured_dish else "Liên hệ",
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


def _load_restaurant_cards(query, user_location=None):
    restaurants = (
        Restaurant.query.options(joinedload(Restaurant.user), joinedload(Restaurant.dishes))
        .order_by(Restaurant.restaurant_id.asc())
        .all()
    )
    pairs = []
    for index, restaurant in enumerate(restaurants):
        distance_km = _restaurant_distance(user_location, restaurant)
        pairs.append((_build_card(restaurant, index, distance_km=distance_km), restaurant, distance_km))

    if query:
        normalized_query = query.casefold()
        pairs = [
            (card, restaurant, distance_km)
            for card, restaurant, distance_km in pairs
            if normalized_query in _searchable_text(restaurant)
        ]

    pairs.sort(key=lambda item: location_sort_key(item[2], item[1].restaurant_id))
    return [card for card, _, _ in pairs]


def _paginate_cards(cards, page_number):
    total_count = len(cards)
    total_pages = max(1, ceil(total_count / PAGE_SIZE)) if total_count else 1
    current_page = max(1, min(page_number, total_pages))
    start = (current_page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE
    page_cards = cards[start:end]
    has_more = current_page < total_pages
    return page_cards, current_page, total_count, has_more


def get_home_page_context(query="", page_number=1, user_location=None, hero_address=""):
    page = get_home_page_data()
    cards = _load_restaurant_cards(query, user_location=user_location)
    page_cards, current_page, total_count, has_more = _paginate_cards(cards, page_number)

    sections = []
    for section in page["sections"]:
        params = {"page": current_page + 1}
        if query:
            params["q"] = query
        if user_location:
            if user_location.get("address"):
                params["address"] = user_location["address"]
            if user_location.get("latitude") is not None:
                params["lat"] = user_location["latitude"]
            if user_location.get("longitude") is not None:
                params["lon"] = user_location["longitude"]
            if user_location.get("area"):
                params["area"] = user_location["area"]
        sections.append(
            {
                **section,
                "items": page_cards,
                "show_load_more": has_more,
                "load_more_href": f"/?{urlencode(params)}" if has_more else None,
            }
        )

    page["search_query"] = query
    page["current_page"] = current_page
    page["results_count"] = total_count
    page["hero_value"] = hero_address or ""
    page["sections"] = sections
    return page
