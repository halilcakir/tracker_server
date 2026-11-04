import os
import sys
import json
import math
import time
import sqlite3
from datetime import datetime, date
from urllib.parse import urlparse, parse_qs
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

DB_PATH = os.path.join(os.path.dirname(__file__), "tracker.db")
WEB_DIR = os.path.join(os.path.dirname(__file__), "web")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            altitude REAL DEFAULT 0,
            speed REAL DEFAULT 0,
            heading REAL DEFAULT 0,
            accuracy REAL DEFAULT 0,
            battery INTEGER DEFAULT 0,
            is_charging INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_time REAL NOT NULL,
            end_time REAL NOT NULL,
            duration_seconds REAL NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            note TEXT DEFAULT ''
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_time ON telemetry(timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_stops_time ON stops(start_time)")
    conn.commit()
    conn.close()

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371000.0  # meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0)**2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

def update_stops_for_date(target_date_str=None):
    """Analyzes raw telemetry to detect parking / stop spots and durations."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if target_date_str:
        day_start = datetime.strptime(target_date_str, "%Y-%m-%d").timestamp()
        day_end = day_start + 86400
        cursor.execute("SELECT timestamp, latitude, longitude, speed FROM telemetry WHERE timestamp >= ? AND timestamp < ? ORDER BY timestamp ASC", (day_start, day_end))
    else:
        cursor.execute("SELECT timestamp, latitude, longitude, speed FROM telemetry ORDER BY timestamp ASC")
    
    rows = cursor.fetchall()
    if not rows:
        conn.close()
        return

    # Find clusters where vehicle remained within 45m with low speed for >= 3 minutes
    detected_stops = []
    current_cluster = []
    
    for row in rows:
        t, lat, lon, spd = row
        if not current_cluster:
            current_cluster.append(row)
            continue
        
        center_lat = sum(r[1] for r in current_cluster) / len(current_cluster)
        center_lon = sum(r[2] for r in current_cluster) / len(current_cluster)
        dist = haversine_distance(center_lat, center_lon, lat, lon)
        
        if dist < 45.0 and spd < 6.0:
            current_cluster.append(row)
        else:
            dur = current_cluster[-1][0] - current_cluster[0][0]
            if dur >= 180.0:  # >= 3 minutes
                s_t = current_cluster[0][0]
                e_t = current_cluster[-1][0]
                c_lat = sum(r[1] for r in current_cluster) / len(current_cluster)
                c_lon = sum(r[2] for r in current_cluster) / len(current_cluster)
                detected_stops.append((s_t, e_t, dur, c_lat, c_lon))
            current_cluster = [row]

    if current_cluster:
        dur = current_cluster[-1][0] - current_cluster[0][0]
        if dur >= 180.0:
            s_t = current_cluster[0][0]
            e_t = current_cluster[-1][0]
            c_lat = sum(r[1] for r in current_cluster) / len(current_cluster)
            c_lon = sum(r[2] for r in current_cluster) / len(current_cluster)
            detected_stops.append((s_t, e_t, dur, c_lat, c_lon))

    if target_date_str:
        cursor.execute("DELETE FROM stops WHERE start_time >= ? AND start_time < ?", (day_start, day_end))
    else:
        cursor.execute("DELETE FROM stops")

    for s_t, e_t, dur, c_lat, c_lon in detected_stops:
        cursor.execute("INSERT INTO stops (start_time, end_time, duration_seconds, latitude, longitude) VALUES (?, ?, ?, ?, ?)",
                       (s_t, e_t, dur, c_lat, c_lon))
    conn.commit()
    conn.close()

class TrackerHandler(BaseHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            self.serve_file(os.path.join(WEB_DIR, "dashboard.html"), "text/html; charset=utf-8")
        elif path == "/api/live":
            self.handle_live()
        elif path == "/api/history":
            self.handle_history(params)
        elif path == "/api/stops":
            self.handle_stops(params)
        elif path == "/api/stats":
            self.handle_stats(params)
        elif path == "/api/match_route":
            self.handle_match_route(params)
        elif path == "/api/dates":
            self.handle_dates()
        elif path == "/api/clear":
            self.handle_clear()
        elif path == "/api/report":
            self.handle_get_report(params)
        elif path == "/api/generate_demo":
            self.handle_generate_demo()
        else:
            safe_rel = path.lstrip("/")
            file_path = os.path.join(WEB_DIR, safe_rel)
            if os.path.exists(file_path) and os.path.isfile(file_path):
                mime = "text/plain"
                if file_path.endswith(".css"): mime = "text/css"
                elif file_path.endswith(".js"): mime = "application/javascript"
                elif file_path.endswith(".png"): mime = "image/png"
                elif file_path.endswith(".svg"): mime = "image/svg+xml"
                self.serve_file(file_path, mime)
            else:
                self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/telemetry" or path == "/api/report":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8", errors="ignore")
            try:
                data = json.loads(body) if body else {}
                self.save_telemetry(data)
                self.send_json({"status": "ok", "time": time.time()})
            except Exception as e:
                self.send_json({"status": "error", "message": str(e)}, status=400)
        elif path == "/api/generate_demo":
            self.handle_generate_demo()
        else:
            self.send_error(404, "Not Found")

    def handle_get_report(self, params):
        try:
            lat = float(params.get("lat", [0])[0])
            lon = float(params.get("lon", [0])[0])
            spd = float(params.get("spd", params.get("speed", [0]))[0])
            head = float(params.get("head", params.get("heading", [0]))[0])
            alt = float(params.get("alt", [0])[0])
            acc = float(params.get("acc", [0])[0])
            bat = int(params.get("bat", params.get("battery", [100]))[0])
            chg = int(params.get("chg", params.get("charging", [0]))[0])
            t = float(params.get("t", [time.time()])[0])

            data = {
                "latitude": lat, "longitude": lon, "speed": spd,
                "heading": head, "altitude": alt, "accuracy": acc,
                "battery": bat, "is_charging": chg, "timestamp": t
            }
            self.save_telemetry(data)
            self.send_json({"status": "ok", "ack": time.time()})
        except Exception as e:
            self.send_json({"status": "error", "message": str(e)}, status=400)

    def save_telemetry(self, data):
        t = data.get("timestamp") or time.time()
        lat = float(data.get("latitude", 0))
        lon = float(data.get("longitude", 0))
        alt = float(data.get("altitude", 0))
        spd = float(data.get("speed", 0))
        heading = float(data.get("heading", 0))
        acc = float(data.get("accuracy", 0))
        bat = int(data.get("battery", 100))
        chg = 1 if data.get("is_charging") else 0

        if abs(lat) < 0.0001 and abs(lon) < 0.0001:
            return

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO telemetry (timestamp, latitude, longitude, altitude, speed, heading, accuracy, battery, is_charging)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (t, lat, lon, alt, spd, heading, acc, bat, chg))
        conn.commit()
        conn.close()

    def handle_live(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM telemetry ORDER BY timestamp DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()

        if not row:
            self.send_json({"online": False, "data": None})
            return

        now = time.time()
        diff = now - row["timestamp"]
        is_online = diff < 180.0

        item = dict(row)
        item["last_seen_seconds_ago"] = round(diff, 1)
        item["online"] = is_online
        item["datetime"] = datetime.fromtimestamp(row["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")

        self.send_json({"online": is_online, "data": item})

    def handle_history(self, params):
        date_str = params.get("date", [None])[0]
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if date_str:
            try:
                day_start = datetime.strptime(date_str, "%Y-%m-%d").timestamp()
                day_end = day_start + 86400
                cursor.execute("SELECT * FROM telemetry WHERE timestamp >= ? AND timestamp < ? ORDER BY timestamp ASC", (day_start, day_end))
            except ValueError:
                cursor.execute("SELECT * FROM telemetry ORDER BY timestamp ASC")
        else:
            day_start = time.time() - 86400
            cursor.execute("SELECT * FROM telemetry WHERE timestamp >= ? ORDER BY timestamp ASC", (day_start,))

        rows = cursor.fetchall()
        conn.close()

        points = []
        for r in rows:
            d = dict(r)
            d["datetime"] = datetime.fromtimestamp(r["timestamp"]).strftime("%H:%M:%S")
            points.append(d)

        self.send_json({"count": len(points), "points": points})

    def handle_match_route(self, params):
        import urllib.request
        import urllib.error

        date_str = params.get("date", [None])[0]
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if date_str:
            try:
                day_start = datetime.strptime(date_str, "%Y-%m-%d").timestamp()
                day_end = day_start + 86400
                cursor.execute("SELECT latitude, longitude, speed FROM telemetry WHERE timestamp >= ? AND timestamp < ? ORDER BY timestamp ASC", (day_start, day_end))
            except ValueError:
                cursor.execute("SELECT latitude, longitude, speed FROM telemetry ORDER BY timestamp ASC")
        else:
            day_start = time.time() - 86400
            cursor.execute("SELECT latitude, longitude, speed FROM telemetry WHERE timestamp >= ? ORDER BY timestamp ASC", (day_start,))

        rows = cursor.fetchall()
        conn.close()

        if len(rows) < 2:
            self.send_json({"snapped": False, "coordinates": [[r["latitude"], r["longitude"]] for r in rows]})
            return

        # Deduplicate consecutive stationary points (distance < 5m)
        filtered_coords = []
        for r in rows:
            lat, lon = r["latitude"], r["longitude"]
            if not filtered_coords:
                filtered_coords.append([lon, lat])
                continue
            prev_lon, prev_lat = filtered_coords[-1]
            if haversine_distance(prev_lat, prev_lon, lat, lon) > 4.0:
                filtered_coords.append([lon, lat])

        if len(filtered_coords) < 2:
            self.send_json({"snapped": False, "coordinates": [[c[1], c[0]] for c in filtered_coords]})
            return

        # Snap to roads using OSRM in chunks of up to 40 coordinates
        snapped_coords = []
        CHUNK_SIZE = 40
        for i in range(0, len(filtered_coords), CHUNK_SIZE - 1):
            chunk = filtered_coords[i:i + CHUNK_SIZE]
            if len(chunk) < 2:
                for c in chunk:
                    snapped_coords.append([c[1], c[0]])
                continue

            coord_str = ";".join(f"{c[0]:.6f},{c[1]:.6f}" for c in chunk)
            radiuses = ";".join(["45"] * len(chunk))
            url = f"https://router.project-osrm.org/match/v1/driving/{coord_str}?overview=full&geometries=geojson&radiuses={radiuses}"

            matched_this_chunk = False
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'GM-Buddy-Tracker/1.0'})
                with urllib.request.urlopen(req, timeout=4) as resp:
                    res_data = json.loads(resp.read().decode('utf-8'))
                    if res_data.get("code") == "Ok" and res_data.get("matchings"):
                        for m in res_data["matchings"]:
                            geom = m.get("geometry", {}).get("coordinates", [])
                            for pt in geom:
                                snapped_coords.append([pt[1], pt[0]])
                        matched_this_chunk = True
            except Exception:
                pass

            if not matched_this_chunk:
                for c in chunk:
                    snapped_coords.append([c[1], c[0]])

        # Deduplicate adjacent snapped coords
        final_coords = []
        for c in snapped_coords:
            if not final_coords or (abs(final_coords[-1][0] - c[0]) > 0.00001 or abs(final_coords[-1][1] - c[1]) > 0.00001):
                final_coords.append(c)

        self.send_json({"snapped": True, "coordinates": final_coords})

    def handle_stops(self, params):
        date_str = params.get("date", [None])[0]
        update_stops_for_date(date_str)

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if date_str:
            day_start = datetime.strptime(date_str, "%Y-%m-%d").timestamp()
            day_end = day_start + 86400
            cursor.execute("SELECT * FROM stops WHERE start_time >= ? AND start_time < ? ORDER BY start_time ASC", (day_start, day_end))
        else:
            cursor.execute("SELECT * FROM stops ORDER BY start_time ASC")

        rows = cursor.fetchall()
        conn.close()

        stops_list = []
        for r in rows:
            d = dict(r)
            dur = d["duration_seconds"]
            hours = int(dur // 3600)
            mins = int((dur % 3600) // 60)
            if hours > 0:
                d["duration_text"] = f"{hours} sa {mins} dk"
            else:
                d["duration_text"] = f"{mins} dk"
            
            d["start_time_str"] = datetime.fromtimestamp(d["start_time"]).strftime("%H:%M")
            d["end_time_str"] = datetime.fromtimestamp(d["end_time"]).strftime("%H:%M")
            stops_list.append(d)

        self.send_json({"stops": stops_list})

    def handle_stats(self, params):
        date_str = params.get("date", [None])[0]
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if date_str:
            day_start = datetime.strptime(date_str, "%Y-%m-%d").timestamp()
            day_end = day_start + 86400
            cursor.execute("SELECT * FROM telemetry WHERE timestamp >= ? AND timestamp < ? ORDER BY timestamp ASC", (day_start, day_end))
        else:
            day_start = time.time() - 86400
            cursor.execute("SELECT * FROM telemetry WHERE timestamp >= ? ORDER BY timestamp ASC", (day_start,))

        rows = cursor.fetchall()
        conn.close()

        if not rows:
            self.send_json({
                "total_distance_km": 0.0,
                "max_speed_kmh": 0.0,
                "avg_speed_kmh": 0.0,
                "total_points": 0,
                "battery_start": 0,
                "battery_current": 0
            })
            return

        total_dist_m = 0.0
        max_speed = 0.0
        speed_sum = 0.0
        speed_count = 0

        for i in range(1, len(rows)):
            p1 = rows[i - 1]
            p2 = rows[i]
            d = haversine_distance(p1["latitude"], p1["longitude"], p2["latitude"], p2["longitude"])
            if d < 5000:
                total_dist_m += d
            if p2["speed"] > max_speed:
                max_speed = p2["speed"]
            if p2["speed"] > 3.0:
                speed_sum += p2["speed"]
                speed_count += 1

        avg_speed = (speed_sum / speed_count) if speed_count > 0 else 0.0

        self.send_json({
            "total_distance_km": round(total_dist_m / 1000.0, 2),
            "max_speed_kmh": round(max_speed, 1),
            "avg_speed_kmh": round(avg_speed, 1),
            "total_points": len(rows),
            "battery_start": rows[0]["battery"],
            "battery_current": rows[-1]["battery"]
        })

    def handle_generate_demo(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM telemetry")
        cursor.execute("DELETE FROM stops")

        now = time.time()
        start_time = now - 28800  # 8 hours ago

        route_segments = [
            {"lat": 40.9902, "lon": 29.0298, "duration": 7200, "speed": 0, "bat": 100, "chg": 0},
            {"lat_start": 40.9902, "lon_start": 29.0298, "lat_end": 41.0772, "lon_end": 29.0125, "duration": 2400, "speed_avg": 55, "bat_start": 98, "bat_end": 92, "chg": 1},
            {"lat": 41.0772, "lon": 29.0125, "duration": 14400, "speed": 0, "bat": 90, "chg": 0},
            {"lat_start": 41.0772, "lon_start": 29.0125, "lat_end": 41.0428, "lon_end": 29.0075, "duration": 1200, "speed_avg": 40, "bat_start": 88, "bat_end": 84, "chg": 1},
            {"lat": 41.0428, "lon": 29.0075, "duration": 2700, "speed": 0, "bat": 82, "chg": 0},
            {"lat_start": 41.0428, "lon_start": 29.0075, "lat_end": 40.9902, "lon_end": 29.0298, "duration": 1800, "speed_avg": 50, "bat_start": 81, "bat_end": 77, "chg": 1},
            {"lat": 40.9902, "lon": 29.0298, "duration": 900, "speed": 0, "bat": 76, "chg": 0}
        ]

        curr_t = start_time
        records = []

        for seg in route_segments:
            if "lat_start" in seg:
                steps = max(10, int(seg["duration"] / 30))
                time_step = seg["duration"] / steps
                for s in range(steps):
                    frac = s / float(steps)
                    lat = seg["lat_start"] + (seg["lat_end"] - seg["lat_start"]) * frac + (math.sin(s * 0.5) * 0.0003)
                    lon = seg["lon_start"] + (seg["lon_end"] - seg["lon_start"]) * frac + (math.cos(s * 0.4) * 0.0003)
                    spd = seg["speed_avg"] + math.sin(s * 0.8) * 12.0
                    heading = (math.degrees(math.atan2(seg["lon_end"] - seg["lon_start"], seg["lat_end"] - seg["lat_start"])) + 360) % 360
                    bat = int(seg["bat_start"] + (seg["bat_end"] - seg["bat_start"]) * frac)
                    records.append((curr_t, lat, lon, 45.0, max(0.0, spd), heading, 8.0, bat, seg["chg"]))
                    curr_t += time_step
            else:
                steps = max(4, int(seg["duration"] / 180))
                time_step = seg["duration"] / steps
                for s in range(steps):
                    lat = seg["lat"] + (math.sin(s) * 0.00003)
                    lon = seg["lon"] + (math.cos(s) * 0.00003)
                    records.append((curr_t, lat, lon, 30.0, 0.0, 0.0, 5.0, seg["bat"], seg["chg"]))
                    curr_t += time_step

        cursor.executemany("""
            INSERT INTO telemetry (timestamp, latitude, longitude, altitude, speed, heading, accuracy, battery, is_charging)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, records)
        conn.commit()
        conn.close()

        update_stops_for_date()
        self.send_json({"status": "ok", "generated_points": len(records)})

    def handle_dates(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT strftime('%Y-%m-%d', datetime(timestamp, 'unixepoch', 'localtime')) as day
            FROM telemetry
            ORDER BY day DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        days = [r[0] for r in rows if r[0]]
        self.send_json({"dates": days})

    def handle_clear(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM telemetry")
        cursor.execute("DELETE FROM stops")
        conn.commit()
        conn.close()
        self.send_json({"status": "ok", "message": "Tum veriler temizlendi"})

    def serve_file(self, file_path, mime_type):
        try:
            with open(file_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, str(e))

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

def run_server(port=8080):
    init_db()
    os.makedirs(WEB_DIR, exist_ok=True)
    server_address = ("0.0.0.0", port)
    httpd = ThreadingHTTPServer(server_address, TrackerHandler)
    print(f"\n=======================================================")
    print(f"🚀 GM Buddy Araç Takip Sunucusu Başlatıldı!")
    print(f"📍 Web Dashboard: http://localhost:{port}")
    print(f"📡 Cihaz Bildirim Endpoint'i: http://<SUNUCU_IP>:{port}/api/report")
    print(f"=======================================================\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nSunucu kapatılıyor...")
        httpd.server_close()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    run_server(port)
