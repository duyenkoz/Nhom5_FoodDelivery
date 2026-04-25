import unittest
from datetime import datetime
from types import SimpleNamespace

from app.services.home_recommendation_service import _build_user_history_profile, _rank_candidate_restaurants
from app.utils.time_utils import VIETNAM_TZ


def _dish(name, category, description="", status=True):
    return SimpleNamespace(dish_name=name, category=category, description=description, status=status)


def _item(dish, quantity=1):
    return SimpleNamespace(dish=dish, quantity=quantity)


def _order(restaurant_id, status, order_date, items):
    return SimpleNamespace(restaurant_id=restaurant_id, status=status, order_date=order_date, items=items)


def _payload(restaurant_id, dishes, distance_km=None):
    restaurant = SimpleNamespace(restaurant_id=restaurant_id, dishes=dishes)
    return {
        "restaurant": restaurant,
        "active_dish_count": len([dish for dish in dishes if getattr(dish, "status", False)]),
        "distance_km": distance_km,
    }


class HomeRecommendationServiceTests(unittest.TestCase):
    def test_evening_drink_history_prefers_drink_restaurant(self):
        drink_order = _order(
            2,
            "completed",
            datetime(2026, 4, 20, 19, 30, tzinfo=VIETNAM_TZ),
            [_item(_dish("Trà sữa ô long", "Đồ uống"), quantity=2)],
        )
        history = _build_user_history_profile([drink_order])
        payloads = [
            _payload(1, [_dish("Cơm sườn", "Cơm"), _dish("Canh rong biển", "Canh")], distance_km=1.2),
            _payload(2, [_dish("Trà sữa trân châu", "Đồ uống"), _dish("Trà đào", "Đồ uống")], distance_km=2.5),
        ]

        ranked_ids = _rank_candidate_restaurants(
            payloads,
            history,
            popularity_map={1: 8, 2: 6},
            promotion_map={1: False, 2: False},
            slot="dinner",
            now=datetime(2026, 4, 24, 19, 0, tzinfo=VIETNAM_TZ),
        )

        self.assertEqual(ranked_ids[0], 2)

    def test_lunch_rice_history_prefers_rice_restaurant(self):
        rice_order = _order(
            3,
            "delivered",
            datetime(2026, 4, 21, 12, 15, tzinfo=VIETNAM_TZ),
            [_item(_dish("Cơm gà nướng", "Cơm"), quantity=1)],
        )
        history = _build_user_history_profile([rice_order])
        payloads = [
            _payload(3, [_dish("Cơm tấm sườn bì chả", "Cơm"), _dish("Cơm gà", "Cơm")], distance_km=3.0),
            _payload(4, [_dish("Trà sữa kem cheese", "Đồ uống"), _dish("Trà đào", "Đồ uống")], distance_km=1.0),
        ]

        ranked_ids = _rank_candidate_restaurants(
            payloads,
            history,
            popularity_map={3: 4, 4: 10},
            promotion_map={3: False, 4: False},
            slot="lunch",
            now=datetime(2026, 4, 24, 12, 0, tzinfo=VIETNAM_TZ),
        )

        self.assertEqual(ranked_ids[0], 3)

    def test_cold_start_uses_time_popularity_and_promotion(self):
        history = _build_user_history_profile([])
        payloads = [
            _payload(5, [_dish("Trà sữa matcha", "Đồ uống"), _dish("Hồng trà", "Đồ uống")], distance_km=2.0),
            _payload(6, [_dish("Trà sữa truyền thống", "Đồ uống"), _dish("Bánh flan", "Tráng miệng")], distance_km=1.5),
        ]

        ranked_ids = _rank_candidate_restaurants(
            payloads,
            history,
            popularity_map={5: 11, 6: 11},
            promotion_map={5: False, 6: True},
            slot="afternoon",
            now=datetime(2026, 4, 24, 15, 0, tzinfo=VIETNAM_TZ),
        )

        self.assertEqual(ranked_ids[0], 6)

    def test_non_completed_orders_do_not_contribute_to_history(self):
        mixed_orders = [
            _order(
                7,
                "cancelled",
                datetime(2026, 4, 20, 19, 0, tzinfo=VIETNAM_TZ),
                [_item(_dish("Trà sữa", "Đồ uống"), quantity=3)],
            ),
            _order(
                8,
                "pending",
                datetime(2026, 4, 21, 12, 0, tzinfo=VIETNAM_TZ),
                [_item(_dish("Cơm gà", "Cơm"), quantity=2)],
            ),
            _order(
                9,
                "completed",
                datetime(2026, 4, 22, 8, 0, tzinfo=VIETNAM_TZ),
                [_item(_dish("Bánh mì ốp la", "Bánh mì"), quantity=1)],
            ),
        ]

        history = _build_user_history_profile(mixed_orders)

        self.assertEqual(history["restaurant_order_counts"][9], 1)
        self.assertNotIn(7, history["restaurant_order_counts"])
        self.assertNotIn(8, history["restaurant_order_counts"])
        self.assertEqual(history["category_counts"]["banh mi"], 1)
        self.assertFalse(history["category_counts"].get("do uong"))
        self.assertFalse(history["category_counts"].get("com"))


if __name__ == "__main__":
    unittest.main()
