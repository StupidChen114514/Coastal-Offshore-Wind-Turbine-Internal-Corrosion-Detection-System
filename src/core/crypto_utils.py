"""
Cryptographic utilities for the Wind Turbine Internal Corrosion Detection System.

Provides data integrity verification (CRC-16, SHA-256), password hashing
(PBKDF2-HMAC-SHA256), secure token generation, and AES-128-GCM authenticated
encryption for LoRa payload protection.
"""

import hashlib
import hmac
import os
import secrets
from typing import Optional, Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CryptoUtils:
    """Cryptographic utilities for data integrity and confidentiality."""

    _CRC16_POLY = 0x1021
    _CRC16_INIT = 0xFFFF
    _CRC16_TABLE: Optional[list] = None

    @classmethod
    def _ensure_crc16_table(cls) -> None:
        if cls._CRC16_TABLE is not None:
            return
        table = []
        for i in range(256):
            crc = i << 8
            for _ in range(8):
                if crc & 0x8000:
                    crc = ((crc << 1) ^ cls._CRC16_POLY) & 0xFFFF
                else:
                    crc = (crc << 1) & 0xFFFF
            table.append(crc)
        cls._CRC16_TABLE = table

    @staticmethod
    def crc16(data: bytes) -> int:
        """Calculate CRC-16-CCITT checksum (polynomial 0x1021, initial 0xFFFF).

        Used for data integrity verification of sensor records.
        """
        CryptoUtils._ensure_crc16_table()
        crc = CryptoUtils._CRC16_INIT
        for byte in data:
            idx = ((crc >> 8) ^ byte) & 0xFF
            crc = ((crc << 8) ^ CryptoUtils._CRC16_TABLE[idx]) & 0xFFFF
        return crc

    @staticmethod
    def sha256_hash(data: bytes) -> str:
        """SHA-256 hash for configuration parameter integrity.

        Returns hex string.
        """
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def generate_salt(length: int = 32) -> bytes:
        """Generate random salt for password hashing."""
        return os.urandom(length)

    @staticmethod
    def hash_password(password: str, salt: Optional[bytes] = None) -> Tuple[str, bytes]:
        """Hash password using PBKDF2-HMAC-SHA256 with 100,000 iterations.

        Returns (hash_hex_string, salt_bytes)
        """
        if salt is None:
            salt = CryptoUtils.generate_salt()
        dk = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            100000,
        )
        return dk.hex(), salt

    @staticmethod
    def verify_password(password: str, stored_hash: str, salt: bytes) -> bool:
        """Verify password against stored hash using constant-time comparison."""
        computed_hash, _ = CryptoUtils.hash_password(password, salt)
        return hmac.compare_digest(computed_hash, stored_hash)

    @staticmethod
    def generate_token(length: int = 32) -> str:
        """Generate a secure random token for API/auth.

        Uses secrets.token_hex() for cryptographically secure randomness.
        """
        return secrets.token_hex(length)

    @staticmethod
    def aes_encrypt(plaintext: bytes, key: bytes) -> bytes:
        """AES-128-GCM encryption for LoRa payload.

        Returns nonce(12) + ciphertext + tag(16).
        Key must be 16 bytes (128 bits).
        """
        if len(key) != 16:
            raise ValueError("AES-128 key must be exactly 16 bytes")
        nonce = os.urandom(12)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        return nonce + ciphertext

    @staticmethod
    def aes_decrypt(ciphertext: bytes, key: bytes) -> bytes:
        """AES-128-GCM decryption.

        Extracts nonce(12), ciphertext, and tag(16) from combined bytes.
        Raises InvalidTag if authentication fails.
        """
        if len(key) != 16:
            raise ValueError("AES-128 key must be exactly 16 bytes")
        if len(ciphertext) < 28:
            raise ValueError("Ciphertext too short: must be at least 28 bytes (nonce+tag)")
        nonce = ciphertext[:12]
        ct = ciphertext[12:]
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ct, None)
