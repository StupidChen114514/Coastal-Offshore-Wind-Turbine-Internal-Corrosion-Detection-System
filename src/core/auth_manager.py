"""
Authentication and Authorization Manager for the Wind Turbine Internal
Corrosion Detection System.

Implements role-based access control (RBAC) with three permission levels:
    Viewer (观察者)  – View real-time data and historical trends only.
    Operator (操作员) – Viewer + acknowledge/resolve alarms + export data.
    Admin (管理员)    – Operator + modify system config + import calibration
                        curves + firmware upgrade.

Features password-based and token-based authentication, account lockout
after repeated failures, and session management.
"""

import json
import os
import threading
import time
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from .crypto_utils import CryptoUtils
from .logger import CorrosionLogger

_logger = CorrosionLogger().get_logger("Auth")


class Permission(Enum):
    VIEW_REALTIME = "view_realtime"
    VIEW_HISTORY = "view_history"
    ACKNOWLEDGE_ALARM = "acknowledge_alarm"
    RESOLVE_ALARM = "resolve_alarm"
    EXPORT_DATA = "export_data"
    MODIFY_CONFIG = "modify_config"
    IMPORT_CALIBRATION = "import_calibration"
    FIRMWARE_UPGRADE = "firmware_upgrade"
    VIEW_AUDIT_LOG = "view_audit_log"
    MANAGE_USERS = "manage_users"


ROLE_PERMISSIONS: Dict[str, list] = {
    "Viewer": [
        Permission.VIEW_REALTIME,
        Permission.VIEW_HISTORY,
    ],
    "Operator": [
        Permission.VIEW_REALTIME,
        Permission.VIEW_HISTORY,
        Permission.ACKNOWLEDGE_ALARM,
        Permission.RESOLVE_ALARM,
        Permission.EXPORT_DATA,
    ],
    "Admin": [
        Permission.VIEW_REALTIME,
        Permission.VIEW_HISTORY,
        Permission.ACKNOWLEDGE_ALARM,
        Permission.RESOLVE_ALARM,
        Permission.EXPORT_DATA,
        Permission.MODIFY_CONFIG,
        Permission.IMPORT_CALIBRATION,
        Permission.FIRMWARE_UPGRADE,
        Permission.VIEW_AUDIT_LOG,
        Permission.MANAGE_USERS,
    ],
}


class PermissionError(Exception):
    """Raised when a user attempts an action they lack permission for."""


class AuthManager:
    """Authentication and Authorization Manager with RBAC support."""

    _DEFAULT_USER_FILE = "config/users.json"
    _DEFAULT_ADMIN = "admin"
    _DEFAULT_ADMIN_PASS = "admin123"

    def __init__(self, storage_manager=None) -> None:
        self._storage = storage_manager
        self._current_user: Optional[str] = None
        self._current_role: Optional[str] = None
        self._login_attempts: Dict[str, int] = {}
        self._lockout_until: Dict[str, float] = {}
        self._max_attempts = 5
        self._lockout_duration = 1800
        self._token_timeout = 3600
        self._tokens: Dict[str, Tuple[str, float]] = {}
        self._lock = threading.RLock()

        self._users: Dict[str, dict] = {}
        self._user_file = self._DEFAULT_USER_FILE
        self._load_users()

        if not self._users:
            self._init_default_admin()

    def _load_users(self) -> None:
        if not os.path.exists(self._user_file):
            return
        try:
            with open(self._user_file, "r", encoding="utf-8") as f:
                self._users = json.load(f)
        except (json.JSONDecodeError, IOError) as exc:
            _logger.warning("Failed to load users file: %s", exc)
            self._users = {}

    def _save_users(self) -> None:
        os.makedirs(os.path.dirname(self._user_file), exist_ok=True)
        with open(self._user_file, "w", encoding="utf-8") as f:
            json.dump(self._users, f, indent=2, ensure_ascii=False)

    def _init_default_admin(self) -> None:
        _logger.info("Creating default admin user")
        pwd_hash, pwd_salt = CryptoUtils.hash_password(self._DEFAULT_ADMIN_PASS)
        self._users[self._DEFAULT_ADMIN] = {
            "password_hash": pwd_hash,
            "salt": pwd_salt.hex(),
            "role": "Admin",
            "created_at": time.time(),
        }
        self._save_users()

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def login(self, username: str, password: str) -> Tuple[bool, str]:
        """Authenticate user with username and password.

        Returns:
            (success, message)
        """
        identifier = f"user:{username}"

        if self.is_locked_out(identifier):
            remaining = int(self._lockout_until[identifier] - time.time())
            return False, f"账户已锁定，请在 {remaining} 秒后重试"

        with self._lock:
            user = self._users.get(username)
            if user is None:
                self._record_failed_attempt(identifier)
                return False, "用户名或密码错误"

            stored_hash = user.get("password_hash", "")
            stored_salt = bytes.fromhex(user.get("salt", ""))

            if CryptoUtils.verify_password(password, stored_hash, stored_salt):
                self._current_user = username
                self._current_role = user.get("role", "Viewer")
                self._login_attempts.pop(identifier, None)
                _logger.info("User '%s' logged in successfully (role: %s)",
                             username, self._current_role)
                return True, f"登录成功，欢迎 {username}（{self._current_role}）"

            self._record_failed_attempt(identifier)
            return False, "用户名或密码错误"

    def login_with_token(self, token: str) -> Tuple[bool, str]:
        """Authenticate with pre-generated token.

        Returns:
            (success, message)
        """
        with self._lock:
            entry = self._tokens.get(token)
            if entry is None:
                return False, "无效的令牌"

            username, expiry = entry
            if time.time() > expiry:
                del self._tokens[token]
                return False, "令牌已过期"

            user = self._users.get(username)
            if user is None:
                del self._tokens[token]
                return False, "令牌关联的用户不存在"

            self._current_user = username
            self._current_role = user.get("role", "Viewer")
            _logger.info("User '%s' authenticated via token", username)
            return True, f"令牌认证成功，欢迎 {username}"

    def _record_failed_attempt(self, identifier: str) -> None:
        with self._lock:
            attempts = self._login_attempts.get(identifier, 0) + 1
            self._login_attempts[identifier] = attempts
            if attempts >= self._max_attempts:
                self._lockout_until[identifier] = time.time() + self._lockout_duration
                _logger.warning("%s locked out after %d failed attempts", identifier, attempts)

    def logout(self) -> None:
        if self._current_user:
            _logger.info("User '%s' logged out", self._current_user)
        self._current_user = None
        self._current_role = None

    def get_current_user(self) -> Optional[str]:
        return self._current_user

    def get_current_role(self) -> Optional[str]:
        return self._current_role

    # ------------------------------------------------------------------
    # Authorization
    # ------------------------------------------------------------------

    def has_permission(self, permission: Permission) -> bool:
        """Check if the current user has the specified permission."""
        if self._current_role is None:
            return False
        allowed = ROLE_PERMISSIONS.get(self._current_role, [])
        return permission in allowed

    def require_permission(self, permission: Permission) -> None:
        """Raise PermissionError if current user lacks the permission."""
        if not self.has_permission(permission):
            user = self._current_user or "未登录用户"
            raise PermissionError(
                f"用户 '{user}' 没有执行 '{permission.value}' 操作的权限"
            )

    # ------------------------------------------------------------------
    # User management
    # ------------------------------------------------------------------

    def create_user(self, username: str, password: str, role: str) -> bool:
        """Admin only: create a new user.

        Returns True on success.
        """
        self.require_permission(Permission.MANAGE_USERS)

        if role not in ROLE_PERMISSIONS:
            _logger.warning("Attempt to create user with invalid role: %s", role)
            return False

        with self._lock:
            if username in self._users:
                _logger.warning("Attempt to create duplicate user: %s", username)
                return False

            pwd_hash, pwd_salt = CryptoUtils.hash_password(password)
            self._users[username] = {
                "password_hash": pwd_hash,
                "salt": pwd_salt.hex(),
                "role": role,
                "created_at": time.time(),
                "created_by": self._current_user,
            }
            self._save_users()
            _logger.info("User '%s' created with role '%s' by '%s'",
                         username, role, self._current_user)
            return True

    def change_password(self, username: str, old_password: str,
                         new_password: str) -> bool:
        """Change a user's password.

        Returns True on success.
        """
        if self._current_user is None:
            return False

        is_admin = self.has_permission(Permission.MANAGE_USERS)
        if self._current_user != username and not is_admin:
            return False

        with self._lock:
            user = self._users.get(username)
            if user is None:
                return False

            if self._current_user == username and not is_admin:
                stored_hash = user.get("password_hash", "")
                stored_salt = bytes.fromhex(user.get("salt", ""))
                if not CryptoUtils.verify_password(old_password, stored_hash, stored_salt):
                    return False

            pwd_hash, pwd_salt = CryptoUtils.hash_password(new_password)
            user["password_hash"] = pwd_hash
            user["salt"] = pwd_salt.hex()
            self._save_users()
            _logger.info("Password changed for user '%s'", username)
            return True

    # ------------------------------------------------------------------
    # Lockout
    # ------------------------------------------------------------------

    def is_locked_out(self, identifier: str) -> bool:
        """Check if a user/IP identifier is currently locked out."""
        with self._lock:
            until = self._lockout_until.get(identifier)
            if until is None:
                return False
            if time.time() < until:
                return True
            self._lockout_until.pop(identifier, None)
            self._login_attempts.pop(identifier, None)
            return False

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def generate_auth_token(self, username: str) -> Optional[str]:
        """Generate a temporary authentication token for the given user.

        Admin only. Returns the token string or None.
        """
        try:
            self.require_permission(Permission.MANAGE_USERS)
        except PermissionError:
            return None

        if username not in self._users:
            return None

        token = CryptoUtils.generate_token()
        expiry = time.time() + self._token_timeout
        with self._lock:
            self._tokens[token] = (username, expiry)
        _logger.info("Auth token generated for '%s' by '%s'", username, self._current_user)
        return token
