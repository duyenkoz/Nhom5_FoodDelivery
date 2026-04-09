from copy import deepcopy


_HOME_PAGE_DATA = {
    "search_placeholder": "Tìm món ăn hoặc nhà hàng",
    "hero_title": "Địa chỉ bạn muốn giao món",
    "hero_placeholder": "Nhập địa chỉ của bạn",
    "empty_title": "Không tìm thấy quán phù hợp",
    "empty_description": "Hãy thử tìm bằng tên quán, món ăn hoặc địa chỉ khác.",
    "sections": [
        {"title": "Gợi ý món ăn", "load_more_label": "Xem thêm"},
        {"title": "Quán ăn gần bạn", "load_more_label": "Xem thêm"},
        {"title": "Nhà hàng đánh giá cao", "load_more_label": "Xem thêm"},
    ],
}


def get_home_page_data():
    return deepcopy(_HOME_PAGE_DATA)
