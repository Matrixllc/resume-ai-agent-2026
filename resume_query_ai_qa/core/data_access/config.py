from typing import Any, Dict

from resume_query_common import get_resume_data_config


def get_data_access_config() -> Dict[str, Any]:
    """返回简历问答数据访问层使用的只读存储位置。"""
    return get_resume_data_config()
