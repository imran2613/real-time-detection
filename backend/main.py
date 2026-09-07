from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse, PlainTextResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os
import time
import csv
import io

from camera import VideoCamera
from blockchain_ledger import EvidenceBlockchainLedger

app = FastAPI(title="Aegis-VisionNet - Multi-Submodel Tactical Border Surveillance Platform")

# Mount static directory for evidence images and biometric face crops
os.makedirs("evidence", exist_ok=True)
os.makedirs("evidence/faces", exist_ok=True)
app.mount("/evidence", StaticFiles(directory="evidence"), name="evidence")

# Allow frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

alerts = []
camera = None
blockchain = EvidenceBlockchainLedger()

def new_alert_callback(alert_data):
    severity = alert_data.get('severity', 'WARNING')
    print(f"[AEGIS ALERT - {severity}]: {alert_data['type']} | {alert_data.get('direction', '')}")
    
    # Cryptographic Blockchain Commitment: Anchor SHA-256 digest to immutable ledger
    evidence_path = alert_data.get("image")
    face_crop_path = alert_data.get("face_crop")
    if evidence_path and os.path.exists(evidence_path):
        block = blockchain.record_evidence(alert_data, evidence_path, face_crop_path)
        alert_data["blockchain"] = block.to_dict()
        alert_data["event_id"] = block.event_id
        alert_data["evidence_sha256"] = block.evidence_sha256
        alert_data["block_index"] = block.index
        alert_data["block_hash"] = block.block_hash
        alert_data["previous_hash"] = block.previous_hash
        alert_data["chain_valid"] = blockchain.is_chain_valid()

    alerts.insert(0, alert_data)
    if len(alerts) > 150:
        alerts.pop()

def gen_frames():
    global camera
    while True:
        if camera:
            frame = camera.get_frame()
            if frame is not None:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n\r\n')
            time.sleep(0.03)
        else:
            time.sleep(0.1)

@app.on_event("startup")
def startup_event():
    global camera
    camera = VideoCamera(alert_callback=new_alert_callback, source=0)

@app.on_event("shutdown")
def shutdown_event():
    global camera
    if camera:
        del camera

@app.get("/video_feed")
def video_feed():
    return StreamingResponse(gen_frames(), media_type="multipart/x-mixed-replace; boundary=frame")

@app.get("/alerts")
def get_alerts():
    return {"alerts": alerts}

@app.post("/clear_alerts")
def clear_alerts():
    global alerts
    alerts = []
    return {"status": "cleared"}

@app.get("/cross_cam_tracks")
def get_cross_cam_tracks():
    """Returns all tracked targets across all non-overlapping surveillance nodes."""
    global camera
    if camera and hasattr(camera, "aegis_net"):
        records = camera.aegis_net.reid_engine.get_all_records()
        return {"records": records, "total_tracked": len(records)}
    return {"records": [], "total_tracked": 0}

@app.get("/face_dossier")
def get_face_dossier():
    """Returns list of recent biometric face crop snapshots."""
    faces_dir = "evidence/faces"
    crops = []
    if os.path.exists(faces_dir):
        files = sorted(os.listdir(faces_dir), reverse=True)[:24]
        for f in files:
            if f.endswith(".jpg") or f.endswith(".png"):
                crops.append(f"/evidence/faces/{f}")
    return {"face_crops": crops}

@app.get("/export_alerts")
def export_alerts():
    """Generates an exportable CSV incident intelligence report for command & control with blockchain proof."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Event ID", "Timestamp", "Category", "Incident Type", "Severity", "Target", "Direction", "Vision Mode", "Confidence", "Sensor Node", "SHA-256 Digest", "Block #", "Court Status", "Evidence Snapshot"])
    
    for idx, a in enumerate(alerts):
        writer.writerow([
            a.get("event_id", f"EVT-{idx+1:05d}"),
            a.get("timestamp", ""),
            a.get("category", "breach").upper(),
            a.get("type", ""),
            a.get("severity", "WARNING"),
            a.get("target", "UNKNOWN"),
            a.get("direction", "N/A"),
            a.get("mode", "NORMAL"),
            a.get("confidence", 1.0),
            a.get("sensor", "CAM-01"),
            a.get("evidence_sha256", "ON-CHAIN"),
            a.get("block_index", idx + 1),
            "VERIFIED UNTAMPERED" if a.get("chain_valid", True) else "TAMPER WARNING",
            a.get("image", "")
        ])
    
    csv_data = output.getvalue()
    return PlainTextResponse(
        content=csv_data, 
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=RealTime_Detection_Blockchain_Report.csv"}
    )

@app.post("/set_mode")
def set_vision_mode(mode: str = Query(..., description="normal, night, thermal, rain")):
    global camera
    if camera:
        camera.set_mode(mode)
        return {"status": "success", "mode": mode}
    return {"status": "error", "message": "Camera not ready"}

class FeatureToggleRequest(BaseModel):
    feature: str # face_detection, anpr, loitering, tripwire, night_boost, reid, airborne_filter
    enabled: bool

@app.post("/toggle_feature")
def toggle_feature(req: FeatureToggleRequest):
    global camera
    if camera:
        ok = camera.toggle_feature(req.feature, req.enabled)
        return {"status": "success" if ok else "failed", "feature": req.feature, "enabled": req.enabled}
    return {"status": "error", "message": "Camera not ready"}

@app.get("/status")
def get_status():
    global camera
    mode = camera.vision_mode if camera else "normal"
    source = camera.source if camera else 0
    connected = camera.connected if camera else False
    connection_status = camera.connection_status if camera else "Offline"
    stats = camera.stats if camera else {}
    features = {
        "face_detection": camera.enable_face_detection if camera else True,
        "anpr": camera.enable_anpr if camera else True,
        "loitering": camera.enable_loitering if camera else True,
        "tripwire": camera.enable_tripwire if camera else True,
        "night_boost": camera.enable_night_boost if camera else True,
        "reid": camera.enable_reid if camera else True,
        "airborne_filter": camera.enable_airborne_filter if camera else True
    }
    return {
        "architecture": "Aegis-VisionNet v2.0 (5 Sub-Models Active)",
        "mode": mode,
        "source": str(source),
        "connected": connected,
        "connection_status": connection_status,
        "stats": stats,
        "features": features,
        "alerts_count": len(alerts),
        "blockchain": {
            "total_blocks": len(blockchain.chain),
            "is_chain_valid": blockchain.is_chain_valid(),
            "latest_block_hash": blockchain.get_latest_block().block_hash
        }
    }

class CameraSourceRequest(BaseModel):
    source: str # e.g. "0" for webcam or "http://192.168.1.15:8080/video" for phone

@app.post("/set_source")
def set_camera_source(req: CameraSourceRequest):
    global camera
    if camera:
        success = camera.set_source(req.source)
        return {"status": "success" if success else "failed", "source": req.source}
    return {"status": "error", "message": "Camera not initialized"}

# --------------------------------------------------------------------------
# CRYPTOGRAPHIC BLOCKCHAIN EVIDENCE ENDPOINTS
# --------------------------------------------------------------------------
class BlockchainVerifyRequest(BaseModel):
    evidence_path: str

@app.get("/blockchain/blocks")
def get_blockchain_blocks():
    """Returns the complete immutable blockchain evidence chain."""
    return {
        "chain": blockchain.get_all_blocks(),
        "total_blocks": len(blockchain.chain),
        "is_chain_valid": blockchain.is_chain_valid(),
        "latest_block_hash": blockchain.get_latest_block().block_hash
    }

@app.post("/blockchain/verify")
def verify_blockchain_evidence(req: BlockchainVerifyRequest):
    """Calculates live SHA-256 of file on disk and verifies against blockchain block."""
    result = blockchain.verify_evidence(req.evidence_path)
    return result

@app.post("/blockchain/simulate_tamper")
def simulate_evidence_tamper(req: BlockchainVerifyRequest):
    """Judges Demonstration: Simulates unauthorized file tampering on disk."""
    result = blockchain.simulate_tamper(req.evidence_path)
    return result

@app.post("/blockchain/restore_evidence")
def restore_evidence(req: BlockchainVerifyRequest):
    """Restores the pristine original evidence file and clears tampering."""
    result = blockchain.restore_evidence(req.evidence_path)
    return result
