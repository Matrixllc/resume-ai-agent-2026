"""Core read-only access to resume storage."""

from .candidate_index import list_known_candidate_names
from .config import get_data_access_config
from .sql_reader import ResumeSqlReader, parse_evidence_ids
from .vector_reader import ResumeVectorReader, parse_metadata_list

__all__ = [
    "ResumeSqlReader",
    "ResumeVectorReader",
    "get_data_access_config",
    "list_known_candidate_names",
    "parse_evidence_ids",
    "parse_metadata_list",
]
