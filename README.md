# Fleet Management — Quản lý đội xe

Ứng dụng web quản lý phương tiện, chuyến đi và lịch bảo dưỡng, thiết kế để triển khai bằng Docker Compose. Giao diện và dữ liệu mẫu bằng tiếng Việt; backend dùng Python standard library và SQLite, không cần cài thư viện Python bên ngoài.

## Chức năng

- Tổng quan số xe, xe hoạt động, xe bảo dưỡng và chuyến đang chạy.
- Thêm, sửa, tìm kiếm và xóa phương tiện; xóa xe sẽ xóa chuyến đi/lịch bảo dưỡng liên quan.
- Ghi nhận chuyến đi, tài xế, lộ trình, ngày khởi hành, quãng đường và trạng thái.
- Lên lịch bảo dưỡng, theo dõi chi phí và trạng thái.
- REST API JSON có kiểm tra dữ liệu; kiểm tra sức khỏe dịch vụ tại `/health`.
- Dữ liệu SQLite tồn tại qua lần khởi động lại container nhờ Docker named volume.

## Chạy với Docker

Yêu cầu Docker Desktop đang chạy và hỗ trợ Docker Compose.

```powershell
docker compose up --build -d
docker compose ps
```

Các ứng dụng và dashboard:

- [Fleet Management](http://localhost:8000)
- [Dashboard thống kê Fleet Management](http://localhost:3000/d/fleet-management/fleet-management-overview?orgId=1&from=now-1h&to=now&refresh=15s)
- [Dashboard nhật ký và giám sát Loki/Promtail](http://localhost:3000/d/loki-overview/loki-and-promtail-overview?orgId=1&from=now-1h&to=now&refresh=15s)
- [Grafana](http://localhost:3000)
- [Prometheus](http://localhost:9090) · [trạng thái các target scrape](http://localhost:9090/targets)
- [Loki — trạng thái sẵn sàng](http://localhost:3100/ready)
- [Promtail — trạng thái sẵn sàng](http://localhost:9080/ready)

Hai dashboard Grafana mở trực tiếp ở chế độ xem, không cần đăng nhập; dashboard tự làm mới mỗi 15 giây. Quyền xem ẩn danh chỉ đọc. Để quản trị Grafana, đăng nhập bằng `dtc245000898@ictu.edu.vn` và mật khẩu đặt trong `GRAFANA_ADMIN_PASSWORD` (mặc định `admin`).

Dashboard **Fleet Management Overview** trong Grafana hiển thị tổng số xe, chuyến đi, lịch bảo dưỡng, số lượng theo trạng thái và access log. Phần **Giám sát hiệu suất ứng dụng** hiển thị độ trễ request p95, request mỗi giây, CPU/RAM tiến trình Fleet, số request đang xử lý và trạng thái scrape. Phần **Hiệu suất máy chủ Prometheus** hiển thị CPU/RAM của Prometheus. Các biểu đồ được lấy từ endpoint `/metrics` của ứng dụng và Prometheus tự giám sát mỗi 15 giây; log được gửi từ Promtail đến Loki. CPU/RAM là tài nguyên của tiến trình trong container, không phải số liệu toàn máy Windows. Loki và Promtail không có giao diện quản trị riêng; dùng **Explore** nếu muốn chạy truy vấn tùy chỉnh.

Dashboard **Loki & Promtail Overview** hiển thị log ứng dụng mới nhất, log trong 5xx, số log nhận được, tốc độ ghi log và tình trạng Loki/Promtail. Truy vấn `{job="fleet"}` xem toàn bộ log; `{job="fleet"} |~ " 5[0-9]{2} "` lọc request lỗi HTTP.

Grafana đã được cấu hình sẵn datasource Prometheus và Loki. Vào **Explore**, chọn **Prometheus** và thử truy vấn:

```promql
fleet_vehicles_total
fleet_vehicles_by_status
rate(fleet_http_requests_total[5m])
histogram_quantile(0.95, sum by (le, route) (rate(fleet_http_request_duration_seconds_bucket[5m])))
rate(fleet_process_cpu_seconds_total[5m]) * 100
fleet_process_resident_memory_bytes
```

Lần khởi động đầu tiên tự tạo ba phương tiện mẫu. Muốn xem bảng thống kê, mở dashboard Grafana:

- [Dashboard thống kê Fleet Management](http://localhost:3000/d/fleet-management/fleet-management-overview?orgId=1&from=now-1h&to=now&refresh=15s)
- [Dashboard log Loki/Promtail](http://localhost:3000/d/loki-overview/loki-and-promtail-overview?orgId=1&from=now-1h&to=now&refresh=15s)

Các lệnh dưới đây chỉ kiểm tra API và tình trạng dịch vụ, không phải trang dashboard. Chúng trả JSON, metrics hoặc trạng thái `ready`:

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/api/vehicles
Invoke-WebRequest http://localhost:8000/metrics | Select-Object -ExpandProperty Content
Invoke-RestMethod http://localhost:3000/api/health
Invoke-RestMethod http://localhost:3100/ready
Invoke-RestMethod http://localhost:9080/ready
```

`/health` kiểm tra ứng dụng và kết nối SQLite; `/metrics` xuất số liệu nghiệp vụ cùng metrics HTTP/process hiệu năng cho Prometheus. Access log được ghi vào volume riêng và Promtail gửi đến Loki; không cần mount Docker socket.

Đổi cổng host bằng cách sửa `FLEET_PORT` trong `.env`, ví dụ `FLEET_PORT=8080`, sau đó chạy `docker compose up -d`.

## Lệnh vận hành

```powershell
docker compose logs -f fleet     # Theo dõi log
docker compose restart fleet    # Khởi động lại
docker compose stop             # Dừng, giữ nguyên dữ liệu
docker compose start            # Chạy lại
docker compose down             # Gỡ container/network, giữ volume dữ liệu
```

Volume SQLite mặc định là `fleet_data`; `fleet_logs`, `loki_data` và `promtail_positions` lưu log và trạng thái giám sát. Sao lưu dữ liệu ứng dụng khi ứng dụng đang dừng:

```powershell
docker compose stop fleet
docker run --rm -v fleet-management-system_fleet_data:/data -v ${PWD}:/backup alpine `
  tar -czf /backup/fleet-data-backup.tar.gz -C /data .
docker compose start fleet
```

Tên volume có thể được Docker Compose thêm tiền tố theo tên thư mục dự án. Xem tên chính xác bằng `docker volume ls`. **Không** thêm `-v` vào `docker compose down` nếu muốn giữ dữ liệu.

## Chạy không dùng Docker (phát triển)

Cần Python 3.12 trở lên; không có dependency bên ngoài.

```powershell
python app/server.py
```

Mở <http://localhost:8000>. Có thể cấu hình `PORT` và `FLEET_DB_PATH` qua biến môi trường.
Khi chạy trực tiếp, hãy mở địa chỉ `localhost` được in trong terminal; `0.0.0.0` chỉ là địa chỉ bind của server, không dùng làm địa chỉ truy cập trong trình duyệt.

## API

| Method | Endpoint | Mô tả |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/api/vehicles` | Danh sách xe |
| POST | `/api/vehicles` | Tạo xe |
| GET / PUT / DELETE | `/api/vehicles/{id}` | Đọc, sửa, xóa xe |
| GET / POST | `/api/trips` | Danh sách / tạo chuyến đi |
| GET / PUT / DELETE | `/api/trips/{id}` | Đọc, sửa, xóa chuyến |
| GET / POST | `/api/maintenance` | Danh sách / tạo lịch bảo dưỡng |
| GET / PUT / DELETE | `/api/maintenance/{id}` | Đọc, sửa, xóa lịch bảo dưỡng |

## Kiểm thử

```powershell
python -m unittest discover -s tests -v
```

## Tài liệu môn học

- [Hướng dẫn triển khai](docs/DEPLOYMENT.md)
- [Vận hành và quản trị hệ thống](docs/QTHTPM.md)
