from math import ceil
from urllib.parse import urlencode

from sqlalchemy.orm import joinedload

from app.data.home import get_home_page_data
from app.models import Restaurant


PAGE_SIZE = 8

PRESENTATION_PRESETS = [
    {
        "rating": "4.8",
        "reviews": "500+",
        "distance": "1.2 km",
        "corner_badge": "PROMO",
        "corner_badge_kind": "promo",
        "featured_label": "Hot",
        "featured_kind": "hot",
    },
    {
        "rating": "4.5",
        "reviews": "1.2k",
        "distance": "0.8 km",
        "corner_badge": "",
        "corner_badge_kind": "",
        "featured_label": "Hot",
        "featured_kind": "hot",
    },
    {
        "rating": "4.9",
        "reviews": "2k",
        "distance": "2.5 km",
        "corner_badge": "",
        "corner_badge_kind": "",
        "featured_label": "Best Seller",
        "featured_kind": "best",
    },
    {
        "rating": "4.7",
        "reviews": "3k",
        "distance": "0.5 km",
        "corner_badge": "PROMO",
        "corner_badge_kind": "promo",
        "featured_label": "Hot",
        "featured_kind": "hot",
    },
    {
        "rating": "4.9",
        "reviews": "5k",
        "distance": "3.1 km",
        "corner_badge": "",
        "corner_badge_kind": "",
        "featured_label": "Best Seller",
        "featured_kind": "best",
    },
    {
        "rating": "4.3",
        "reviews": "800",
        "distance": "1.8 km",
        "corner_badge": "",
        "corner_badge_kind": "",
        "featured_label": "Hot",
        "featured_kind": "hot",
    },
    {
        "rating": "4.6",
        "reviews": "1.5k",
        "distance": "2.2 km",
        "corner_badge": "",
        "corner_badge_kind": "",
        "featured_label": "Best Seller",
        "featured_kind": "best",
    },
    {
        "rating": "4.7",
        "reviews": "2.2k",
        "distance": "1.0 km",
        "corner_badge": "PROMO",
        "corner_badge_kind": "promo",
        "featured_label": "Hot",
        "featured_kind": "hot",
    },
    {
        "rating": "4.4",
        "reviews": "120",
        "distance": "0.3 km",
        "corner_badge": "",
        "corner_badge_kind": "",
        "featured_label": "Best Seller",
        "featured_kind": "best",
    },
    {
        "rating": "5.0",
        "reviews": "10k+",
        "distance": "2.8 km",
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
    parts = [restaurant.address, restaurant.area]
    return ", ".join(part for part in parts if part)


def _searchable_text(restaurant):
    values = [
        restaurant.user.display_name if restaurant.user else "",
        restaurant.user.username if restaurant.user else "",
        restaurant.address or "",
        restaurant.area or "",
    ]
    values.extend(dish.dish_name or "" for dish in restaurant.dishes)
    return " ".join(values).casefold()


def _build_card(restaurant, index):
    preset = PRESENTATION_PRESETS[index % len(PRESENTATION_PRESETS)]
    dishes = sorted(restaurant.dishes, key=lambda dish: dish.dish_id)
    featured_dish = dishes[0] if dishes else None

    return {
        "name": restaurant.user.display_name
        if restaurant.user and restaurant.user.display_name
        else (restaurant.user.username if restaurant.user else f"Nhà hàng {restaurant.restaurant_id}"),
        "image_path": restaurant.image or "images/restaurant-default.svg",
        "rating": preset["rating"],
        "reviews": preset["reviews"],
        "distance": preset["distance"],
        "address": _format_address(restaurant),
        "corner_badge": preset["corner_badge"],
        "corner_badge_kind": preset["corner_badge_kind"],
        "featured_label": preset["featured_label"],
        "featured_kind": preset["featured_kind"],
        "featured_name": featured_dish.dish_name if featured_dish else "Món đang cập nhật",
        "price": _format_price(featured_dish.price) if featured_dish else "Liên hệ",
    }


def _load_restaurant_cards(query):
    restaurants = (
        Restaurant.query.options(joinedload(Restaurant.user), joinedload(Restaurant.dishes))
        .order_by(Restaurant.restaurant_id.asc())
        .all()
    )
    pairs = [(_build_card(restaurant, index), restaurant) for index, restaurant in enumerate(restaurants)]

    if query:
        normalized_query = query.casefold()
        pairs = [(card, restaurant) for card, restaurant in pairs if normalized_query in _searchable_text(restaurant)]

    return [card for card, _ in pairs]


def _paginate_cards(cards, page_number):
    total_count = len(cards)
    total_pages = max(1, ceil(total_count / PAGE_SIZE)) if total_count else 1
    current_page = max(1, min(page_number, total_pages))
    start = (current_page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE
    page_cards = cards[start:end]
    has_more = current_page < total_pages
    return page_cards, current_page, total_count, has_more


def get_home_page_context(query="", page_number=1):
    page = get_home_page_data()
    cards = _load_restaurant_cards(query)
    page_cards, current_page, total_count, has_more = _paginate_cards(cards, page_number)

    sections = []
    for section in page["sections"]:
        params = {"page": current_page + 1}
        if query:
            params["q"] = query
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
    page["sections"] = sections
    return page
