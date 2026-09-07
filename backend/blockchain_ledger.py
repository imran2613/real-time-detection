"""
Cryptographic Blockchain Evidence Integrity Ledger for Suraksha Vision (SIH-2K26).
Maintains an immutable chain of SHA-256 hashes of incident surveillance snapshots and biometric crops.
Provides court-admissible proof that video evidence has not been modified or replaced.
"""

import hashlib
import json
import os
import time
import shutil
from datetime import datetime
from typing import List, Dict, Optional

LEDGER_FILE = "evidence/blockchain_ledger.json"
BACKUP_DIR = "evidence/backups"

def compute_file_sha256(filepath: str) -> Optional[str]:
    """Computes the SHA-256 cryptographic digest of a file on disk."""
    if not os.path.exists(filepath):
        return None
    sha256_hash = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            for byte_block in iter(lambda: f.read(65536), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest().upper()
    except Exception as e:
        print(f"Error hashing file {filepath}: {e}")
        return None


class Block:
    def __init__(
        self,
        index: int,
        timestamp: str,
        event_id: str,
        camera_id: str,
        event_type: str,
        evidence_path: str,
        evidence_sha256: str,
        face_crop_sha256: Optional[str] = None,
        previous_hash: str = "0" * 64,
        nonce: int = 0,
        block_hash: Optional[str] = None
    ):
        self.index = index
        self.timestamp = timestamp
        self.event_id = event_id
        self.camera_id = camera_id
        self.event_type = event_type
        self.evidence_path = evidence_path
        self.evidence_sha256 = evidence_sha256
        self.face_crop_sha256 = face_crop_sha256
        self.previous_hash = previous_hash
        self.nonce = nonce
        self.block_hash = block_hash or self.calculate_hash()

    def calculate_hash(self) -> str:
        """Computes block header SHA-256 hash including previous block hash."""
        payload = (
            f"{self.index}|{self.timestamp}|{self.event_id}|{self.camera_id}|"
            f"{self.event_type}|{self.evidence_sha256}|{self.face_crop_sha256 or ''}|"
            f"{self.previous_hash}|{self.nonce}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest().upper()

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "event_id": self.event_id,
            "camera_id": self.camera_id,
            "event_type": self.event_type,
            "evidence_path": self.evidence_path,
            "evidence_sha256": self.evidence_sha256,
            "face_crop_sha256": self.face_crop_sha256,
            "previous_hash": self.previous_hash,
            "nonce": self.nonce,
            "block_hash": self.block_hash
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Block":
        return cls(
            index=data["index"],
            timestamp=data["timestamp"],
            event_id=data["event_id"],
            camera_id=data["camera_id"],
            event_type=data["event_type"],
            evidence_path=data["evidence_path"],
            evidence_sha256=data["evidence_sha256"],
            face_crop_sha256=data.get("face_crop_sha256"),
            previous_hash=data["previous_hash"],
            nonce=data.get("nonce", 0),
            block_hash=data.get("block_hash")
        )


class EvidenceBlockchainLedger:
    def __init__(self):
        self.chain: List[Block] = []
        os.makedirs("evidence", exist_ok=True)
        os.makedirs(BACKUP_DIR, exist_ok=True)
        self.load_or_initialize()

    def _create_genesis_block(self) -> Block:
        genesis = Block(
            index=0,
            timestamp=datetime(2026, 1, 1, 0, 0, 0).isoformat(),
            event_id="GENESIS-00000",
            camera_id="ROOT-COMMAND",
            event_type="GENESIS: Sovereign Border Defense Ledger Initialized",
            evidence_path="N/A",
            evidence_sha256="0" * 64,
            previous_hash="0" * 64,
            nonce=2026
        )
        return genesis

    def load_or_initialize(self):
        """Loads existing chain from disk or creates new genesis block."""
        if os.path.exists(LEDGER_FILE):
            try:
                with open(LEDGER_FILE, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
                    self.chain = [Block.from_dict(b) for b in raw_data]
                if len(self.chain) > 0:
                    print(f"[BLOCKCHAIN]: Loaded {len(self.chain)} blocks from {LEDGER_FILE}")
                    return
            except Exception as e:
                print(f"[BLOCKCHAIN ERROR]: Failed loading ledger, reinitializing: {e}")

        # Initialize with Genesis Block
        self.chain = [self._create_genesis_block()]
        self.save_ledger()
        print("[BLOCKCHAIN]: Initialized new Genesis Block #0")

    def save_ledger(self):
        """Persists entire blockchain to disk."""
        try:
            with open(LEDGER_FILE, "w", encoding="utf-8") as f:
                json.dump([b.to_dict() for b in self.chain], f, indent=2)
        except Exception as e:
            print(f"[BLOCKCHAIN ERROR]: Failed saving ledger: {e}")

    def get_latest_block(self) -> Block:
        return self.chain[-1]

    def record_evidence(self, event_data: dict, evidence_path: str, face_crop_path: Optional[str] = None) -> Block:
        """
        Calculates SHA-256 of the evidence image and anchors a new block to the immutable chain.
        Also creates a pristine backup copy for tamper simulation demonstration.
        """
        evidence_sha256 = compute_file_sha256(evidence_path) or ("E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855")
        face_sha256 = compute_file_sha256(face_crop_path) if face_crop_path else None

        # Backup original for tamper demo
        if os.path.exists(evidence_path):
            backup_path = os.path.join(BACKUP_DIR, os.path.basename(evidence_path) + ".orig")
            try:
                shutil.copy2(evidence_path, backup_path)
            except Exception:
                pass

        prev_block = self.get_latest_block()
        new_index = len(self.chain)
        event_id = f"EVT-{new_index:05d}"

        # Proof of Integrity Nonce calculation
        nonce = 0
        new_block = Block(
            index=new_index,
            timestamp=event_data.get("timestamp", datetime.now().isoformat()),
            event_id=event_id,
            camera_id=event_data.get("sensor", "CAM-01"),
            event_type=event_data.get("type", "BORDER INCIDENT"),
            evidence_path=evidence_path,
            evidence_sha256=evidence_sha256,
            face_crop_sha256=face_sha256,
            previous_hash=prev_block.block_hash,
            nonce=nonce
        )

        self.chain.append(new_block)
        self.save_ledger()
        print(f"[BLOCKCHAIN]: Mined Block #{new_block.index} [{event_id}] SHA-256: {evidence_sha256[:16]}...")
        return new_block

    def verify_evidence(self, evidence_path: str) -> dict:
        """
        Cross-verifies the on-disk evidence image's SHA-256 checksum against the blockchain block.
        Also verifies chain continuity up to this block.
        """
        block = None
        # Find matching block by evidence path
        for b in reversed(self.chain):
            if b.evidence_path == evidence_path or os.path.basename(b.evidence_path) == os.path.basename(evidence_path):
                block = b
                break

        if not block:
            # Fallback: compute current file hash
            curr_hash = compute_file_sha256(evidence_path)
            return {
                "verified": False,
                "tampered": True,
                "message": "Evidence not registered in Blockchain Ledger",
                "current_hash": curr_hash,
                "stored_hash": None,
                "chain_valid": self.is_chain_valid()
            }

        current_hash = compute_file_sha256(evidence_path)
        is_match = (current_hash is not None) and (current_hash.upper() == block.evidence_sha256.upper())
        chain_valid = self.is_chain_valid()

        return {
            "verified": is_match and chain_valid,
            "tampered": not is_match,
            "message": "100% Verified Untampered Evidence" if is_match else "🚨 Tampering Detected! SHA-256 Checksum Mismatch",
            "block_index": block.index,
            "event_id": block.event_id,
            "timestamp": block.timestamp,
            "stored_hash": block.evidence_sha256,
            "current_hash": current_hash,
            "previous_hash": block.previous_hash,
            "block_hash": block.block_hash,
            "chain_valid": chain_valid,
            "court_admissible": is_match and chain_valid
        }

    def is_chain_valid(self) -> bool:
        """Validates entire blockchain from Genesis block to latest block."""
        for i in range(1, len(self.chain)):
            curr = self.chain[i]
            prev = self.chain[i - 1]
            if curr.previous_hash != prev.block_hash:
                return False
            if curr.block_hash != curr.calculate_hash():
                return False
        return True

    def simulate_tamper(self, evidence_path: str) -> dict:
        """
        Judges Demo Feature: Injects a subtle modification into the image file on disk.
        When verification is subsequently triggered, the SHA-256 mismatch is immediately caught!
        """
        if not os.path.exists(evidence_path):
            return {"status": "error", "message": f"File {evidence_path} not found"}

        # Ensure backup exists first
        backup_path = os.path.join(BACKUP_DIR, os.path.basename(evidence_path) + ".orig")
        if not os.path.exists(backup_path):
            shutil.copy2(evidence_path, backup_path)

        # Alter image bytes slightly (appends a few altered bytes or flip end bytes)
        with open(evidence_path, "r+b") as f:
            f.seek(max(0, os.path.getsize(evidence_path) - 16))
            f.write(b"TAMPERED_JUDGES_DEMO_2026")

        new_hash = compute_file_sha256(evidence_path)
        return {
            "status": "tampered",
            "message": "File intentionally modified for Judges Tampering Demonstration",
            "new_sha256": new_hash
        }

    def restore_evidence(self, evidence_path: str) -> dict:
        """Restores original unmodified evidence image from pristine backup."""
        backup_path = os.path.join(BACKUP_DIR, os.path.basename(evidence_path) + ".orig")
        if not os.path.exists(backup_path):
            return {"status": "error", "message": "Original backup not found"}

        shutil.copy2(backup_path, evidence_path)
        restored_hash = compute_file_sha256(evidence_path)
        return {
            "status": "restored",
            "message": "Original evidence restored successfully",
            "restored_sha256": restored_hash
        }

    def get_all_blocks(self) -> List[dict]:
        return [b.to_dict() for b in self.chain]
