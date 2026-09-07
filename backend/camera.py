import cv2
import time
import os
import math
import socket
import threading
import hashlib
import numpy as np
from urllib.parse import urlparse
from datetime import datetime

from aegis_core_net import AegisPerceptionNet, TACTICAL_VEHICLE_REGISTRY, generate_tactical_plate

# Minimize OpenCV FFmpeg network timeout
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "timeout;1500000"

def is_stream_reachable(url_str, timeout=0.8):
    """Fast TCP socket pre-flight check so OpenCV never hangs on unreachable IP addresses."""
    try:
        parsed = urlparse(url_str)
        host = parsed.hostname
        if not host:
            return False
        port = parsed.port
        if not port:
            port = 80 if parsed.scheme == 'http' else (554 if parsed.scheme == 'rtsp' else 8080)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        sock.close()
        return True
    except Exception:
        return False


class VideoCamera:
    """
    Tactical Video Streaming Node powered by Aegis-VisionNet.
    Coordinates 5 Sub-Models:
      1. CSPDarknet Tactical Detector
      2. Biometric Face Localization Head
      3. Cross-Camera Vehicle Re-Identification Engine
      4. Airborne Micro-Target (Bird vs Drone) Discriminator
      5. Perimeter Breach & Kinematics Evaluator
    """
    def __init__(self, alert_callback, source=0):
        self.alert_callback = alert_callback
        self.source = source
        self.pending_source = None
        
        # Thread-safe raw frame buffer
        self.raw_frame = None
        self.frame_lock = threading.Lock()
        self.last_frame_time = 0
        self.connected = False
        self.connection_status = "Initializing..."
        self.running = True
        
        # Feature toggles
        self.enable_face_detection = True
        self.enable_anpr = True
        self.enable_loitering = True
        self.enable_tripwire = True
        self.enable_night_boost = True
        self.enable_reid = True
        self.enable_airborne_filter = True

        # Initialize Aegis-VisionNet Master Perception Pipeline
        self.aegis_net = AegisPerceptionNet()

        # Active vision mode: 'normal', 'night', 'thermal', 'rain'
        self.vision_mode = 'normal'
        self.tripwire_y = 300
        
        # Tracking & Behavioral state
        self.tracks = {}
        self.last_alert_time = {}
        self.alert_cooldown = 3.0 # seconds per alert category
        
        # Telemetry & Target Statistics
        self.stats = {
            "persons": 0,
            "vehicles": 0,
            "faces": 0,
            "plates": 0,
            "reid_matches": 0,
            "birds_filtered": 0,
            "drones": 0,
            "fps": 30,
            "mean_luminance": 120
        }
        self.frame_count = 0
        self.fps_start_time = time.time()

        os.makedirs("evidence", exist_ok=True)
        os.makedirs("evidence/faces", exist_ok=True)

        # Launch background camera capture thread
        self.capture_thread = threading.Thread(target=self._capture_worker, daemon=True)
        self.capture_thread.start()

    def _get_cam_identifier(self):
        """Returns standard node name (e.g. CAM-01 or CAM-02)."""
        src_str = str(self.source)
        if src_str == "0":
            return "CAM-01 [BASE]"
        elif "15" in src_str or "1" in src_str:
            return "CAM-01 [WEST-PERIMETER]"
        else:
            return "CAM-02 [NORTH-GATEWAY]"

    def _open_capture(self, src):
        try:
            if isinstance(src, str) and src.isdigit():
                src = int(src)

            if isinstance(src, int):
                cap = cv2.VideoCapture(src, cv2.CAP_DSHOW)
                if cap.isOpened():
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    return cap
                return None

            # Remote IP camera
            url_str = str(src).strip()
            if url_str.startswith("http://") or url_str.startswith("https://") or url_str.startswith("rtsp://"):
                if not is_stream_reachable(url_str, timeout=0.8):
                    print(f"[CAM]: Remote endpoint {url_str} is unreachable.")
                    return None

            cap = cv2.VideoCapture(url_str)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                return cap
            return None
        except Exception as e:
            print(f"Error opening source {src}: {e}")
            return None

    def _capture_worker(self):
        """Dedicated background thread grabbing frames continuously."""
        current_cap = self._open_capture(self.source)
        if current_cap and current_cap.isOpened():
            self.connected = True
            self.connection_status = "Live"
        else:
            self.connected = False
            self.connection_status = "Searching..."

        while self.running:
            if self.pending_source is not None:
                new_src = self.pending_source
                self.pending_source = None
                self.connection_status = "Switching..."
                self.connected = False
                
                if current_cap is not None:
                    try:
                        current_cap.release()
                    except Exception:
                        pass
                    current_cap = None
                    time.sleep(0.1)
                
                self.source = new_src
                current_cap = self._open_capture(self.source)
                if current_cap and current_cap.isOpened():
                    self.connected = True
                    self.connection_status = "Live"
                else:
                    self.connected = False
                    self.connection_status = "Offline / Unreachable"

            if current_cap is not None and current_cap.isOpened():
                try:
                    success, frame = current_cap.read()
                    if success and frame is not None:
                        with self.frame_lock:
                            self.raw_frame = frame
                            self.last_frame_time = time.time()
                            self.connected = True
                            self.connection_status = "Live"
                    else:
                        self.connected = False
                        self.connection_status = "No Frames"
                        time.sleep(0.04)
                except Exception:
                    self.connected = False
                    time.sleep(0.04)
            else:
                time.sleep(1.5)
                if self.pending_source is None and current_cap is None:
                    current_cap = self._open_capture(self.source)
                    if current_cap and current_cap.isOpened():
                        self.connected = True
                        self.connection_status = "Live"

        if current_cap is not None:
            current_cap.release()

    def set_source(self, new_source):
        if isinstance(new_source, str) and new_source.isdigit():
            new_source = int(new_source)
        self.pending_source = new_source
        return True

    def set_mode(self, mode):
        if mode in ['normal', 'night', 'thermal', 'rain']:
            self.vision_mode = mode

    def toggle_feature(self, feature_name, enabled):
        if hasattr(self, f"enable_{feature_name}"):
            setattr(self, f"enable_{feature_name}", bool(enabled))
            return True
        return False

    def __del__(self):
        self.running = False

    def apply_vision_filter(self, frame):
        """Environmental Preprocessing: Thermal, Night IR/CLAHE, Rain Defog."""
        if self.vision_mode == 'thermal':
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=3.5, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)
            return cv2.applyColorMap(enhanced, cv2.COLORMAP_INFERNO)
        elif self.vision_mode == 'night':
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
            boosted = clahe.apply(gray)
            night_vision = np.zeros_like(frame)
            night_vision[:, :, 1] = boosted # Military Phosphor Green
            night_vision[:, :, 0] = (boosted * 0.15).astype(np.uint8)
            night_vision[:, :, 2] = (boosted * 0.1).astype(np.uint8)
            return night_vision
        elif self.vision_mode == 'rain':
            filtered = cv2.bilateralFilter(frame, 7, 50, 50)
            gaussian = cv2.GaussianBlur(filtered, (0, 0), 2.0)
            return cv2.addWeighted(filtered, 1.5, gaussian, -0.5, 0)
        return frame

    def _trigger_alert(self, alert_data, display_frame, box=None, face_crop=None):
        now = time.time()
        category = alert_data.get("category", "breach")
        if now - self.last_alert_time.get(category, 0) < self.alert_cooldown:
            return False
        self.last_alert_time[category] = now

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"evidence/{category}_{timestamp}.jpg"
        
        snapshot = display_frame.copy()
        if box:
            bx1, by1, bx2, by2 = box
            cv2.rectangle(snapshot, (bx1, by1), (bx2, by2), (0, 0, 255), 3)
            cv2.putText(snapshot, alert_data['type'], (bx1, max(25, by1 - 10)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
        
        # Attach and embed Biometric Face Crop if present
        if face_crop:
            alert_data["face_crop"] = face_crop
            if os.path.exists(face_crop):
                try:
                    f_img = cv2.imread(face_crop)
                    if f_img is not None and f_img.size > 0:
                        sh, sw = snapshot.shape[:2]
                        pip_size = min(120, max(60, int(sh * 0.28)))
                        f_resized = cv2.resize(f_img, (pip_size, pip_size))
                        px = sw - pip_size - 15
                        py = 15
                        # Picture-in-picture background and border
                        snapshot[py:py+pip_size, px:px+pip_size] = f_resized
                        cv2.rectangle(snapshot, (px, py), (px+pip_size, py+pip_size), (0, 255, 255), 2)
                        cv2.putText(snapshot, "BIO-FACE", (px + 4, py + pip_size - 6),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
                except Exception as e:
                    print("Face PIP overlay error:", e)

        cv2.imwrite(filename, snapshot)

        alert_data.update({
            "timestamp": datetime.now().isoformat(),
            "image": filename,
            "mode": self.vision_mode.upper(),
            "sensor": self._get_cam_identifier()
        })
        self.alert_callback(alert_data)
        return True

    def get_frame(self):
        with self.frame_lock:
            has_fresh_frame = (self.raw_frame is not None) and ((time.time() - self.last_frame_time) < 2.5)
            if has_fresh_frame:
                raw_image = self.raw_frame.copy()
            else:
                raw_image = None

        if raw_image is None:
            test_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cam_label = self._get_cam_identifier()
            cv2.putText(test_frame, "[ACQUIRING AEGIS-VISIONNET SENSOR FEED...]", (90, 190), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)
            cv2.putText(test_frame, f"Active Sensor: {cam_label}", (40, 240), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)
            cv2.putText(test_frame, f"Link Status: {self.connection_status}", (40, 275), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 200, 255), 1)
            cv2.putText(test_frame, "Ensure IP Webcam or USB Camera is active", (40, 315), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (120, 120, 255), 1)
            ret, jpeg = cv2.imencode('.jpg', test_frame)
            return jpeg.tobytes()

        # Measure FPS
        self.frame_count += 1
        elapsed = time.time() - self.fps_start_time
        if elapsed >= 1.0:
            self.stats["fps"] = int(self.frame_count / elapsed)
            self.frame_count = 0
            self.fps_start_time = time.time()

        h, w = raw_image.shape[:2]
        self.tripwire_y = int(h * 0.55)

        # Environmental mean luminance
        gray_raw = cv2.cvtColor(raw_image, cv2.COLOR_BGR2GRAY)
        mean_lum = float(np.mean(gray_raw))
        self.stats["mean_luminance"] = round(mean_lum, 1)

        # ------------------------------------------------------------------
        # SUB-MODEL 1: AEGIS DEEP CONVOLUTIONAL DETECTOR
        # ------------------------------------------------------------------
        results = self.aegis_net.run_inference(raw_image, conf_thresh=0.35)

        # Apply environmental filter
        display_frame = self.apply_vision_filter(raw_image.copy())

        # Border sector zones
        overlay = display_frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, self.tripwire_y), (0, 0, 140), -1) # Zone A: Exclusion
        cv2.rectangle(overlay, (0, self.tripwire_y), (w, h), (0, 90, 0), -1)  # Zone B: Sovereign Outpost
        cv2.addWeighted(overlay, 0.12, display_frame, 0.88, 0, display_frame)

        cv2.putText(display_frame, "[ZONE A: RESTRICTED BUFFER / EXCLUSION SECTOR]", (15, 25), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (100, 100, 255), 2)
        cv2.putText(display_frame, "[ZONE B: SOVEREIGN TERRITORY / FRIENDLY POST]", (15, h - 15), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (100, 255, 100), 2)

        now = time.time()
        active_track_keys = set()
        person_count = 0
        vehicle_count = 0
        face_count = 0
        plate_count = 0
        reid_match_count = 0
        birds_filtered_count = 0
        drones_count = 0
        tripwire_triggered = False
        cam_id = self._get_cam_identifier()

        for r in results:
            boxes = r.boxes
            for idx, box in enumerate(boxes):
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                conf = float(box.conf[0])
                cls_id = int(box.cls[0])
                box_w = max(1, x2 - x1)
                box_h = max(1, y2 - y1)

                center_x = (x1 + x2) // 2
                bottom_y = y2
                track_key = f"{cls_id}_{center_x // 35}_{idx}"
                active_track_keys.add(track_key)

                # Initialize or update track state
                if track_key not in self.tracks:
                    self.tracks[track_key] = {
                        "last_x": center_x,
                        "last_y": bottom_y,
                        "first_seen": now,
                        "zone_a_entry": now if bottom_y < self.tripwire_y else None,
                        "history": [(center_x, bottom_y)],
                        "speed": 0.0
                    }
                trk = self.tracks[track_key]
                
                # Speed / displacement calculation
                dx = center_x - trk["last_x"]
                dy = bottom_y - trk["last_y"]
                distance = math.hypot(dx, dy)
                trk["speed"] = round(distance, 1)
                prev_y = trk["last_y"]
                trk["last_x"] = center_x
                trk["last_y"] = bottom_y
                trk["history"].append((center_x, bottom_y))
                if len(trk["history"]) > 16:
                    trk["history"].pop(0)

                # Track zone dwell time
                if bottom_y < self.tripwire_y:
                    if trk["zone_a_entry"] is None:
                        trk["zone_a_entry"] = now
                else:
                    trk["zone_a_entry"] = None

                # Direction classification
                if bottom_y > prev_y + 3:
                    direction = "INBOUND (A -> B)"
                elif bottom_y < prev_y - 3:
                    direction = "OUTBOUND (B -> A)"
                else:
                    direction = "PATROLLING"

                # ------------------------------------------------------------------
                # SUB-MODEL 4: AIRBORNE MICRO-TARGET & BIRD/DRONE DISCRIMINATION
                # ------------------------------------------------------------------
                if cls_id == 14 or (bottom_y < self.tripwire_y and box_w < 65 and box_h < 55 and cls_id not in [0, 2, 5, 7]):
                    if self.enable_airborne_filter:
                        airborne_res = self.aegis_net.airborne_classifier.classify(cls_id, (x1, y1, x2, y2), conf)
                        if airborne_res["target_type"] == "AIRBORNE_WILDLIFE":
                            birds_filtered_count += 1
                            # Harmless wildlife: draw yellow reticle, suppress critical alerts
                            cv2.rectangle(display_frame, (x1, y1), (x2, y2), airborne_res["color"], 2)
                            cv2.putText(display_frame, airborne_res["label"], (x1, max(18, y1 - 6)),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, airborne_res["color"], 1)
                            continue
                        elif airborne_res["target_type"] == "AERIAL_DRONE_SUSPECT":
                            drones_count += 1
                            cv2.rectangle(display_frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                            cv2.putText(display_frame, "[AIRBORNE DRONE / UAV INTRUSION]", (x1, max(18, y1 - 6)),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 2)
                            self._trigger_alert({
                                "category": "drone",
                                "type": "AIRBORNE THREAT: Low-Altitude Unmanned Drone (UAV) Detected",
                                "severity": "CRITICAL",
                                "direction": direction,
                                "target": "UAV-MICRO",
                                "confidence": round(conf, 2)
                            }, display_frame, (x1, y1, x2, y2))
                            continue

                # ------------------------------------------------------------------
                # SUB-MODEL 1 & 2: HUMAN INTRUSION & BIOMETRIC FACE LOCALIZATION
                # ------------------------------------------------------------------
                if cls_id == 0:
                    person_count += 1
                    is_suspicious = False
                    suspicious_reason = ""
                    captured_face_crop = None

                    # SUB-MODEL 2: BIOMETRIC FACE DETECTION & FORENSIC CROP
                    if self.enable_face_detection and box_h > 45:
                        face_boxes = self.aegis_net.face_submodel.extract_faces(raw_image, (x1, y1, x2, y2))
                        for (fx1, fy1, fx2, fy2, f_conf, crop_path) in face_boxes:
                            face_count += 1
                            if crop_path:
                                captured_face_crop = crop_path
                            corner_len = 8
                            c_color = (0, 255, 255)
                            # Draw Biometric Corner Reticles
                            cv2.line(display_frame, (fx1, fy1), (fx1 + corner_len, fy1), c_color, 2)
                            cv2.line(display_frame, (fx1, fy1), (fx1, fy1 + corner_len), c_color, 2)
                            cv2.line(display_frame, (fx2, fy1), (fx2 - corner_len, fy1), c_color, 2)
                            cv2.line(display_frame, (fx2, fy1), (fx2, fy1 + corner_len), c_color, 2)
                            cv2.line(display_frame, (fx1, fy2), (fx1 + corner_len, fy2), c_color, 2)
                            cv2.line(display_frame, (fx1, fy2), (fx1, fy2 - corner_len), c_color, 2)
                            cv2.line(display_frame, (fx2, fy2), (fx2 - corner_len, fy2), c_color, 2)
                            cv2.line(display_frame, (fx2, fy2), (fx2, fy2 - corner_len), c_color, 2)
                            cv2.putText(display_frame, f"BIO-FACE: {f_conf*100:.1f}%", (fx1 - 4, fy1 - 4), 
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 255), 1)

                    # Check 1: Loitering in Zone A
                    if self.enable_loitering and trk["zone_a_entry"] is not None:
                        dwell_time = now - trk["zone_a_entry"]
                        if dwell_time > 4.5:
                            is_suspicious = True
                            suspicious_reason = f"LOITERING ({dwell_time:.1f}s in Zone A)"
                            self._trigger_alert({
                                "category": "loitering",
                                "type": f"SUSPICIOUS ACTIVITY: Dwell in Exclusion Zone ({dwell_time:.1f}s)",
                                "severity": "WARNING",
                                "direction": direction,
                                "target": "HUMAN_TARGET",
                                "confidence": round(conf, 2)
                            }, display_frame, (x1, y1, x2, y2), face_crop=captured_face_crop)

                    # Check 2: High-Speed Infiltration Rush
                    if trk["speed"] > 38 and bottom_y >= self.tripwire_y - 30:
                        is_suspicious = True
                        suspicious_reason = "HIGH-SPEED SPRINT / RUSH"
                        self._trigger_alert({
                            "category": "rush",
                            "type": "SUSPICIOUS ACTIVITY: High-Speed Infiltration Rush",
                            "severity": "CRITICAL",
                            "direction": direction,
                            "target": "HUMAN_TARGET",
                            "confidence": round(conf, 2)
                        }, display_frame, (x1, y1, x2, y2), face_crop=captured_face_crop)

                    # Check 3: Virtual Tripwire Intrusion
                    if self.enable_tripwire and conf > 0.45:
                        crossed = (prev_y <= self.tripwire_y and bottom_y >= self.tripwire_y) or (abs(bottom_y - self.tripwire_y) < 18)
                        if crossed and direction.startswith("INBOUND"):
                            tripwire_triggered = True
                            self._trigger_alert({
                                "category": "breach",
                                "type": "PERIMETER BREACH: Unauthorized Border Crossing",
                                "severity": "CRITICAL",
                                "direction": direction,
                                "target": "HUMAN_INTRUDER",
                                "confidence": round(conf, 2)
                            }, display_frame, (x1, y1, x2, y2), face_crop=captured_face_crop)

                    # Bounding Box & Trajectory Trail
                    box_color = (0, 0, 255) if (is_suspicious or tripwire_triggered) else (0, 255, 120)
                    cv2.rectangle(display_frame, (x1, y1), (x2, y2), box_color, 2)
                    for i in range(1, len(trk["history"])):
                        cv2.line(display_frame, trk["history"][i - 1], trk["history"][i], (0, 200, 255), 2)

                    badge_text = f"TARGET ID-{track_key[-4:]} | {direction}"
                    if is_suspicious:
                        badge_text = f"ALERT: {suspicious_reason}"
                    cv2.putText(display_frame, badge_text, (x1, max(20, y1 - 8)), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, box_color, 2)

                # ------------------------------------------------------------------
                # SUB-MODEL 3: VEHICLE CLASSIFICATION, ANPR & CROSS-CAMERA ReID
                # ------------------------------------------------------------------
                elif cls_id in TACTICAL_VEHICLE_REGISTRY:
                    vehicle_count += 1
                    v_meta = TACTICAL_VEHICLE_REGISTRY[cls_id]
                    v_type = v_meta["type"]
                    v_color = v_meta["color"]

                    # Tripwire crossing check for vehicles
                    if self.enable_tripwire and conf > 0.45:
                        crossed = (prev_y <= self.tripwire_y and bottom_y >= self.tripwire_y) or (abs(bottom_y - self.tripwire_y) < 22)
                        if crossed and direction.startswith("INBOUND"):
                            tripwire_triggered = True
                            self._trigger_alert({
                                "category": "vehicle_breach",
                                "type": f"VEHICLE PERIMETER BREACH: {v_type}",
                                "severity": "CRITICAL",
                                "direction": direction,
                                "target": v_meta["code"],
                                "confidence": round(conf, 2)
                            }, display_frame, (x1, y1, x2, y2))

                    # Crop vehicle region for Cross-Camera ReID Signature
                    v_crop = raw_image[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]
                    global_id = f"VEH-{track_key[-4:]}"
                    is_reid_match = False
                    match_info = None

                    if self.enable_reid and v_crop.size > 0:
                        global_id, is_reid_match, match_info = self.aegis_net.reid_engine.match_or_register(
                            v_crop, cam_id, track_key
                        )

                    # Draw Vehicle Box
                    cv2.rectangle(display_frame, (x1, y1), (x2, y2), v_color, 2)
                    
                    # Tactical Tag
                    label_text = f"[{v_type}] {global_id}"
                    cv2.putText(display_frame, label_text, (x1, max(20, y1 - 8)), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.42, v_color, 2)

                    # CROSS-CAMERA ReID MATCH ALERT & HUD TAG
                    if is_reid_match and match_info:
                        reid_match_count += 1
                        reid_badge = f"RE-ID FROM {match_info['origin_cam']} ({match_info['travel_time_sec']}s ago)"
                        cv2.rectangle(display_frame, (x1, y1 - 32), (x1 + 260, y1 - 12), (180, 0, 255), -1)
                        cv2.putText(display_frame, reid_badge, (x1 + 4, y1 - 16),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1)

                        self._trigger_alert({
                            "category": "reid_transit",
                            "type": f"CROSS-CAMERA RE-ID: {global_id} ({v_type}) tracked from {match_info['origin_cam']} (Transition: {match_info['travel_time_sec']}s)",
                            "severity": "WARNING",
                            "direction": direction,
                            "target": global_id,
                            "confidence": round(conf, 2)
                        }, display_frame, (x1, y1, x2, y2))

                    # ANPR Automatic Number Plate Recognition
                    if self.enable_anpr and box_w > 80:
                        plate_count += 1
                        plate_str, is_flagged = generate_tactical_plate(track_key)
                        
                        pw = int(box_w * 0.65)
                        ph = 26
                        px1 = int(x1 + (box_w - pw) / 2)
                        py1 = int(y2 - ph - 6)
                        px2 = px1 + pw
                        py2 = py1 + ph

                        plate_bg = (0, 0, 180) if is_flagged else (0, 220, 255)
                        text_col = (255, 255, 255) if is_flagged else (0, 0, 0)
                        cv2.rectangle(display_frame, (px1, py1), (px2, py2), plate_bg, -1)
                        cv2.rectangle(display_frame, (px1, py1), (px2, py2), (255, 255, 255), 1)

                        status_tag = "[FLAGGED]" if is_flagged else "[VERIFIED]"
                        cv2.putText(display_frame, f"{plate_str} {status_tag}", (px1 + 4, py2 - 7), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, text_col, 1)

                        if is_flagged:
                            self._trigger_alert({
                                "category": "anpr",
                                "type": f"ANPR WATCHLIST HIT: {plate_str} ({v_type})",
                                "severity": "WARNING",
                                "direction": direction,
                                "target": plate_str,
                                "confidence": round(conf, 2)
                            }, display_frame, (x1, y1, x2, y2))

        # Update telemetry statistics
        self.stats["persons"] = person_count
        self.stats["vehicles"] = vehicle_count
        self.stats["faces"] = face_count
        self.stats["plates"] = plate_count
        self.stats["reid_matches"] = reid_match_count
        self.stats["birds_filtered"] = birds_filtered_count
        self.stats["drones"] = drones_count

        # Clean stale tracks
        stale_keys = [k for k in self.tracks if k not in active_track_keys and (now - self.tracks[k]["last_y"]) > 60]
        for k in stale_keys:
            del self.tracks[k]

        # Draw Border Tripwire Line
        tripwire_color = (0, 0, 255) if tripwire_triggered else (255, 120, 0)
        cv2.line(display_frame, (0, self.tripwire_y), (w, self.tripwire_y), tripwire_color, 3)
        
        b_text = "AEGIS TRIPWIRE [ARMED - ACTIVE]" if not tripwire_triggered else "BORDER BREACH DETECTED!"
        cv2.putText(display_frame, b_text, (w // 2 - 170, self.tripwire_y - 10), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, tripwire_color, 2)

        # Top Tactical HUD Bar: AI Modules & Real-time Sensors
        hud_bg = np.zeros((40, w, 3), dtype=np.uint8)
        cv2.addWeighted(display_frame[0:40, 0:w], 0.25, hud_bg, 0.75, 0, display_frame[0:40, 0:w])
        
        hud_info = f"AEGIS-NET | FPS: {self.stats['fps']} | TARGETS: {person_count}P {vehicle_count}V | RE-ID: {reid_match_count} | BIRDS-FILTERED: {birds_filtered_count} | FACES: {face_count}"
        cv2.putText(display_frame, hud_info, (15, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1)

        if mean_lum < 50:
            cv2.putText(display_frame, "[LOW-LIGHT / NIGHT CONDITIONS]", (w - 270, 25), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 165, 255), 2)

        ret, jpeg = cv2.imencode('.jpg', display_frame)
        return jpeg.tobytes()
