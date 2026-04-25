import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

from app import create_app
from app.extensions import db
from app.models import Customer, Dish, Order, OrderItem, Restaurant, Review, User
from app.services.public_restaurant_service import build_public_restaurant_context
from app.services.restaurant_service import (
    _build_review_dashboard,
    _build_reviewed_top_dishes,
    _review_sentiment_bucket,
)
from app.utils.time_utils import VIETNAM_TZ


def _vn_dt(year, month, day, hour=12, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=VIETNAM_TZ)


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    GEMINI_API_KEY = ""
    GEMINI_MODEL = ""
    AI_REVIEW_SUMMARY_MIN_REVIEWS = 5
    AI_REVIEW_SUMMARY_MAX_REVIEWS = 30
    AI_REVIEW_SUMMARY_TIMEOUT_SECONDS = 15
    MAIL_SERVER = "localhost"
    MAIL_PORT = 25
    MAIL_USE_TLS = False
    MAIL_USE_SSL = False
    MAIL_USERNAME = ""
    MAIL_PASSWORD = ""
    MAIL_DEFAULT_SENDER = "test@example.com"


class RestaurantReviewDashboardTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _seed_restaurant_with_reviews(self):
        restaurant_user = User(
            username="restaurant_owner",
            password="secret",
            display_name="Nha hang test",
            email="restaurant@example.com",
            role="restaurant",
        )
        customer_user = User(
            username="customer_one",
            password="secret",
            display_name="Khach hang",
            email="customer@example.com",
            phone="0900000001",
            role="customer",
        )
        db.session.add_all([restaurant_user, customer_user])
        db.session.flush()

        restaurant = Restaurant(
            restaurant_id=restaurant_user.user_id,
            address="123 Duong Test",
            area="Quan 1",
        )
        customer = Customer(customer_id=customer_user.user_id, address="456 Duong Test", area="Quan 3")
        db.session.add_all([restaurant, customer])
        db.session.flush()

        dishes = [
            Dish(restaurant_id=restaurant.restaurant_id, dish_name="Pho bo", price=50000, status=True),
            Dish(restaurant_id=restaurant.restaurant_id, dish_name="Com tam", price=45000, status=True),
            Dish(restaurant_id=restaurant.restaurant_id, dish_name="Tra dao", price=25000, status=True),
        ]
        db.session.add_all(dishes)
        db.session.flush()

        order1 = Order(customer_id=customer.customer_id, restaurant_id=restaurant.restaurant_id, order_date=_vn_dt(2026, 4, 20), status="completed")
        order2 = Order(customer_id=customer.customer_id, restaurant_id=restaurant.restaurant_id, order_date=_vn_dt(2026, 4, 21), status="completed")
        order3 = Order(customer_id=customer.customer_id, restaurant_id=restaurant.restaurant_id, order_date=_vn_dt(2026, 3, 12), status="completed")
        db.session.add_all([order1, order2, order3])
        db.session.flush()

        db.session.add_all(
            [
                OrderItem(order_id=order1.order_id, dish_id=dishes[0].dish_id, quantity=2, price=50000),
                OrderItem(order_id=order1.order_id, dish_id=dishes[1].dish_id, quantity=1, price=45000),
                OrderItem(order_id=order2.order_id, dish_id=dishes[0].dish_id, quantity=1, price=50000),
                OrderItem(order_id=order2.order_id, dish_id=dishes[2].dish_id, quantity=2, price=25000),
                OrderItem(order_id=order3.order_id, dish_id=dishes[1].dish_id, quantity=1, price=45000),
            ]
        )

        reviews = [
            Review(
                customer_id=customer.customer_id,
                restaurant_id=restaurant.restaurant_id,
                order_id=order1.order_id,
                rating=1,
                comment="Giao cham",
                sentiment="negative",
                review_date=_vn_dt(2026, 4, 22, 9, 0),
            ),
            Review(
                customer_id=customer.customer_id,
                restaurant_id=restaurant.restaurant_id,
                order_id=order2.order_id,
                rating=5,
                comment="Rat ngon",
                sentiment="positive",
                review_date=_vn_dt(2026, 4, 23, 10, 0),
            ),
            Review(
                customer_id=customer.customer_id,
                restaurant_id=restaurant.restaurant_id,
                order_id=order3.order_id,
                rating=4,
                comment="On dinh",
                sentiment="positive",
                review_date=_vn_dt(2026, 3, 18, 11, 0),
            ),
        ]
        db.session.add_all(reviews)
        db.session.commit()

        return restaurant_user, restaurant

    def _login_restaurant(self, restaurant_user):
        with self.client.session_transaction() as session:
            session["auth_state"] = "logged_in"
            session["user_role"] = "restaurant"
            session["user_id"] = restaurant_user.user_id
            session["username"] = restaurant_user.username
            session["user_display_name"] = restaurant_user.display_name

    def _seed_public_restaurant_with_many_reviews(self, review_count=13):
        restaurant_user = User(
            username="public_restaurant_owner",
            password="secret",
            display_name="Quan an cong khai",
            email="public-restaurant@example.com",
            role="restaurant",
        )
        customer_user = User(
            username="public_customer",
            password="secret",
            display_name="Nguoi danh gia",
            email="public-customer@example.com",
            phone="0900000002",
            role="customer",
        )
        db.session.add_all([restaurant_user, customer_user])
        db.session.flush()

        restaurant = Restaurant(
            restaurant_id=restaurant_user.user_id,
            address="789 Duong Cong Khai",
            area="Quan 5",
        )
        customer = Customer(customer_id=customer_user.user_id, address="111 Duong Cong Khai", area="Quan 5")
        db.session.add_all([restaurant, customer])
        db.session.flush()

        dish = Dish(
            restaurant_id=restaurant.restaurant_id,
            dish_name="Bun bo",
            category="Mon nuoc",
            price=55000,
            status=True,
        )
        db.session.add(dish)
        db.session.flush()

        for index in range(review_count):
            order = Order(
                customer_id=customer.customer_id,
                restaurant_id=restaurant.restaurant_id,
                order_date=_vn_dt(2026, 4, 1 + min(index, 27), 9, 0),
                status="completed",
            )
            db.session.add(order)
            db.session.flush()

            db.session.add(
                OrderItem(
                    order_id=order.order_id,
                    dish_id=dish.dish_id,
                    quantity=1,
                    price=55000,
                )
            )
            db.session.add(
                Review(
                    customer_id=customer.customer_id,
                    restaurant_id=restaurant.restaurant_id,
                    order_id=order.order_id,
                    rating=5 if index % 2 == 0 else 4,
                    comment=f"Review {review_count - index}",
                    sentiment="positive",
                    review_date=_vn_dt(2026, 4, 24, 12, review_count - index),
                )
            )

        db.session.commit()
        return restaurant

    def test_review_sentiment_bucket_uses_rating_thresholds(self):
        self.assertEqual(_review_sentiment_bucket(SimpleNamespace(rating=5)), "positive")
        self.assertEqual(_review_sentiment_bucket(SimpleNamespace(rating=4)), "positive")
        self.assertEqual(_review_sentiment_bucket(SimpleNamespace(rating=3)), "neutral")
        self.assertEqual(_review_sentiment_bucket(SimpleNamespace(rating=2)), "negative")
        self.assertEqual(_review_sentiment_bucket(SimpleNamespace(rating=1)), "negative")

    def test_build_reviewed_top_dishes_counts_each_order_once_per_dish(self):
        pho = SimpleNamespace(dish_id=1, dish_name="Pho bo")
        com = SimpleNamespace(dish_id=2, dish_name="Com tam")
        order_one = SimpleNamespace(
            items=[
                SimpleNamespace(dish=pho, dish_id=1, quantity=2),
                SimpleNamespace(dish=pho, dish_id=1, quantity=1),
                SimpleNamespace(dish=com, dish_id=2, quantity=1),
            ]
        )
        order_two = SimpleNamespace(
            items=[
                SimpleNamespace(dish=pho, dish_id=1, quantity=3),
            ]
        )

        result = _build_reviewed_top_dishes(
            [SimpleNamespace(order=order_one), SimpleNamespace(order=order_two)],
            limit=3,
        )

        self.assertEqual(result[0]["name"], "Pho bo")
        self.assertEqual(result[0]["reviewed_order_count"], 2)
        self.assertEqual(result[0]["total_quantity"], 6)
        self.assertEqual(result[1]["name"], "Com tam")
        self.assertEqual(result[1]["reviewed_order_count"], 1)

    def test_build_review_dashboard_computes_month_over_month_counts(self):
        with self.app.test_request_context("/restaurant/reviews"):
            with patch("app.services.restaurant_service.vietnam_today", return_value=date(2026, 4, 25)):
                with patch(
                    "app.services.restaurant_service.get_ai_review_summary_settings",
                    return_value={"enabled": True, "min_reviews": 5, "max_reviews": 30},
                ):
                    dashboard = _build_review_dashboard(
                        None,
                        [
                            SimpleNamespace(rating=5, review_date=_vn_dt(2026, 4, 10), order=None),
                            SimpleNamespace(rating=1, review_date=_vn_dt(2026, 4, 11), order=None),
                            SimpleNamespace(rating=4, review_date=_vn_dt(2026, 3, 6), order=None),
                            SimpleNamespace(rating=2, review_date=_vn_dt(2026, 3, 7), order=None),
                            SimpleNamespace(rating=2, review_date=_vn_dt(2026, 3, 8), order=None),
                        ],
                    )

        self.assertEqual(dashboard["month_over_month"]["positive"]["current_count"], 1)
        self.assertEqual(dashboard["month_over_month"]["positive"]["previous_count"], 1)
        self.assertEqual(dashboard["month_over_month"]["positive"]["delta"], 0)
        self.assertEqual(dashboard["month_over_month"]["negative"]["current_count"], 1)
        self.assertEqual(dashboard["month_over_month"]["negative"]["previous_count"], 2)
        self.assertEqual(dashboard["month_over_month"]["negative"]["delta"], -1)

    def test_reviews_page_renders_dashboard_and_review_list(self):
        restaurant_user, _restaurant = self._seed_restaurant_with_reviews()
        self._login_restaurant(restaurant_user)

        with patch("app.services.restaurant_service.vietnam_today", return_value=date(2026, 4, 25)):
            response = self.client.get("/restaurant/reviews")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Tổng quan tháng này", page)
        self.assertIn("Top 3 món theo phản hồi", page)
        self.assertIn("Danh sách đánh giá", page)

    def test_review_ai_insights_returns_400_when_threshold_not_met(self):
        restaurant_user, _restaurant = self._seed_restaurant_with_reviews()
        self._login_restaurant(restaurant_user)

        with patch(
            "app.routes.restaurant.get_ai_review_summary_settings",
            return_value={"enabled": True, "min_reviews": 5, "max_reviews": 30},
        ):
            with patch(
                "app.routes.restaurant.query_negative_reviews_for_improvement_insights",
                return_value=[{"rating": 1, "comment": "Cham"}] * 2,
            ):
                response = self.client.post("/restaurant/reviews/ai-insights")

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["threshold"], 5)

    def test_review_ai_insights_returns_payload_when_ai_succeeds(self):
        restaurant_user, _restaurant = self._seed_restaurant_with_reviews()
        self._login_restaurant(restaurant_user)

        with patch(
            "app.routes.restaurant.get_ai_review_summary_settings",
            return_value={"enabled": True, "min_reviews": 5, "max_reviews": 30},
        ):
            with patch(
                "app.routes.restaurant.query_negative_reviews_for_improvement_insights",
                return_value=[{"rating": 1, "comment": "Cham"}] * 5,
            ):
                with patch(
                    "app.routes.restaurant.generate_restaurant_review_improvement_insights",
                    return_value={
                        "insights": {
                            "overview": "Co mot so van de lap lai.",
                            "issues": ["Giao cham", "Do an nguoi di"],
                            "actions": ["Ra soat quy trinh giao", "Tach mon nuoc"],
                        },
                        "review_count_used": 5,
                        "threshold": 5,
                        "model": "gemini-test",
                    },
                ):
                    response = self.client.post("/restaurant/reviews/ai-insights")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["review_count_used"], 5)
        self.assertEqual(payload["insights"]["issues"][0], "Giao cham")

    def test_public_restaurant_context_keeps_all_reviews_for_load_more(self):
        restaurant = self._seed_public_restaurant_with_many_reviews(review_count=13)

        context = build_public_restaurant_context(restaurant.restaurant_id, include_reviews=True)

        self.assertIsNotNone(context)
        self.assertEqual(len(context["review_items"]), 13)
        self.assertFalse(context["review_has_more"])
        self.assertEqual(context["review_items"][0]["review"].comment, "Review 13")
        self.assertEqual(context["review_items"][-1]["review"].comment, "Review 1")

    def test_restaurant_detail_renders_full_review_list_without_load_more_controls(self):
        restaurant = self._seed_public_restaurant_with_many_reviews(review_count=13)

        response = self.client.get(f"/restaurants/{restaurant.restaurant_id}")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Review 13", page)
        self.assertIn("Review 1", page)
        self.assertNotIn("data-review-load-more", page)


if __name__ == "__main__":
    unittest.main()
