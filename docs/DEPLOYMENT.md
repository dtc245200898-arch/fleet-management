# Hướng dẫn triển khai Fleet Management

## 1. Mục tiêu và phạm vi

Triển khai ứng dụng web quản lý đội xe cho môi trường demo/lab bằng Docker Compose trên một máy chủ. Một container chạy web/API và một named volume lưu SQLite; không cần dịch vụ cơ sở dữ liệu riêng.

## 2. Kiến trúc triển khai

```text
Trình duyệt
    ├── Fleet Management :8000 (có thể đổi bằng FLEET_PORT)
    ├── Grafana :3000 ── Prometheus :9090
    └── Grafana Explore ── Loki :3100

Docker Compose
    ├── fleet-management (Python 3.12, UID không đặc quyền)
    │       ├── UI + REST API + /metrics (business and HTTP/process performance)
    │       ├── /data/fleet.db ── named volume: fleet_data
    │       └── /logs/fleet.log ── named volume: fleet_logs
    ├── Promtail :9080 ── đọc fleet_logs, gửi log đến Loki
    ├── Loki :3100 ── lưu log ở named volume: loki_data
    ├── Prometheus :9090 ── scrape fleet:8000/metrics, prometheus:9090,
    │                       loki:3100/metrics và promtail:9080/metrics
    └── Grafana :3000 ── provision datasource Prometheus/Loki và dashboard Fleet/Loki
```

Compose tự xây image, tự khởi động lại container và kiểm tra sức khỏe các dịch vụ có health check. Ứng dụng bỏ toàn bộ Linux capabilities và ngăn nâng quyền. Các cổng giám sát chỉ bind vào `127.0.0.1`; Grafana cho phép xem dashboard ẩn danh ở quyền Viewer để mở link biểu đồ mà không cần đăng nhập. Promtail chỉ đọc volume log dùng chung, không cần quyền truy cập Docker socket. SQLite/Loki dùng filesystem phù hợp bài tập/demo một máy, lưu lượng thấp; đây chưa phải cấu hình HA hoặc lưu trữ đa máy chủ.

## 3. Môi trường yêu cầu

- Windows 10/11 có Docker Desktop và Docker Compose v2.
- Tối thiểu 2 CPU, 2 GB RAM trống và khoảng 1 GB dung lượng đĩa.
- Các cổng TCP 8000, 3000, 9090, 3100 và 9080 chưa bị ứng dụng khác sử dụng; đổi `FLEET_PORT` nếu cổng 8000 đang bận.
- Nếu triển khai trên máy chủ: chỉ mở cổng ứng dụng cho mạng cần truy cập; cấu hình firewall và HTTPS ở reverse proxy/gateway bên ngoài.

## 4. Triển khai lần đầu

Mở PowerShell tại thư mục dự án:

```powershell
Copy-Item .env.example .env
docker info
docker compose config
docker compose up --build -d
docker compose ps
```

Khi các container đã chạy, mở [dashboard Fleet Management](http://localhost:3000/d/fleet-management/fleet-management-overview?orgId=1&from=now-1h&to=now&refresh=15s) hoặc [dashboard Loki/Promtail](http://localhost:3000/d/loki-overview/loki-and-promtail-overview?orgId=1&from=now-1h&to=now&refresh=15s); quyền Viewer ẩn danh không yêu cầu đăng nhập. Grafana cũng có tại `http://localhost:3000`, Prometheus tại `http://localhost:9090`, trạng thái Loki tại `http://localhost:3100/ready` và trạng thái Promtail tại `http://localhost:9080/ready`. Trong Grafana **Explore**, chọn **Loki** rồi chạy `{job="fleet"}` để kiểm tra log. Xác thực endpoint:

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/api/vehicles
Invoke-RestMethod http://localhost:3100/ready
Invoke-RestMethod http://localhost:9080/ready
```

`/health` trả `{"status":"ok"}`. Lần chạy đầu tạo SQLite schema và ba xe mẫu; các lần khởi động sau giữ dữ liệu qua volume `fleet_data`.

## 5. Cập nhật phiên bản

1. Sao lưu volume dữ liệu và xác nhận tệp sao lưu đọc được.
2. Lấy phiên bản mã nguồn đã kiểm tra từ kho Git.
3. Chạy `docker compose build --no-cache fleet`.
4. Chạy `docker compose up -d --no-deps fleet`.
5. Chờ health check, thử mở giao diện, danh sách xe, tạo/sửa một bản ghi kiểm thử.
6. Nếu lỗi, xem log và quay lại image/mã nguồn trước; giữ nguyên volume.

Thay đổi schema hiện được khởi tạo theo kiểu tương thích `CREATE TABLE IF NOT EXISTS`; trước khi phát triển thay đổi schema phá vỡ tương thích cần bổ sung migration có phiên bản và kiểm thử backup/restore.

## 6. Sao lưu và khôi phục

Dừng ghi dữ liệu trước khi tạo bản sao lưu nhất quán. Làm theo lệnh trong README, kiểm tra archive, lưu bản sao ngoài máy chủ triển khai và giới hạn người truy cập. Ghi lại ngày giờ, kích thước và nơi lưu backup.

Khôi phục: dừng dịch vụ, giữ một bản sao volume hiện hành, nạp archive vào đúng named volume, chạy lại stack và xác minh `/health`, số bản ghi và các chức năng đọc/ghi. Không dùng `docker compose down -v` trong quy trình bảo trì thông thường vì lệnh đó xóa volume.

## 7. Nghiệm thu triển khai

- `docker compose config` hợp lệ.
- Container hoạt động với health `healthy`.
- Giao diện mở được; xe mẫu hiển thị.
- Thêm/sửa/tìm/xóa xe và ghi nhận chuyến đi/bảo dưỡng hoạt động.
- Khởi động lại container không làm mất dữ liệu.
- Grafana truy vấn được cả Prometheus và Loki; Loki nhận log với nhãn `job="fleet"`.
- Dashboard Fleet Management hiển thị số liệu nghiệp vụ, request rate/latency, CPU/RAM tiến trình Fleet và CPU/RAM Prometheus; dashboard Loki hiển thị log và tình trạng pipeline Loki/Promtail.
- Log không có lỗi bất thường; port và trạng thái container đã ghi vào biên bản.
