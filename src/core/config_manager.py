"""
JSON-based configuration management with validation and fallback support.

Manages loading, saving, and validating configuration from JSON files.
Supports default value fallback, configuration version tracking, and
range validation for all configurable parameters.
"""

import json
import os
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional


class ConfigManager:
    """
    Singleton configuration manager for the corrosion detection system.

    Features:
        - JSON-based configuration loading and saving
        - Default value fallback from default_config.json
        - Configuration version tracking
        - Value range validation
        - Thread-safe operations
    """

    _instance: Optional["ConfigManager"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls, *args, **kwargs) -> "ConfigManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config_dir: str = "config") -> None:
        if hasattr(self, "_initialized") and self._initialized:
            return

        self._initialized = True
        self._config_dir = Path(config_dir)
        self._config_path = self._config_dir / "config.json"
        self._default_config_path = self._config_dir / "default_config.json"
        self._lock = threading.Lock()

        self._default_config: Dict[str, Any] = {}
        self._active_config: Dict[str, Any] = {}
        self._loaded = False

    def load(self) -> None:
        """Load configuration, falling back to defaults if needed."""
        with self._lock:
            self._load_defaults()
            self._load_active()
            self._loaded = True

    def _load_defaults(self) -> None:
        """Load the default configuration template."""
        if self._default_config_path.exists():
            with open(self._default_config_path, "r", encoding="utf-8") as f:
                self._default_config = json.load(f)
        else:
            self._default_config = {}

    def _load_active(self) -> None:
        """Load active configuration, merging with defaults for missing keys."""
        if self._config_path.exists():
            with open(self._config_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            self._active_config = self._merge_configs(
                deepcopy(self._default_config), user_config
            )
        else:
            self._active_config = deepcopy(self._default_config)

    def _merge_configs(
        self, base: Dict[str, Any], override: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Recursively merge override config into base config."""
        for key, value in override.items():
            if (
                key in base
                and isinstance(base[key], dict)
                and isinstance(value, dict)
            ):
                self._merge_configs(base[key], value)
            else:
                base[key] = value
        return base

    def save(self, config: Optional[Dict[str, Any]] = None) -> bool:
        """
        Save the current (or provided) configuration to disk.

        Args:
            config: Optional configuration dict to save. If None, saves active config.

        Returns:
            True if save succeeded, False otherwise.
        """
        with self._lock:
            try:
                os.makedirs(self._config_dir, exist_ok=True)
                data = config if config is not None else self._active_config
                with open(self._config_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                return True
            except (IOError, OSError) as e:
                print(f"ConfigManager: Failed to save config: {e}")
                return False

    def get(self, path: str, default: Any = None) -> Any:
        """
        Get a configuration value by dot-separated path.

        Args:
            path: Dot-separated path, e.g. 'sensor.d0.value'.
            default: Default value if path not found.

        Returns:
            The configuration value, or default if not found.
        """
        if not self._loaded:
            self.load()

        keys = path.split(".")
        current: Any = self._active_config
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key)
            else:
                return default
            if current is None:
                return default
        return current

    def get_default(self, path: str, default: Any = None) -> Any:
        """Get a value from the default configuration."""
        keys = path.split(".")
        current: Any = self._default_config
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key)
            else:
                return default
            if current is None:
                return default
        return current

    def set(self, path: str, value: Any) -> bool:
        """
        Set a configuration value by dot-separated path.

        Validation is performed before setting. Returns False if validation fails.

        Args:
            path: Dot-separated path, e.g. 'sensor.d0.value'.
            value: New value to set.

        Returns:
            True if set succeeded, False if validation failed.
        """
        if not self._loaded:
            self.load()

        if not self._validate_value(path, value):
            return False

        with self._lock:
            keys = path.split(".")
            current = self._active_config
            for key in keys[:-1]:
                if key not in current:
                    current[key] = {}
                current = current[key]
            current[keys[-1]] = value
            return True

    def _validate_value(self, path: str, value: Any) -> bool:
        """
        Validate a configuration value against defined ranges.

        Args:
            path: Dot-separated configuration path.
            value: Value to validate.

        Returns:
            True if value is within valid range or no range defined.
        """
        ranges = self._active_config.get("validation_ranges", {})
        range_def = ranges.get(path)
        if range_def is None:
            return True

        try:
            numeric_value = float(value)
            min_val = range_def.get("min")
            max_val = range_def.get("max")

            if min_val is not None and numeric_value < min_val:
                print(
                    f"ConfigManager: Validation failed for '{path}': "
                    f"{value} < min({min_val})"
                )
                return False

            if max_val is not None and numeric_value > max_val:
                print(
                    f"ConfigManager: Validation failed for '{path}': "
                    f"{value} > max({max_val})"
                )
                return False

            return True
        except (ValueError, TypeError):
            return True

    def get_all(self) -> Dict[str, Any]:
        """Get the entire active configuration dictionary."""
        if not self._loaded:
            self.load()
        return deepcopy(self._active_config)

    def get_version(self) -> str:
        """Get the configuration version string."""
        return str(self.get("version", "0.0.0"))

    def reset_to_defaults(self) -> None:
        """Reset active configuration to default values."""
        with self._lock:
            self._active_config = deepcopy(self._default_config)

    def reload(self) -> None:
        """Force reload configuration from disk."""
        self._loaded = False
        self.load()

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (useful for testing)."""
        with cls._lock:
            cls._instance = None
