# Quản trị hệ thống phần mềm (QTHTPM)

## 1. Thông tin hệ thống

| Hạng mục | Giá trị |
|---|---|
| Hệ thống | Fleet Management — Quản lý đội xe |
| Thành phần chạy | Một container `fleet-management` |
| Nền tảng | Python 3.12 slim, Docker Compose |
| Lưu trữ | SQLite tại `/data/fleet.db` |
| Lưu bền | Docker named volume `fleet_data` |
| Cổng mặc định | TCP 8000 (đổi bằng `FLEET_PORT`) |
| Kiểm tra sức khỏe | HTTP `GET /health` |

## 2. Quy trình khởi động và dừng

Tại thư mục dự án:

```powershell
docker compose up -d
docker compose ps
docker compose stop
docker compose start
```

`docker compose down` gỡ container và network nhưng giữ dữ liệu. Tránh `docker compose down -v` trừ khi chủ sở hữu dữ liệu đã cho phép xóa dữ liệu và có backup được xác nhận.

## 3. Giám sát và xử lý sự cố

```powershell
docker compose ps
docker compose logs --tail 100 fleet
docker inspect --format '{{json .State.Health}}' fleet-management
Invoke-RestMethod http://localhost:8000/health
```

| Hiện tượng | Kiểm tra | Xử lý |
|---|---|---|
| Không mở được giao diện | `docker compose ps`, log, `FLEET_PORT`, firewall | Đảm bảo container healthy; đổi cổng host nếu bị chiếm và mở đúng rule firewall |
| Health `unhealthy` | `docker compose logs fleet`; endpoint `/health` | Xem lỗi khởi động, quyền ghi volume hoặc lỗi SQLite; khắc phục nguyên nhân rồi restart |
| API trả lỗi dữ liệu | JSON thông báo lỗi trong response | Kiểm tra trường bắt buộc, ngày `YYYY-MM-DD`, trạng thái và xe liên kết |
| Dữ liệu không còn sau khi khởi động | `docker volume ls`, `docker compose config` | Xác nhận đúng thư mục Compose/project và named volume; không tạo volume mới khi chưa kiểm tra dữ liệu cũ |
| Cổng đã sử dụng | Thông báo bind port trong log Docker | Đổi `FLEET_PORT` trong `.env`, rồi `docker compose up -d` |

Ghi nhận thời điểm, triệu chứng, lệnh đã chạy và kết quả trước khi chuyển sự cố cho người phụ trách.

## 4. Bảo trì và backup

- Xem log và health định kỳ; cảnh báo khi container dừng/unhealthy hoặc dung lượng đĩa gần đầy.
- Backup SQLite khi ứng dụng dừng; lưu ít nhất một bản sao ngoài máy chạy Docker.
- Kiểm tra khả năng mở file backup và thực hành khôi phục trước khi coi backup là hợp lệ.
- Cập nhật Python base image có chủ đích; build và nghiệm thu lại trước khi thay image đang chạy.
- Không chỉnh sửa/xóa trực tiếp volume khi ứng dụng đang hoạt động.

## 5. Bảo mật và quyền truy cập

- Container chạy user không phải root, drop capabilities, `no-new-privileges` và chỉ công bố cổng ứng dụng.
- Không đưa file `.env`/database/backup vào Git hoặc image; file `.env` đã được `.dockerignore` loại trừ.
- Ứng dụng bài tập hiện chưa có đăng nhập/phân quyền, HTTPS hay audit log: chỉ dùng dữ liệu demo hoặc mạng nội bộ tin cậy. Trước khi mở Internet, cần triển khai xác thực, TLS qua reverse proxy, chính sách truy cập, backup ngoài máy và rà soát bảo mật.
- Giới hạn người được quyền vào Docker host; quyền truy cập Docker tương đương quyền quản trị máy.

## 6. Phân quyền và trách nhiệm

| Vai trò | Trách nhiệm |
|---|---|
| Quản trị viên máy triển khai | Docker host, port, volume, backup, cập nhật và khôi phục |
| Người vận hành đội xe | Nhập/sửa dữ liệu phương tiện, chuyến đi và bảo dưỡng |
| Giảng viên/người nghiệm thu | Kiểm tra chức năng, trạng thái triển khai và tài liệu |

## 7. Danh sách bàn giao

- Mã nguồn, `Dockerfile`, `compose.yaml`, `.env.example`.
- Tài liệu triển khai và QTHTPM này.
- Port thực tế, thời điểm triển khai, phiên bản mã nguồn/image, trạng thái health.
- Vị trí lưu backup và người chịu trách nhiệm phục hồi.
- Xác nhận các hạn chế đã biết: bản demo chưa có xác thực người dùng và HA.
