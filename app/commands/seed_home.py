import click

from app.extensions import db
from app.models import Dish, Restaurant, User
from app.services.location_service import resolve_address_for_area


RESTAURANTS = [
    {
        "username": "comtam-phucloctho",
        "display_name": "Cơm Tấm Phúc Lộc Thọ",
        "address": "123 Nguyễn Văn Linh, Phường Tân Thuận Tây, Quận 7",
        "area": "Hồ Chí Minh",
        "image": "images/com-tam.jpg",
        "description": "Quán cơm tấm quen thuộc với phần nướng đậm vị, món ăn no bụng và dễ lên hình đẹp trên trang chủ.",
        "dishes": [
            {"name": "Cơm sườn bì chả", "price": 66000, "category": "Cơm", "image": "images/com-tam.jpg", "description": "Sườn nướng mềm, bì thơm và chả trứng béo vừa."},
            {"name": "Cơm gà nướng", "price": 72000, "category": "Cơm", "image": "images/com-tam.jpg", "description": "Gà nướng vàng mặt ăn cùng cơm tấm và mỡ hành."},
            {"name": "Cơm sườn trứng ốp la", "price": 68000, "category": "Cơm", "image": "images/com-tam.jpg", "description": "Phần cơm cân bằng giữa thịt nướng, trứng và đồ chua."},
            {"name": "Cơm tấm đặc biệt", "price": 85000, "category": "Cơm", "image": "images/com-tam.jpg", "description": "Đầy đủ sườn, bì, chả, trứng cho bữa ăn chắc bụng."},
            {"name": "Canh rong biển thịt bằm", "price": 28000, "category": "Canh", "image": "images/coca_cola.jpg", "description": "Chén canh nóng thanh vị dùng kèm món chính."},
            {"name": "Coca Cola lon", "price": 15000, "category": "Đồ uống", "image": "images/coca_cola.jpg", "description": "Nước ngọt mát lạnh dùng kèm mọi phần cơm."},
        ],
    },
    {
        "username": "bundaumamtom-achanh",
        "display_name": "Bún Đậu Mắm Tôm A Chảnh",
        "address": "45 Hẻm 453 Lê Văn Sỹ, Phường 12, Quận 3",
        "area": "Hồ Chí Minh",
        "image": "images/nha_hang_bun_dau.jpg",
        "description": "Mẹt bún đậu đủ topping với đồ chiên nóng giòn, hợp để hiển thị dạng menu nhiều danh mục.",
        "dishes": [
            {"name": "Bún đậu đầy đủ", "price": 80000, "category": "Bún/Phở", "image": "images/mon_an_bun_dau.jpg", "description": "Mẹt đậu, chả cốm, nem rán và rau sống đầy đủ."},
            {"name": "Chả cốm", "price": 25000, "category": "Khai vị", "image": "images/mon_an_bun_dau.jpg", "description": "Miếng chả cốm chiên thơm, bên ngoài giòn nhẹ."},
            {"name": "Đậu hũ chiên", "price": 22000, "category": "Khai vị", "image": "images/bun-dau-mam-tom.jpg", "description": "Đậu chiên vàng giòn, chấm mắm tôm hoặc nước mắm."},
            {"name": "Nem rán Hà Nội", "price": 32000, "category": "Khai vị", "image": "images/nem-ran.jpg", "description": "Nem rán nóng giòn, nhân thịt và rau củ cân vị."},
            {"name": "Bún chả giò", "price": 62000, "category": "Bún/Phở", "image": "images/bun-cha-gio.jpg", "description": "Bún tươi ăn kèm chả giò, rau và nước mắm tỏi ớt."},
            {"name": "Trà tắc", "price": 18000, "category": "Đồ uống", "image": "images/tra_tac.jpg", "description": "Trà tắc chua ngọt giúp cân lại vị đậm của mẹt bún đậu."},
        ],
    },
    {
        "username": "phohung-nguyentrai",
        "display_name": "Phở Hùng - Nguyễn Trãi",
        "address": "241 Nguyễn Trãi, Phường Nguyễn Cư Trinh, Quận 1",
        "area": "Hồ Chí Minh",
        "image": "images/nha_hang_pho.jpg",
        "description": "Nhà hàng phở nhiều lựa chọn nước dùng và topping, phù hợp làm điểm nhấn cho nhóm món nước.",
        "dishes": [
            {"name": "Phở tái đặc biệt", "price": 65000, "category": "Bún/Phở", "image": "images/pho-tai.jpg", "description": "Nước dùng trong, thịt tái mềm và bánh phở dai vừa."},
            {"name": "Phở gà", "price": 62000, "category": "Bún/Phở", "image": "images/nha_hang_pho.jpg", "description": "Phở gà xé thanh vị với hành lá và rau thơm."},
            {"name": "Phở bò viên", "price": 68000, "category": "Bún/Phở", "image": "images/pho-tai.jpg", "description": "Bò viên dai nhẹ, hợp cho bữa sáng hoặc trưa."},
            {"name": "Bún bò nam", "price": 72000, "category": "Bún/Phở", "image": "images/bun-bo-nam.jpg", "description": "Tô bún bò nhiều thịt, nước dùng cay thơm kiểu Huế."},
            {"name": "Ram tôm giòn", "price": 42000, "category": "Khai vị", "image": "images/ram-tom.jpg", "description": "Ram tôm giòn rụm, dễ gọi thêm để ăn kèm."},
            {"name": "Trà đá ly lớn", "price": 10000, "category": "Đồ uống", "image": "images/tra_tac.jpg", "description": "Ly trà đá mát lạnh phục vụ cùng món nước."},
        ],
    },
    {
        "username": "thecoffeehouse-caothang",
        "display_name": "The Coffee House",
        "address": "88 Cao Thắng, Phường 4, Quận 3",
        "area": "Hồ Chí Minh",
        "image": "images/the_coffee_house.jpg",
        "description": "Tiệm đồ uống có thêm bánh và món ăn nhẹ, giúp giao diện menu có nhiều danh mục dễ nhìn.",
        "dishes": [
            {"name": "Bạc xỉu", "price": 39000, "category": "Đồ uống", "image": "images/the_coffee_house.jpg", "description": "Ly bạc xỉu thơm cà phê và sữa, vị ngọt dịu."},
            {"name": "Trà đào cam sả", "price": 45000, "category": "Đồ uống", "image": "images/tra_cam_the_coffee_house.jpg", "description": "Trà trái cây mát, có cam lát và hương sả dễ uống."},
            {"name": "Trà hoa lạc thần lạnh", "price": 49000, "category": "Đồ uống", "image": "images/tra_hoa_lac_than_lanh_the_coffee_house.jpg", "description": "Vị chua nhẹ, màu sắc nổi bật khi lên giao diện."},
            {"name": "Trà sữa ô long", "price": 52000, "category": "Đồ uống", "image": "images/tra_sua_Oolong.png", "description": "Trà sữa thơm ô long, hậu vị trà rõ."},
            {"name": "Bánh mì đầy đủ", "price": 35000, "category": "Món ăn nhẹ", "image": "images/banh_mi_day_du.jpg", "description": "Bánh mì mềm giòn với nhân mặn gọn gàng."},
            {"name": "Bánh cuốn chả", "price": 42000, "category": "Món ăn nhẹ", "image": "images/banh_cuon_cha.jpg", "description": "Món nhẹ no vừa, có thể dùng buổi xế."},
        ],
    },
    {
        "username": "banhmi-huynhhoa",
        "display_name": "Bánh Mì Huỳnh Hoa",
        "address": "26 Lê Thị Riêng, Phường Bến Thành, Quận 1",
        "area": "Hồ Chí Minh",
        "image": "images/banh_mi_huynh_hoa.jpg",
        "description": "Tiệm bánh mì nhân đầy đặn với món chính và nước đi kèm, phù hợp hiển thị dạng fast meal.",
        "dishes": [
            {"name": "Bánh mì pate chả lụa", "price": 70000, "category": "Bánh mì", "image": "images/banh_mi_huynh_hoa.jpg", "description": "Ổ bánh mì nổi bật với pate, chả lụa và đồ chua."},
            {"name": "Bánh mì ốp la", "price": 45000, "category": "Bánh mì", "image": "images/banh_mi_day_du.jpg", "description": "Trứng ốp la béo mềm, ăn cùng rau dưa giòn."},
            {"name": "Bánh mì đầy đủ", "price": 55000, "category": "Bánh mì", "image": "images/banh_mi_day_du.jpg", "description": "Nhân thập cẩm cho người thích vị truyền thống."},
            {"name": "Bánh mì xíu mại", "price": 48000, "category": "Bánh mì", "image": "images/banh_mi_day_du.jpg", "description": "Xíu mại sốt đậm, bánh mì giòn ruột mềm."},
            {"name": "Trà tắc", "price": 18000, "category": "Đồ uống", "image": "images/tra_tac.jpg", "description": "Nước chua ngọt nhẹ giúp bữa ăn đỡ ngấy."},
            {"name": "Coca Cola lon", "price": 15000, "category": "Đồ uống", "image": "images/coca_cola.jpg", "description": "Lựa chọn đồ uống phổ biến đi kèm bánh mì."},
        ],
    },
    {
        "username": "garan-popeyes",
        "display_name": "Gà Rán Popeyes",
        "address": "469 Nguyễn Hữu Thọ, Phường Tân Hưng, Quận 7",
        "area": "Hồ Chí Minh",
        "image": "images/ga_ran_popeyes.png",
        "description": "Mô hình fast food với combo, món chiên và đồ uống rõ ràng, rất hợp để test giao diện nhóm món.",
        "dishes": [
            {"name": "Combo gà rán nước ngọt", "price": 90000, "category": "Combo", "image": "images/combo_popeyes_2nguoi.jpg", "description": "Combo gồm gà rán, khoai và nước ngọt tiện đặt nhanh."},
            {"name": "Khoai tây chiên", "price": 35000, "category": "Khai vị", "image": "images/ga_ran_popeyes.png", "description": "Khoai chiên vàng giòn, dùng kèm sốt."},
            {"name": "Gà rán 2 miếng", "price": 69000, "category": "Món chính", "image": "images/ga_ran_popeyes.png", "description": "Gà rán giòn rụm, phần ăn vừa đủ cho một người."},
            {"name": "Burger gà cay", "price": 59000, "category": "Burger", "image": "images/ga_ran_popeyes.png", "description": "Burger gà giòn với sốt cay nhẹ."},
            {"name": "Combo 2 người", "price": 179000, "category": "Combo", "image": "images/combo_popeyes_2nguoi.jpg", "description": "Phần lớn dành cho hai người với gà và món phụ."},
            {"name": "Coca Cola lon", "price": 18000, "category": "Đồ uống", "image": "images/coca_cola.jpg", "description": "Thức uống có gas đi kèm món chiên."},
        ],
    },
    {
        "username": "pizzacompany",
        "display_name": "Pizza Company",
        "address": "68 Phan Xích Long, Phường 1, Quận Phú Nhuận",
        "area": "Hồ Chí Minh",
        "image": "images/pizza_company.jpg",
        "description": "Nhà hàng pizza và mì Ý với danh mục rõ ràng, giúp trang chi tiết có nhiều section menu hấp dẫn.",
        "dishes": [
            {"name": "Pizza hải sản", "price": 150000, "category": "Pizza", "image": "images/pizza_company.jpg", "description": "Pizza hải sản sốt đậm, viền bánh nướng vàng."},
            {"name": "Mì Ý bò bằm", "price": 99000, "category": "Mì Ý", "image": "images/pizza_bo_bam.jpg", "description": "Mì Ý sốt bò bằm dễ ăn, hợp mọi nhóm khách."},
            {"name": "Pizza bò bằm", "price": 169000, "category": "Pizza", "image": "images/pizza_bo_bam.jpg", "description": "Pizza topping bò bằm phủ đều và đậm vị."},
            {"name": "Khoai tây đút lò", "price": 52000, "category": "Khai vị", "image": "images/pizza_company.jpg", "description": "Món mở đầu béo thơm, dễ chia sẻ."},
            {"name": "Salad gà giòn", "price": 65000, "category": "Salad", "image": "images/ga_ran_popeyes.png", "description": "Rau tươi kèm gà giòn tạo sự cân bằng cho bữa ăn."},
            {"name": "Trà tắc", "price": 22000, "category": "Đồ uống", "image": "images/tra_tac.jpg", "description": "Đồ uống chua ngọt giúp đỡ ngấy sau món phô mai."},
        ],
    },
    {
        "username": "gongcha-trasua",
        "display_name": "Trà Sữa Gong Cha",
        "address": "96 Hồ Tùng Mậu, Phường Bến Nghé, Quận 1",
        "area": "Hồ Chí Minh",
        "image": "images/gong_cha.jpg",
        "description": "Cửa hàng trà sữa có topping, trà trái cây và món ăn vặt, thích hợp test giao diện nhà hàng đồ uống.",
        "dishes": [
            {"name": "Trà sữa uyên ương", "price": 66000, "category": "Đồ uống", "image": "images/gong_cha.jpg", "description": "Vị trà sữa đậm, topping linh hoạt."},
            {"name": "Trà sữa ô long", "price": 59000, "category": "Đồ uống", "image": "images/tra_sua_Oolong.png", "description": "Trà sữa thơm ô long, ngọt vừa."},
            {"name": "Trà sữa lài", "price": 56000, "category": "Đồ uống", "image": "images/tra_sua_lai.png", "description": "Mùi trà lài rõ, hậu vị nhẹ."},
            {"name": "Trà tắc nhiệt đới", "price": 49000, "category": "Đồ uống", "image": "images/tra_tac.jpg", "description": "Trà trái cây mát, màu tươi sáng."},
            {"name": "Bánh cuốn mini", "price": 35000, "category": "Ăn vặt", "image": "images/banh_cuon.jpg", "description": "Món ăn kèm lạ miệng cho cửa hàng đồ uống."},
            {"name": "Nem rán", "price": 32000, "category": "Ăn vặt", "image": "images/nem-ran.jpg", "description": "Ăn vặt giòn nóng để tăng độ đa dạng menu."},
        ],
    },
    {
        "username": "bunbo-uthung",
        "display_name": "Bún Bò Huế Út Hưng",
        "address": "456 Huỳnh Tấn Phát, Phường Bình Thuận, Quận 7",
        "area": "Hồ Chí Minh",
        "image": "images/bun-bo-nam.jpg",
        "description": "Quán bún bò kiểu Huế với món nước, đồ ăn kèm và nước uống đủ để tạo menu nhiều lớp.",
        "dishes": [
            {"name": "Bún bò tái nạm", "price": 60000, "category": "Bún/Phở", "image": "images/bun-bo-nam.jpg", "description": "Tô bún bò có tái nạm, nước dùng đậm vừa."},
            {"name": "Bún chả giò", "price": 62000, "category": "Bún/Phở", "image": "images/bun-cha-gio.jpg", "description": "Bún tươi đi cùng chả giò và rau sống."},
            {"name": "Bún bò đặc biệt", "price": 76000, "category": "Bún/Phở", "image": "images/bun-bo-nam.jpg", "description": "Phần nhiều topping cho người ăn khỏe."},
            {"name": "Bánh canh giò heo", "price": 68000, "category": "Bún/Phở", "image": "images/banh-canh-gio-heo.jpg", "description": "Nước dùng sánh nhẹ, giò heo mềm."},
            {"name": "Ram tôm", "price": 38000, "category": "Khai vị", "image": "images/ram-tom.jpg", "description": "Món ăn kèm giòn rụm, dùng trước món nước."},
            {"name": "Trà tắc", "price": 18000, "category": "Đồ uống", "image": "images/tra_tac.jpg", "description": "Ly trà tắc mát để cân vị cay nóng."},
        ],
    },
    {
        "username": "sushitei",
        "display_name": "Sushi Tei",
        "address": "5 Lý Tự Trọng, Phường Bến Nghé, Quận 1",
        "area": "Hồ Chí Minh",
        "image": "images/banh-uot-thap-cam.jpg",
        "description": "Nhà hàng phong cách Nhật với cơm, món chính và đồ uống, đủ đa dạng để test section tương tự.",
        "dishes": [
            {"name": "Phần cá ngừ", "price": 266000, "category": "Sushi", "image": "images/banh-uot-thap-cam.jpg", "description": "Phần ăn cao cấp, trình bày đẹp trên giao diện."},
            {"name": "Sushi tổng hợp", "price": 245000, "category": "Sushi", "image": "images/banh-uot-thap-cam.jpg", "description": "Set nhiều loại sushi cho khách muốn chọn nhanh."},
            {"name": "Cơm cuộn tempura", "price": 169000, "category": "Sushi", "image": "images/ram-tom.jpg", "description": "Cuộn chiên giòn, dễ tiếp cận với người mới ăn."},
            {"name": "Cơm gà teriyaki", "price": 129000, "category": "Cơm", "image": "images/com-tam.jpg", "description": "Cơm nóng với gà sốt ngọt mặn kiểu Nhật."},
            {"name": "Salad rong biển", "price": 59000, "category": "Salad", "image": "images/tra_tac.jpg", "description": "Món khai vị thanh mát, phù hợp menu Nhật."},
            {"name": "Trà lạnh", "price": 25000, "category": "Đồ uống", "image": "images/tra_tac.jpg", "description": "Đồ uống đơn giản để đi cùng set sushi."},
        ],
    },
    {
        "username": "miquang-bepdanang",
        "display_name": "Mì Quảng Bếp Đà Nẵng",
        "address": "18 Nguyễn Gia Trí, Phường 25, Quận Bình Thạnh",
        "area": "Hồ Chí Minh",
        "image": "images/mi-quang.jpg",
        "description": "Quán mì Quảng tập trung món miền Trung với nước dùng ít, topping đa dạng và ảnh món nổi bật.",
        "dishes": [
            {"name": "Mì Quảng gà", "price": 62000, "category": "Mì/Phở", "image": "images/mi-quang.jpg", "description": "Mì Quảng gà xé với đậu phộng và rau sống."},
            {"name": "Mì Quảng tôm thịt", "price": 68000, "category": "Mì/Phở", "image": "images/mi-quang.jpg", "description": "Tôm thịt đầy đặn, nước sốt đậm vừa."},
            {"name": "Bánh xèo miền Trung", "price": 45000, "category": "Khai vị", "image": "images/banh-xeo.jpg", "description": "Bánh xèo giòn vàng ăn với rau và nước chấm."},
            {"name": "Ram tôm đất", "price": 38000, "category": "Khai vị", "image": "images/ram-tom.jpg", "description": "Ram nhỏ cuốn tôm, chiên giòn ăn vui miệng."},
            {"name": "Trà tắc", "price": 18000, "category": "Đồ uống", "image": "images/tra_tac.jpg", "description": "Đồ uống chua nhẹ phù hợp món miền Trung."},
            {"name": "Bánh cuốn chả", "price": 42000, "category": "Ăn nhẹ", "image": "images/banh_cuon_cha.jpg", "description": "Thêm lựa chọn ăn nhẹ để menu phong phú hơn."},
        ],
    },
    {
        "username": "laubo-ongmap",
        "display_name": "Lẩu Bò Ông Mập",
        "address": "210 Phạm Văn Đồng, Phường 1, Quận Gò Vấp",
        "area": "Hồ Chí Minh",
        "image": "images/lau-bo.jpg",
        "description": "Quán lẩu với món dùng nhóm, món nhúng và món khai vị, giúp trang chi tiết có nhiều danh mục rõ ràng.",
        "dishes": [
            {"name": "Lẩu bò thập cẩm", "price": 189000, "category": "Lẩu", "image": "images/lau-bo.jpg", "description": "Nồi lẩu bò đủ gân, nạm và rau ăn kèm."},
            {"name": "Lẩu thập cẩm", "price": 209000, "category": "Lẩu", "image": "images/lau-thap-cam.jpg", "description": "Phần lẩu nhiều topping dành cho nhóm bạn."},
            {"name": "Lẩu cá", "price": 179000, "category": "Lẩu", "image": "images/lau-ca.jpg", "description": "Nồi lẩu cá vị chua cay thanh, hợp ăn tối."},
            {"name": "Bò viên nhúng lẩu", "price": 49000, "category": "Món thêm", "image": "images/lau-bo.jpg", "description": "Phần topping gọi thêm để ăn cùng nồi lẩu."},
            {"name": "Nem rán", "price": 36000, "category": "Khai vị", "image": "images/nem-ran.jpg", "description": "Khai vị giòn nóng trước khi vào nồi lẩu."},
            {"name": "Coca Cola chai", "price": 20000, "category": "Đồ uống", "image": "images/coca_cola.jpg", "description": "Nước ngọt dùng cùng món lẩu và món nhúng."},
        ],
    },
    {
        "username": "bunrieu-coba",
        "display_name": "Bún Riêu Cô Ba",
        "address": "55 Nguyễn Thái Bình, Phường 4, Quận Tân Bình",
        "area": "Hồ Chí Minh",
        "image": "images/bun-rieu.jpg",
        "description": "Quán bún riêu có món nước, món cuốn và đồ uống bình dân, tạo dữ liệu menu rất tự nhiên cho app.",
        "dishes": [
            {"name": "Bún riêu cua", "price": 58000, "category": "Bún/Phở", "image": "images/bun-rieu.jpg", "description": "Tô bún riêu cua đậm đà với chả và huyết."},
            {"name": "Bún riêu đặc biệt", "price": 68000, "category": "Bún/Phở", "image": "images/bun-rieu.jpg", "description": "Thêm giò, chả và topping cho phần ăn tròn vị."},
            {"name": "Bún chả", "price": 62000, "category": "Bún/Phở", "image": "images/bun-cha.jpg", "description": "Bún chả nướng thơm, rau sống tươi."},
            {"name": "Bánh cuốn", "price": 42000, "category": "Ăn nhẹ", "image": "images/banh_cuon.jpg", "description": "Bánh cuốn mềm, có hành phi và chả."},
            {"name": "Chả giò", "price": 35000, "category": "Khai vị", "image": "images/nem-ran.jpg", "description": "Cuốn chiên giòn ăn kèm nước mắm chua ngọt."},
            {"name": "Trà đá", "price": 10000, "category": "Đồ uống", "image": "images/tra_tac.jpg", "description": "Ly trà đá cơ bản, dễ ghép vào mọi đơn hàng."},
        ],
    },
    {
        "username": "banhxeo-muoixiem",
        "display_name": "Bánh Xèo Mười Xiềm",
        "address": "204 Nam Kỳ Khởi Nghĩa, Phường Võ Thị Sáu, Quận 3",
        "area": "Hồ Chí Minh",
        "image": "images/banh-xeo.jpg",
        "description": "Nhà hàng bánh xèo và món cuốn miền Nam, có hình ảnh món ăn bắt mắt để lên card đẹp.",
        "dishes": [
            {"name": "Bánh xèo tôm thịt", "price": 79000, "category": "Bánh xèo", "image": "images/banh-xeo.jpg", "description": "Bánh xèo vàng giòn với nhân tôm thịt đầy đặn."},
            {"name": "Bánh xèo đầy đủ", "price": 95000, "category": "Bánh xèo", "image": "images/banh_xeo_day_du.jpg", "description": "Phần lớn hơn với nhiều topping và rau kèm."},
            {"name": "Bánh ướt thập cẩm", "price": 52000, "category": "Món cuốn", "image": "images/banh-uot-thap-cam.jpg", "description": "Bánh ướt mềm, topping phong phú dễ ăn."},
            {"name": "Bánh cuốn chả", "price": 48000, "category": "Món cuốn", "image": "images/banh_cuon_cha.jpg", "description": "Món cuốn mềm mượt, có thêm chả thơm."},
            {"name": "Ram tôm", "price": 36000, "category": "Khai vị", "image": "images/ram-tom.jpg", "description": "Ram tôm giòn nhỏ, hợp ăn khai vị hoặc gọi thêm."},
            {"name": "Trà tắc", "price": 18000, "category": "Đồ uống", "image": "images/tra_tac.jpg", "description": "Đồ uống quen thuộc khi ăn món chiên và cuốn."},
        ],
    },
    {
        "username": "banhcuon-thanhtri",
        "display_name": "Bánh Cuốn Thanh Trì",
        "address": "72 Cách Mạng Tháng 8, Phường 6, Quận 3",
        "area": "Hồ Chí Minh",
        "image": "images/banh_cuon.jpg",
        "description": "Quán bánh cuốn sáng tối với món cuốn, món nước nhẹ và đồ uống cơ bản, rất hợp để test menu phân nhóm.",
        "dishes": [
            {"name": "Bánh cuốn nóng", "price": 42000, "category": "Món cuốn", "image": "images/banh_cuon.jpg", "description": "Bánh cuốn nóng mềm với hành phi thơm nhẹ."},
            {"name": "Bánh cuốn chả", "price": 48000, "category": "Món cuốn", "image": "images/banh_cuon_cha.jpg", "description": "Thêm chả quế giúp phần ăn đầy đặn hơn."},
            {"name": "Bánh ướt thập cẩm", "price": 54000, "category": "Món cuốn", "image": "images/banh-uot-thap-cam.jpg", "description": "Lựa chọn khác cho khách thích món mềm thanh."},
            {"name": "Bún chả", "price": 62000, "category": "Bún/Phở", "image": "images/bun-cha.jpg", "description": "Bún chả nướng đậm vị để menu không bị một màu."},
            {"name": "Nem rán", "price": 32000, "category": "Khai vị", "image": "images/nem-ran.jpg", "description": "Món chiên dễ gọi thêm, tạo sự đa dạng danh mục."},
            {"name": "Trà đá", "price": 10000, "category": "Đồ uống", "image": "images/tra_tac.jpg", "description": "Đồ uống đơn giản đi cùng các món cuốn."},
        ],
    },
]

SEED_LOCATION_FALLBACKS = {
    ("123 Nguyễn Văn Linh, Phường Tân Thuận Tây, Quận 7", "Hồ Chí Minh"): (10.752172, 106.725394),
    ("45 Hẻm 453 Lê Văn Sỹ, Phường 12, Quận 3", "Hồ Chí Minh"): (10.78909, 106.67361),
    ("241 Nguyễn Trãi, Phường Nguyễn Cư Trinh, Quận 1", "Hồ Chí Minh"): (10.76484, 106.68762),
    ("88 Cao Thắng, Phường 4, Quận 3", "Hồ Chí Minh"): (10.77105, 106.681039),
    ("26 Lê Thị Riêng, Phường Bến Thành, Quận 1", "Hồ Chí Minh"): (10.77141, 106.692417),
    ("469 Nguyễn Hữu Thọ, Phường Tân Hưng, Quận 7", "Hồ Chí Minh"): (10.741028, 106.701958),
    ("68 Phan Xích Long, Phường 1, Quận Phú Nhuận", "Hồ Chí Minh"): (10.801063, 106.683374),
    ("96 Hồ Tùng Mậu, Phường Bến Nghé, Quận 1", "Hồ Chí Minh"): (10.77279, 106.70349),
    ("456 Huỳnh Tấn Phát, Phường Bình Thuận, Quận 7", "Hồ Chí Minh"): (10.74491, 106.72923),
    ("5 Lý Tự Trọng, Phường Bến Nghé, Quận 1", "Hồ Chí Minh"): (10.782375, 106.705336),
    ("18 Nguyễn Gia Trí, Phường 25, Quận Bình Thạnh", "Hồ Chí Minh"): (10.80379, 106.71418),
    ("210 Phạm Văn Đồng, Phường 1, Quận Gò Vấp", "Hồ Chí Minh"): (10.83568, 106.68941),
    ("55 Nguyễn Thái Bình, Phường 4, Quận Tân Bình", "Hồ Chí Minh"): (10.79353, 106.65632),
    ("204 Nam Kỳ Khởi Nghĩa, Phường Võ Thị Sáu, Quận 3", "Hồ Chí Minh"): (10.78669, 106.69025),
    ("72 Cách Mạng Tháng 8, Phường 6, Quận 3", "Hồ Chí Minh"): (10.77874, 106.68462),
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
    restaurant.description = spec.get("description") or f"Nhà hàng phục vụ món {spec['display_name']}"
    restaurant.platform_fee = restaurant.platform_fee or 0
    return restaurant, restaurant in db.session.new


def _upsert_dish(restaurant_id, dish_spec):
    dish = Dish.query.filter_by(restaurant_id=restaurant_id, dish_name=dish_spec["name"]).one_or_none()
    if not dish:
        dish = Dish(restaurant_id=restaurant_id, dish_name=dish_spec["name"])
        db.session.add(dish)

    dish.dish_name = dish_spec["name"]
    dish.category = dish_spec.get("category") or dish.category or "Món chính"
    dish.image = dish_spec.get("image") or dish.image
    dish.price = dish_spec["price"]
    dish.description = dish_spec.get("description") or dish.description or dish_spec["name"]
    dish.status = True
    return dish, dish in db.session.new


@click.command("seed-home")
def seed_home_command():
    """Seed restaurant and dish data for the home and restaurant pages."""
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
