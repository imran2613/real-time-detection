# SURAKSHA VISION • Tactical AI Surveillance Matrix (SIH-2K26)

Advanced Multi-Camera Tactical Border Surveillance System integrating Real-Time Neural Perception (CSPDarknet Backbone, Biometric Face Localization, Cross-Camera Vehicle Re-ID, Airborne Micro-Target Discrimination, and Virtual Tripwire Intrusion Analytics) with an **Immutable Cryptographic Blockchain Evidence Ledger** for court-admissible, tamper-evident forensic intelligence.

---

## 🚀 Key Features

1. **3-Column Intuitive Command Dashboard**:
   - **Column 1 (Camera Hub)**: Instant zero-hang switching across multi-sensor nodes (`CAM-01` Base Laptop Webcam, `CAM-02` Patrol Phone 1 IP Webcam, `CAM-03` Recon Phone 2 IP Webcam).
   - **Column 2 (Real Time Camera Viewport)**: High-resolution live MJPEG feed with 4 tactical vision optic filters directly underneath:
     - ☀️ **DAY**: Natural optical spectrum.
     - 🔥 **THERMAL**: High-contrast FLIR thermal heatmap.
     - 🌧️ **RAIN**: Bilateral dehaze and fog penetration.
     - 🌙 **NIGHT VISION**: Phosphor green infrared illumination.
   - **Column 3 (Real Time Incident Stream)**: Live forensic breach cards, severity ratings, direction vectors, and snapshot previews.

2. **Biometric Face Capture at Border Perimeter**:
   - Automated facial isolation when an intruder breaches the virtual tripwire or loiters in the restricted buffer zone.
   - Picture-in-picture (PiP) biometric face inset embedded on forensic snapshots and saved to the intelligence dossier.

3. **Cryptographic Blockchain Evidence Integrity Ledger**:
   - Computes SHA-256 cryptographic hashes of every incident snapshot and biometric face crop.
   - Commits records to an immutable, decentralized-style blockchain ledger with previous-hash anchoring.
   - **Court-Admissible Verification**: Live hash verification directly from the UI (`100% UNTAMPERED EVIDENCE`).
   - **Judges Tamper Simulation Demo**: Interactive button demonstrating instant detection of modified or corrupted video/image evidence.

---

## 🛠️ Architecture & Tech Stack

- **Backend**: Python 3, FastAPI, OpenCV, Ultralytics YOLO, Cryptographic Blockchain Ledger (SHA-256).
- **Frontend**: React 19, Vite, TailwindCSS, Lucide Icons.
- **Protocols**: HTTP REST API, MJPEG Video Streaming, RTSP / IP Webcam endpoints.

---

## 📦 Setup & Running Locally

### 1. Backend Setup
```bash
cd backend
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 2. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

Visit **`http://localhost:5173`** in your browser.
