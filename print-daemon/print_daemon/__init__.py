"""Print daemon package: poll the queue service and print raw ESC/POS bytes."""

from .config import Config, ConfigError

__all__ = ["Config", "ConfigError"]
__version__ = "0.1.0"
