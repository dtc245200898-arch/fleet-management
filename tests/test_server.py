import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.server import FleetRequestHandler, initialize_database


class FleetApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_directory = tempfile.TemporaryDirectory()
        cls.database_path = Path(cls.temp_directory.name) / "fleet-test.db"
        initialize_database(cls.database_path)
        handler = type(
            "TestFleetRequestHandler",
            (FleetRequestHandler,),
            {"database_path": cls.database_path},
        )
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=5)
        cls.temp_directory.cleanup()

    def request_json(self, path, method="GET", payload=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def test_health_and_seeded_vehicles(self):
        status, health = self.request_json("/health")
        self.assertEqual(status, 200)
        self.assertEqual(health, {"status": "ok"})
        status, vehicles = self.request_json("/api/vehicles")
        self.assertEqual(status, 200)
        self.assertEqual(len(vehicles), 3)
        with urlopen(f"{self.base_url}/metrics", timeout=3) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("text/plain", response.headers["Content-Type"])
            metrics = response.read().decode("utf-8")
            self.assertIn("fleet_vehicles_total 3", metrics)
            self.assertIn('fleet_vehicles_by_status{status="Hoạt động"} 2', metrics)
        with urlopen(f"{self.base_url}/", timeout=3) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("text/html", response.headers["Content-Type"])
            self.assertIn(b"FleetOps", response.read())

    def test_metrics_include_http_performance(self):
        self.request_json("/health")
        with urlopen(f"{self.base_url}/metrics", timeout=3) as response:
            metrics = response.read().decode("utf-8")

        self.assertIn("# TYPE fleet_http_requests_total counter", metrics)
        self.assertRegex(
            metrics,
            r'fleet_http_requests_total\{method="GET",route="/health",status="200"\} [1-9]\d*',
        )
        self.assertIn(
            'fleet_http_request_duration_seconds_bucket{method="GET",route="/health",status="200",le="+Inf"}',
            metrics,
        )
        self.assertIn("fleet_http_requests_in_progress", metrics)
        self.assertIn("fleet_process_cpu_seconds_total", metrics)
        self.assertIn("fleet_process_uptime_seconds", metrics)

    def test_vehicle_create_update_and_delete(self):
        vehicle = {
            "registration": "30A-999.99",
            "make": "Honda",
            "model": "CR-V",
            "year": 2024,
            "mileage": 500,
            "status": "Hoạt động",
        }
        status, created = self.request_json("/api/vehicles", "POST", vehicle)
        self.assertEqual(status, 201)
        self.assertEqual(created["registration"], vehicle["registration"])

        vehicle["mileage"] = 900
        status, updated = self.request_json(f"/api/vehicles/{created['id']}", "PUT", vehicle)
        self.assertEqual(status, 200)
        self.assertEqual(updated["mileage"], 900)

        status, deleted = self.request_json(f"/api/vehicles/{created['id']}", "DELETE")
        self.assertEqual(status, 200)
        self.assertEqual(deleted["message"], "Đã xóa dữ liệu.")

    def test_invalid_payload_and_duplicate_registration(self):
        invalid = {
            "registration": "31A-111.11",
            "make": "Ford",
            "model": "Ranger",
            "year": 2024,
            "mileage": -1,
            "status": "Hoạt động",
        }
        status, result = self.request_json("/api/vehicles", "POST", invalid)
        self.assertEqual(status, 400)
        self.assertIn("mileage", result["error"])

        duplicate = {
            "registration": "51A-123.45",
            "make": "Toyota",
            "model": "Camry",
            "year": 2022,
            "mileage": 0,
            "status": "Hoạt động",
        }
        status, result = self.request_json("/api/vehicles", "POST", duplicate)
        self.assertEqual(status, 409)
        self.assertIn("Biển số", result["error"])

    def test_trip_rejects_invalid_dates_and_non_finite_distance(self):
        _, vehicles = self.request_json("/api/vehicles")
        trip = {
            "vehicle_id": vehicles[0]["id"],
            "driver": "Nguyễn Văn C",
            "origin": "Hà Nội",
            "destination": "Nam Định",
            "departure_date": "2026-10-24",
            "arrival_date": "2026-10-23",
            "distance_km": 50,
            "status": "Đã lên lịch",
        }
        status, result = self.request_json("/api/trips", "POST", trip)
        self.assertEqual(status, 400)
        self.assertIn("arrival_date", result["error"])

        trip["arrival_date"] = None
        trip["distance_km"] = float("inf")
        status, result = self.request_json("/api/trips", "POST", trip)
        self.assertEqual(status, 400)
        self.assertIn("distance_km", result["error"])

    def test_trip_and_maintenance_relations(self):
        _, vehicles = self.request_json("/api/vehicles")
        vehicle_id = vehicles[0]["id"]
        trip = {
            "vehicle_id": vehicle_id,
            "driver": "Nguyễn Văn A",
            "origin": "Hà Nội",
            "destination": "Hải Phòng",
            "departure_date": "2026-10-24",
            "arrival_date": None,
            "distance_km": 120,
            "status": "Đang thực hiện",
        }
        status, created_trip = self.request_json("/api/trips", "POST", trip)
        self.assertEqual(status, 201)
        status, trips = self.request_json("/api/trips")
        self.assertEqual(status, 200)
        self.assertEqual(trips[0]["vehicle_registration"], vehicles[0]["registration"])

        maintenance = {
            "vehicle_id": vehicle_id,
            "service_date": "2026-10-25",
            "service_type": "Thay dầu",
            "cost": 850000,
            "description": "Bảo dưỡng định kỳ",
            "status": "Đã lên lịch",
        }
        status, created_maintenance = self.request_json("/api/maintenance", "POST", maintenance)
        self.assertEqual(status, 201)
        status, entries = self.request_json("/api/maintenance")
        self.assertEqual(status, 200)
        self.assertEqual(entries[0]["vehicle_registration"], vehicles[0]["registration"])

        status, _ = self.request_json(f"/api/trips/{created_trip['id']}", "DELETE")
        self.assertEqual(status, 200)
        status, _ = self.request_json(f"/api/maintenance/{created_maintenance['id']}", "DELETE")
        self.assertEqual(status, 200)

    def test_vehicle_delete_cascades_linked_records(self):
        _, vehicles = self.request_json("/api/vehicles")
        vehicle_id = vehicles[0]["id"]
        trip = {
            "vehicle_id": vehicle_id,
            "driver": "Nguyễn Văn B",
            "origin": "Đà Nẵng",
            "destination": "Huế",
            "departure_date": "2026-10-24",
            "distance_km": 95,
            "status": "Đã lên lịch",
        }
        maintenance = {
            "vehicle_id": vehicle_id,
            "service_date": "2026-10-25",
            "service_type": "Kiểm tra lốp",
            "cost": 200000,
            "description": "Kiểm tra định kỳ",
            "status": "Đã lên lịch",
        }
        self.assertEqual(self.request_json("/api/trips", "POST", trip)[0], 201)
        self.assertEqual(self.request_json("/api/maintenance", "POST", maintenance)[0], 201)

        self.assertEqual(self.request_json(f"/api/vehicles/{vehicle_id}", "DELETE")[0], 200)
        self.assertEqual(self.request_json("/api/trips")[1], [])
        self.assertEqual(self.request_json("/api/maintenance")[1], [])


if __name__ == "__main__":
    unittest.main()
