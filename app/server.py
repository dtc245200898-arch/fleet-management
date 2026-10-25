import json
import logging
import math
import os
import re
import sqlite3
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
DATABASE_PATH = Path(os.environ.get("FLEET_DB_PATH", ROOT.parent / "data" / "fleet.db"))
MAX_BODY_BYTES = 64 * 1024
METRIC_DURATION_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
METRIC_LOCK = threading.Lock()
METRIC_REQUESTS = defaultdict(int)
METRIC_DURATION_BUCKETS_COUNTS = defaultdict(lambda: [0] * len(METRIC_DURATION_BUCKETS))
METRIC_DURATION_SUM = defaultdict(float)
METRIC_DURATION_COUNT = defaultdict(int)
METRIC_IN_PROGRESS = 0
PROCESS_START_TIME = time.monotonic()
RESOURCE_FIELDS = {
    "vehicles": {
        "required": ("registration", "make", "model", "year", "status"),
        "optional": ("mileage",),
        "strings": ("registration", "make", "model", "status"),
        "statuses": ("Hoạt động", "Bảo trì", "Ngừng hoạt động"),
    },
    "trips": {
        "required": ("vehicle_id", "driver", "origin", "destination", "departure_date", "status"),
        "optional": ("arrival_date", "distance_km"),
        "strings": ("driver", "origin", "destination", "departure_date", "status"),
        "statuses": ("Đã lên lịch", "Đang thực hiện", "Hoàn thành", "Đã hủy"),
    },
    "maintenance": {
        "required": ("vehicle_id", "service_date", "service_type", "cost", "description", "status"),
        "optional": (),
        "strings": ("service_date", "service_type", "description", "status"),
        "statuses": ("Đã lên lịch", "Đang thực hiện", "Hoàn thành"),
    },
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    registration TEXT NOT NULL UNIQUE,
    make TEXT NOT NULL,
    model TEXT NOT NULL,
    year INTEGER NOT NULL CHECK (year BETWEEN 1950 AND 2100),
    mileage INTEGER NOT NULL DEFAULT 0 CHECK (mileage >= 0),
    status TEXT NOT NULL CHECK (status IN ('Hoạt động', 'Bảo trì', 'Ngừng hoạt động')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS trips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id INTEGER NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
    driver TEXT NOT NULL,
    origin TEXT NOT NULL,
    destination TEXT NOT NULL,
    departure_date TEXT NOT NULL,
    arrival_date TEXT,
    distance_km REAL NOT NULL DEFAULT 0 CHECK (distance_km >= 0),
    status TEXT NOT NULL CHECK (status IN ('Đã lên lịch', 'Đang thực hiện', 'Hoàn thành', 'Đã hủy')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS maintenance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id INTEGER NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
    service_date TEXT NOT NULL,
    service_type TEXT NOT NULL,
    cost REAL NOT NULL CHECK (cost >= 0),
    description TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('Đã lên lịch', 'Đang thực hiện', 'Hoàn thành')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class ValidationError(Exception):
    pass


def connect_database(database_path=DATABASE_PATH):
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def database_connection(database_path=DATABASE_PATH):
    connection = connect_database(database_path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database(database_path=DATABASE_PATH):
    with database_connection(database_path) as connection:
        connection.executescript(SCHEMA)
        if connection.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0] == 0:
            connection.executemany(
                """INSERT INTO vehicles (registration, make, model, year, mileage, status)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    ("51A-123.45", "Toyota", "Fortuner", 2022, 28500, "Hoạt động"),
                    ("51B-678.90", "Ford", "Transit", 2021, 41200, "Bảo trì"),
                    ("60C-246.80", "Hyundai", "Solati", 2023, 15800, "Hoạt động"),
                ],
            )


def validate_payload(resource, payload, vehicle_ids):
    definition = RESOURCE_FIELDS[resource]
    if not isinstance(payload, dict):
        raise ValidationError("Dữ liệu gửi lên phải là một đối tượng JSON.")

    allowed = set(definition["required"]) | set(definition["optional"])
    unknown = set(payload) - allowed
    if unknown:
        raise ValidationError(f"Trường dữ liệu không được hỗ trợ: {', '.join(sorted(unknown))}.")

    missing = [field for field in definition["required"] if field not in payload]
    if missing:
        raise ValidationError(f"Thiếu trường bắt buộc: {', '.join(missing)}.")

    cleaned = {}
    for field in definition["strings"]:
        value = payload[field]
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"'{field}' phải là chuỗi không rỗng.")
        value = value.strip()
        if len(value) > 200:
            raise ValidationError(f"'{field}' không được vượt quá 200 ký tự.")
        cleaned[field] = value

    if cleaned["status"] not in definition["statuses"]:
        raise ValidationError(f"Trạng thái không hợp lệ cho {resource}.")

    for field in ("year", "mileage", "vehicle_id"):
        if field in payload:
            value = payload[field]
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValidationError(f"'{field}' phải là số nguyên.")
            cleaned[field] = value

    for field in ("cost", "distance_km"):
        if field in payload:
            value = payload[field]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValidationError(f"'{field}' phải là số không âm.")
            cleaned[field] = value

    if "year" in cleaned and not 1950 <= cleaned["year"] <= 2100:
        raise ValidationError("'year' phải nằm trong khoảng 1950–2100.")
    if "mileage" in cleaned and cleaned["mileage"] < 0:
        raise ValidationError("'mileage' không được âm.")

    for field in ("service_date", "departure_date", "arrival_date"):
        if field in payload:
            value = payload[field]
            if value is not None:
                if not isinstance(value, str):
                    raise ValidationError(f"'{field}' phải có định dạng YYYY-MM-DD.")
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    raise ValidationError(f"'{field}' phải có định dạng YYYY-MM-DD.")
                try:
                    date.fromisoformat(value)
                except ValueError as exc:
                    raise ValidationError(f"'{field}' phải có định dạng YYYY-MM-DD.") from exc
            cleaned[field] = value

    if (
        cleaned.get("arrival_date")
        and cleaned["arrival_date"] < cleaned["departure_date"]
    ):
        raise ValidationError("'arrival_date' không được trước 'departure_date'.")

    if "vehicle_id" in cleaned and cleaned["vehicle_id"] not in vehicle_ids:
        raise ValidationError("Không tìm thấy xe được chọn.")

    return cleaned


class FleetRequestHandler(BaseHTTPRequestHandler):
    database_path = DATABASE_PATH

    def track_request(self, handler):
        global METRIC_IN_PROGRESS

        started_at = time.perf_counter()
        self._metrics_status = 500
        with METRIC_LOCK:
            METRIC_IN_PROGRESS += 1
        try:
            handler()
        finally:
            elapsed = time.perf_counter() - started_at
            route = self.metric_route()
            labels = (self.command or "UNKNOWN", route, self._metrics_status)
            with METRIC_LOCK:
                METRIC_IN_PROGRESS -= 1
                METRIC_REQUESTS[labels] += 1
                METRIC_DURATION_SUM[labels] += elapsed
                METRIC_DURATION_COUNT[labels] += 1
                for index, bucket in enumerate(METRIC_DURATION_BUCKETS):
                    if elapsed <= bucket:
                        METRIC_DURATION_BUCKETS_COUNTS[labels][index] += 1

    def metric_route(self):
        path = urlparse(self.path).path
        if path in {"/", "/styles.css", "/app.js", "/health", "/metrics"}:
            return path
        if re.fullmatch(r"/api/(vehicles|trips|maintenance)", path):
            return path
        if re.fullmatch(r"/api/(vehicles|trips|maintenance)/\d+", path):
            return re.sub(r"/\d+$", "/{id}", path)
        return "other"

    def send_response(self, code, message=None):
        self._metrics_status = code
        super().send_response(code, message)

    def log_message(self, format_string, *args):
        logging.getLogger("fleet.access").info(
            "%s %s %s",
            self.log_date_time_string(),
            self.client_address[0],
            format_string % args,
        )

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_metrics(self, body):
        encoded_body = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded_body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded_body)

    @staticmethod
    def performance_metrics():
        with METRIC_LOCK:
            requests = dict(METRIC_REQUESTS)
            bucket_counts = {
                labels: counts.copy()
                for labels, counts in METRIC_DURATION_BUCKETS_COUNTS.items()
            }
            duration_sums = dict(METRIC_DURATION_SUM)
            duration_counts = dict(METRIC_DURATION_COUNT)
            in_progress = METRIC_IN_PROGRESS

        metrics = [
            "# HELP fleet_http_requests_total Total HTTP requests handled by the Fleet application.",
            "# TYPE fleet_http_requests_total counter",
        ]
        metrics.extend(
            f'fleet_http_requests_total{{method="{method}",route="{route}",status="{status}"}} {count}'
            for (method, route, status), count in sorted(requests.items())
        )
        metrics.extend(
            (
                "# HELP fleet_http_request_duration_seconds HTTP request duration in seconds.",
                "# TYPE fleet_http_request_duration_seconds histogram",
            )
        )
        for labels, counts in sorted(bucket_counts.items()):
            method, route, status = labels
            label_prefix = f'method="{method}",route="{route}",status="{status}"'
            for index, bucket in enumerate(METRIC_DURATION_BUCKETS):
                metrics.append(
                    f'fleet_http_request_duration_seconds_bucket{{{label_prefix},le="{bucket}"}} '
                    f"{counts[index]}"
                )
            metrics.extend(
                (
                    f'fleet_http_request_duration_seconds_bucket{{{label_prefix},le="+Inf"}} '
                    f"{duration_counts[labels]}",
                    f'fleet_http_request_duration_seconds_sum{{{label_prefix}}} '
                    f"{duration_sums[labels]:.9f}",
                    f'fleet_http_request_duration_seconds_count{{{label_prefix}}} '
                    f"{duration_counts[labels]}",
                )
            )

        metrics.extend(
            (
                "# HELP fleet_http_requests_in_progress Current HTTP requests being processed.",
                "# TYPE fleet_http_requests_in_progress gauge",
                f"fleet_http_requests_in_progress {max(0, in_progress - 1)}",
                "# HELP fleet_process_cpu_seconds_total Total CPU time used by the Fleet process.",
                "# TYPE fleet_process_cpu_seconds_total counter",
                f"fleet_process_cpu_seconds_total {time.process_time():.9f}",
                "# HELP fleet_process_start_time_seconds Start time of the Fleet process since the Unix epoch.",
                "# TYPE fleet_process_start_time_seconds gauge",
                f"fleet_process_start_time_seconds {time.time() - (time.monotonic() - PROCESS_START_TIME):.3f}",
                "# HELP fleet_process_uptime_seconds Uptime of the Fleet process in seconds.",
                "# TYPE fleet_process_uptime_seconds gauge",
                f"fleet_process_uptime_seconds {time.monotonic() - PROCESS_START_TIME:.3f}",
            )
        )
        try:
            with open("/proc/self/status", encoding="ascii") as process_status:
                for line in process_status:
                    if line.startswith("VmRSS:"):
                        resident_memory_kb = int(line.split()[1])
                        metrics.extend(
                            (
                                "# HELP fleet_process_resident_memory_bytes Resident memory size of the Fleet process in bytes.",
                                "# TYPE fleet_process_resident_memory_bytes gauge",
                                f"fleet_process_resident_memory_bytes {resident_memory_kb * 1024}",
                            )
                        )
                        break
        except OSError:
            pass
        return metrics

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValidationError("Content-Length không hợp lệ.") from exc
        if length < 1 or length > MAX_BODY_BYTES:
            raise ValidationError("Kích thước nội dung phải từ 1 đến 65536 byte.")
        try:
            return json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError("Nội dung phải là JSON hợp lệ.") from exc

    def do_GET(self):
        self.track_request(self.handle_get)

    def handle_get(self):
        path = urlparse(self.path).path
        if path == "/health":
            try:
                with database_connection(self.database_path) as connection:
                    connection.execute("SELECT 1")
                self.send_json(200, {"status": "ok"})
            except sqlite3.Error:
                self.send_json(503, {"error": "Cơ sở dữ liệu không khả dụng."})
            return

        if path == "/metrics":
            try:
                with database_connection(self.database_path) as connection:
                    metrics = self.performance_metrics()
                    for resource in ("vehicles", "trips", "maintenance"):
                        metrics.extend(
                            (
                                f"# HELP fleet_{resource}_total Total number of {resource}.",
                                f"# TYPE fleet_{resource}_total gauge",
                                f"fleet_{resource}_total "
                                f"{connection.execute(f'SELECT COUNT(*) FROM {resource}').fetchone()[0]}",
                            )
                        )
                        metrics.extend(
                            (
                                f"# HELP fleet_{resource}_by_status Number of {resource} by status.",
                                f"# TYPE fleet_{resource}_by_status gauge",
                            )
                        )
                        rows = connection.execute(
                            f"SELECT status, COUNT(*) AS count FROM {resource} GROUP BY status"
                        ).fetchall()
                        metrics.extend(
                            f'fleet_{resource}_by_status{{status="{row["status"]}"}} {row["count"]}'
                            for row in rows
                        )
                self.send_metrics("\n".join(metrics) + "\n")
            except sqlite3.Error:
                self.send_json(503, {"error": "Cơ sở dữ liệu không khả dụng."})
            return

        static_files = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/styles.css": ("styles.css", "text/css; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
        }
        if path in static_files:
            filename, content_type = static_files[path]
            try:
                body = (ROOT / filename).read_bytes()
            except OSError:
                self.send_error(500)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)
            return

        match = re.fullmatch(r"/api/(vehicles|trips|maintenance)(?:/(\d+))?", path)
        if not match:
            self.send_error(404)
            return

        resource, item_id = match.groups()
        with database_connection(self.database_path) as connection:
            if item_id:
                row = connection.execute(
                    f"SELECT * FROM {resource} WHERE id = ?", (int(item_id),)
                ).fetchone()
                if row is None:
                    self.send_json(404, {"error": "Không tìm thấy dữ liệu."})
                    return
                self.send_json(200, dict(row))
                return

            rows = connection.execute(
                f"""SELECT {resource}.*, vehicles.registration AS vehicle_registration
                    FROM {resource}
                    LEFT JOIN vehicles ON vehicles.id = {resource}.vehicle_id
                    ORDER BY {resource}.id DESC"""
            ).fetchall() if resource != "vehicles" else connection.execute(
                "SELECT * FROM vehicles ORDER BY id DESC"
            ).fetchall()
            self.send_json(200, [dict(row) for row in rows])

    def do_POST(self):
        self.track_request(self.handle_post)

    def handle_post(self):
        match = re.fullmatch(r"/api/(vehicles|trips|maintenance)", urlparse(self.path).path)
        if not match:
            self.send_error(404)
            return
        resource = match.group(1)
        try:
            payload = self.read_json()
            with database_connection(self.database_path) as connection:
                vehicle_ids = {
                    row[0] for row in connection.execute("SELECT id FROM vehicles")
                }
                cleaned = validate_payload(resource, payload, vehicle_ids)
                columns = list(cleaned)
                cursor = connection.execute(
                    f"INSERT INTO {resource} ({', '.join(columns)}) "
                    f"VALUES ({', '.join('?' for _ in columns)})",
                    [cleaned[column] for column in columns],
                )
                created = connection.execute(
                    f"SELECT * FROM {resource} WHERE id = ?", (cursor.lastrowid,)
                ).fetchone()
            self.send_json(201, dict(created))
        except ValidationError as exc:
            self.send_json(400, {"error": str(exc)})
        except sqlite3.IntegrityError as exc:
            message = "Biển số xe đã tồn tại." if resource == "vehicles" else "Dữ liệu liên quan không hợp lệ."
            self.send_json(409, {"error": message})

    def do_PUT(self):
        self.track_request(self.handle_put)

    def handle_put(self):
        match = re.fullmatch(r"/api/(vehicles|trips|maintenance)/(\d+)", urlparse(self.path).path)
        if not match:
            self.send_error(404)
            return
        resource, item_id = match.groups()
        try:
            payload = self.read_json()
            with database_connection(self.database_path) as connection:
                vehicle_ids = {
                    row[0] for row in connection.execute("SELECT id FROM vehicles")
                }
                cleaned = validate_payload(resource, payload, vehicle_ids)
                columns = list(cleaned)
                cursor = connection.execute(
                    f"UPDATE {resource} SET "
                    + ", ".join(f"{column} = ?" for column in columns)
                    + " WHERE id = ?",
                    [cleaned[column] for column in columns] + [int(item_id)],
                )
                if cursor.rowcount == 0:
                    self.send_json(404, {"error": "Không tìm thấy dữ liệu."})
                    return
                updated = connection.execute(
                    f"SELECT * FROM {resource} WHERE id = ?", (int(item_id),)
                ).fetchone()
            self.send_json(200, dict(updated))
        except ValidationError as exc:
            self.send_json(400, {"error": str(exc)})
        except sqlite3.IntegrityError:
            self.send_json(409, {"error": "Dữ liệu vi phạm ràng buộc."})

    def do_DELETE(self):
        self.track_request(self.handle_delete)

    def handle_delete(self):
        match = re.fullmatch(r"/api/(vehicles|trips|maintenance)/(\d+)", urlparse(self.path).path)
        if not match:
            self.send_error(404)
            return
        resource, item_id = match.groups()
        with database_connection(self.database_path) as connection:
            cursor = connection.execute(
                f"DELETE FROM {resource} WHERE id = ?", (int(item_id),)
            )
            if cursor.rowcount == 0:
                self.send_json(404, {"error": "Không tìm thấy dữ liệu."})
                return
        self.send_json(200, {"message": "Đã xóa dữ liệu."})


def main():
    initialize_database()
    log_handlers = [logging.StreamHandler()]
    log_path = os.environ.get("FLEET_LOG_PATH")
    if log_path:
        log_file = Path(log_path)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_handlers.append(
            RotatingFileHandler(
                log_file,
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
        )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        handlers=log_handlers,
        force=True,
    )
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer((host, port), FleetRequestHandler)
    access_host = "localhost" if host in {"0.0.0.0", "::"} else host
    print(f"Fleet Management đang chạy tại http://{access_host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Đang dừng dịch vụ Fleet Management.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
