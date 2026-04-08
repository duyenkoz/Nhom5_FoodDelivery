# Food Delivery Flask Project

Skeleton Flask project for a food delivery website.

## Cài đặt

- Cài uv để quản lý venv, các thư viện, mở Power Shell lên và copy paste lệnh này, nhấn enter để cài

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

- Tạo venv cho project ở local để cài các thư viện của project

```powershell
uv venv
```

- Sau đó tiến hành active môi trường:

```
.venv\Scripts\activate
```

- Cài các thư viện tương ứng từ file requirement
```bash
uv pip install -r requirements.txt
```

## Chạy project

```bash
python run.py
```

Mặc định app sẽ chạy ở:

```text
http://localhost:5000 hoặc http://127.0.0.1:5000, nên dùng domain localhost
```

## Cấu trúc chính

- `app/`: source code của ứng dụng Flask
- `app/models/`: model database
- `app/routes/`: route/blueprint
- `app/templates/`: file HTML Jinja2
- `app/static/`: CSS, JS, hình ảnh
- `config.py`: cấu hình ứng dụng
- `run.py`: entry point để chạy app
- `requirements.txt`: danh sách thư viện cần cài

