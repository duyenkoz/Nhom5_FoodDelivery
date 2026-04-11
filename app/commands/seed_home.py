import click

from app.extensions import db
from app.models import Dish, Restaurant, User
from app.services.location_service import resolve_address_for_area


RESTAURANTS = [
    {
        "username": "comtam-phucloctho",
        "display_name": "Cơm Tấm Phúc Lộc Thọ",
        "address": "123 Đường Nguyễn Văn Linh, Phường Tân Thuận Tây, Quận 7",
        "area": "Hồ Chí Minh",
        "image": "images/com-tam.jpg",
        "dishes": [
            {"name": "Cơm sườn bì chả", "price": 66000},
            {"name": "Cơm gà nướng", "price": 72000},
        ],
    },
    {
        "username": "bundaumamtom-achanh",
        "display_name": "Bún Đậu Mắm Tôm A Chảnh",
        "address": "45 Hẻm 453 Lê Văn Sỹ, Phường 12, Quận 3",
        "area": "Hồ Chí Minh",
        "image": "images/nha_hang_bun_dau.jpg",
        "dishes": [
            {"name": "Bún đậu đầy đủ", "price": 80000},
            {"name": "Chả cốm", "price": 25000},
        ],
    },
    {
        "username": "phohung-nguyentrai",
        "display_name": "Phở Hùng - Nguyễn Trãi",
        "address": "241 Đường Nguyễn Trãi, Phường Nguyễn Cư Trinh, Quận 1",
        "area": "Hồ Chí Minh",
        "image": "images/nha_hang_pho.jpg",
        "dishes": [
            {"name": "Phở tái đặc biệt", "price": 65000},
            {"name": "Phở gà", "price": 62000},
        ],
    },
    {
        "username": "thecoffeehouse-caothang",
        "display_name": "The Coffee House",
        "address": "88 Đường Cao Thắng, Phường 4, Quận 3",
        "area": "Hồ Chí Minh",
        "image": "images/the_coffee_house.jpg",
        "dishes": [
            {"name": "Bạc xỉu (S)", "price": 39000},
            {"name": "Trà đào cam sả", "price": 45000},
        ],
    },
    {
        "username": "banhmi-huynhhoa",
        "display_name": "Bánh Mì Huỳnh Hoa",
        "address": "26 Đường Lê Thị Riêng, Phường Bến Thành, Quận 1",
        "area": "Hồ Chí Minh",
        "image": "images/banh_mi_huynh_hoa.jpg",
        "dishes": [
            {"name": "Bánh mì pate chả lụa", "price": 70000},
            {"name": "Bánh mì ốp la", "price": 45000},
        ],
    },
    {
        "username": "garan-popeyes",
        "display_name": "Gà Rán Popeyes",
        "address": "469 Đường Nguyễn Hữu Thọ, Phường Tân Hưng, Quận 7",
        "area": "Hồ Chí Minh",
        "image": "images/ga_ran_popeyes.png",
        "dishes": [
            {"name": "Combo gà rán nước ngọt", "price": 90000},
            {"name": "Khoai tây chiên", "price": 35000},
        ],
    },
    {
        "username": "pizzacompany",
        "display_name": "Pizza Company",
        "address": "68 Phan Xích Long, Phường 1, Quận Phú Nhuận",
        "area": "Hồ Chí Minh",
        "image": "images/pizza_company.jpg",
        "dishes": [
            {"name": "Pizza hải sản", "price": 150000},
            {"name": "Mì Ý bò bằm", "price": 99000},
        ],
    },
    {
        "username": "gongcha-trasua",
        "display_name": "Trà Sữa Gong Cha",
        "address": "96 Đường Hồ Tùng Mậu, Phường Bến Nghé, Quận 1",
        "area": "Hồ Chí Minh",
        "image": "images/gong_cha.jpg",
        "dishes": [
            {"name": "Trà sữa uyên ương", "price": 66000},
            {"name": "Trà sữa ô long", "price": 59000},
        ],
    },
    {
        "username": "bunbo-uthung",
        "display_name": "Bún Bò Huế Út Hưng",
        "address": "456 Đường Huỳnh Tấn Phát, Phường Bình Thuận, Quận 7",
        "area": "Hồ Chí Minh",
        "image": "images/banh_cuon_cha.jpg",
        "dishes": [
            {"name": "Bún bò tái nạm", "price": 60000},
            {"name": "Bún chả giò", "price": 62000},
        ],
    },
    {
        "username": "sushitei",
        "display_name": "Sushi Tei",
        "address": "5 Lý Tự Trọng, Phường Bến Nghé, Quận 1",
        "area": "Hồ Chí Minh",
        "image": "images/tra_sua_Oolong.png",
        "dishes": [
            {"name": "Phần cá ngừ", "price": 266000},
            {"name": "Sushi tổng hợp", "price": 245000},
        ],
    },
]

SEED_LOCATION_FALLBACKS = {
    ("123 Đường Nguyễn Văn Linh, Phường Tân Thuận Tây, Quận 7", "Hồ Chí Minh"): (10.752172, 106.725394),
    ("45 Hẻm 453 Lê Văn Sỹ, Phường 12, Quận 3", "Hồ Chí Minh"): (10.78909, 106.67361),
    ("241 Đường Nguyễn Trãi, Phường Nguyễn Cư Trinh, Quận 1", "Hồ Chí Minh"): (10.76484, 106.68762),
    ("88 Đường Cao Thắng, Phường 4, Quận 3", "Hồ Chí Minh"): (10.77105, 106.681039),
    ("26 Đường Lê Thị Riêng, Phường Bến Thành, Quận 1", "Hồ Chí Minh"): (10.77141, 106.692417),
    ("469 Đường Nguyễn Hữu Thọ, Phường Tân Hưng, Quận 7", "Hồ Chí Minh"): (10.741028, 106.701958),
    ("68 Phan Xích Long, Phường 1, Quận Phú Nhuận", "Hồ Chí Minh"): (10.801063, 106.683374),
    ("96 Đường Hồ Tùng Mậu, Phường Bến Nghé, Quận 1", "Hồ Chí Minh"): (10.77279, 106.70349),
    ("456 Đường Huỳnh Tấn Phát, Phường Bình Thuận, Quận 7", "Hồ Chí Minh"): (10.74491, 106.72923),
    ("5 Lý Tự Trọng, Phường Bến Nghé, Quận 1", "Hồ Chí Minh"): (10.782375, 106.705336),
}


def _upsert_user(spec):
    user = User.query.filter_by(username=spec["username"]).one_or_none()
    if user:
        user.display_name = spec["display_name"]
        user.email = user.email or f'{spec["username"]}@example.com'
        user.phone = user.phone or "0900000000"
        user.role = "restaurant"
        user.status = True
        user.password = user.password or "password123"
        return user, False

    user = User(
        username=spec["username"],
        password="password123",
        display_name=spec["display_name"],
        email=f'{spec["username"]}@example.com',
        phone="0900000000",
        role="restaurant",
        status=True,
    )
    db.session.add(user)
    db.session.flush()
    return user, True


def _upsert_restaurant(user, spec):
    restaurant = Restaurant.query.filter_by(restaurant_id=user.user_id).one_or_none()
    if not restaurant:
        restaurant = Restaurant(restaurant_id=user.user_id)
        db.session.add(restaurant)

    location = resolve_address_for_area(spec["address"], spec["area"], allow_seed_fallback=True)
    if not location:
        coords = SEED_LOCATION_FALLBACKS.get((spec["address"], spec["area"]))
        if coords:
            location = {"lat": coords[0], "lon": coords[1]}

    restaurant.image = spec["image"]
    restaurant.address = spec["address"]
    restaurant.area = spec["area"]
    restaurant.latitude = location["lat"] if location else None
    restaurant.longitude = location["lon"] if location else None
    restaurant.description = f"Nhà hàng phục vụ món {spec['display_name']}"
    restaurant.platform_fee = restaurant.platform_fee or 0
    return restaurant, restaurant in db.session.new


def _upsert_dish(restaurant_id, dish_spec):
    dish = Dish.query.filter_by(restaurant_id=restaurant_id, dish_name=dish_spec["name"]).one_or_none()
    if not dish:
        dish = Dish(restaurant_id=restaurant_id, dish_name=dish_spec["name"])
        db.session.add(dish)

    dish.price = dish_spec["price"]
    dish.description = dish.description or dish_spec["name"]
    dish.status = True
    return dish, dish in db.session.new


@click.command("seed-home")
def seed_home_command():
    """Seed home page restaurant and dish data."""
    created_users = 0
    created_restaurants = 0
    created_dishes = 0

    for spec in RESTAURANTS:
        user, user_created = _upsert_user(spec)
        if user_created:
            created_users += 1

        _, restaurant_created = _upsert_restaurant(user, spec)
        if restaurant_created:
            created_restaurants += 1

        for dish_spec in spec["dishes"]:
            _, dish_created = _upsert_dish(user.user_id, dish_spec)
            if dish_created:
                created_dishes += 1

    db.session.commit()
    click.echo(
        f"Seed done: users={created_users}, restaurants={created_restaurants}, dishes={created_dishes}"
    )
