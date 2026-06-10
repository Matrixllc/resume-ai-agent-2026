"""配置校验公共入口，保持旧的 core.config_validation import 兼容。"""

from __future__ import annotations

from .orchestrator import ConfigStructureError, validate_config_structure

__all__ = ["ConfigStructureError", "validate_config_structure"]
