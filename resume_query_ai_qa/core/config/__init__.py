"""配置公共入口，兼容原 `resume_query_ai_qa.core.config` 导入路径。"""

from __future__ import annotations

from .compiler_flags import CompilerConfigError
from .loader import load_config
from .model import ResumeQAConfig

__all__ = ["CompilerConfigError", "ResumeQAConfig", "load_config"]
