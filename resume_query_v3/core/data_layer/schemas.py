from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class DocumentBlock:
    block_id: str
    page_no: int
    text: str
    raw_text: str
    source_file: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceRef:
    block_ids: List[str] = field(default_factory=list)
    text_snippets: List[str] = field(default_factory=list)
    page_refs: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "block_ids": list(self.block_ids),
            "text_snippets": list(self.text_snippets),
            "page_refs": list(self.page_refs),
        }


def build_evidence(blocks: List[DocumentBlock]) -> Dict[str, Any]:
    return EvidenceRef(
        block_ids=[block.block_id for block in blocks],
        text_snippets=[block.text[:240] for block in blocks],
        page_refs=sorted({block.page_no for block in blocks}),
    ).to_dict()


def make_scored_value(
    *,
    value: Any,
    confidence: float,
    evidence: Dict[str, Any],
    source: str,
    extra: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    payload = {
        "value": value,
        "confidence": round(float(confidence), 4),
        "evidence": evidence,
        "source": source,
    }
    if extra:
        payload.update(extra)
    return payload
