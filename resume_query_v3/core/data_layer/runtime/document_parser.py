from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any, Dict, List, Tuple
import unicodedata
from contextlib import nullcontext, redirect_stderr, redirect_stdout

import docx
from pypdf import PdfReader

from ..schemas import DocumentBlock


def parse_resume_to_blocks(file_path: Path, config: Dict[str, Any]) -> List[DocumentBlock]:
    blocks, _ = parse_resume_to_blocks_with_diagnostics(file_path, config)
    return blocks


def parse_resume_to_blocks_with_diagnostics(
    file_path: Path,
    config: Dict[str, Any],
) -> Tuple[List[DocumentBlock], Dict[str, Any]]:
    parser_fallback_reason = ""
    if config["ingestion"].get("use_docling", True):
        try:
            return _parse_with_docling(
                file_path,
                verbose_third_party=bool(config.get("logging", {}).get("verbose_third_party", False)),
            ), {"parser_mode": "docling", "parser_fallback_reason": ""}
        except Exception as error:
            parser_fallback_reason = f"{type(error).__name__}: {error}"
    return _parse_with_builtin(file_path), {
        "parser_mode": "builtin",
        "parser_fallback_reason": parser_fallback_reason,
    }


def _parse_with_docling(file_path: Path, *, verbose_third_party: bool = False) -> List[DocumentBlock]:
    from docling.document_converter import DocumentConverter  # type: ignore

    sink = io.StringIO()
    context = nullcontext() if verbose_third_party else redirect_stderr(sink)
    with context:
        with nullcontext() if verbose_third_party else redirect_stdout(sink):
            converter = DocumentConverter()
            result = converter.convert(str(file_path))
    markdown = str(result.document.export_to_markdown() or "")
    return _build_blocks(source_file=file_path, page_texts=[markdown])


def _parse_with_builtin(file_path: Path) -> List[DocumentBlock]:
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(str(file_path))
        return _build_blocks(source_file=file_path, page_texts=[page.extract_text() or "" for page in reader.pages])
    if suffix == ".docx":
        doc = docx.Document(str(file_path))
        text = "\n".join(paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip())
        return _build_blocks(source_file=file_path, page_texts=[text])
    text = file_path.read_text(encoding="utf-8", errors="ignore")
    return _build_blocks(source_file=file_path, page_texts=[text])


def _build_blocks(*, source_file: Path, page_texts: List[str]) -> List[DocumentBlock]:
    blocks: List[DocumentBlock] = []
    for page_no, page_text in enumerate(page_texts, start=1):
        paragraphs = [line.strip() for line in str(page_text or "").replace("\r\n", "\n").split("\n") if line.strip()]
        for line_index, paragraph in enumerate(paragraphs, start=1):
            paragraph = unicodedata.normalize("NFKC", paragraph).replace("\x00", "").strip()
            if not paragraph:
                continue
            digest = hashlib.sha1(f"{source_file}|{page_no}|{line_index}|{paragraph}".encode("utf-8")).hexdigest()[:12]
            blocks.append(
                DocumentBlock(
                    block_id=f"b{page_no}_{digest}",
                    page_no=page_no,
                    text=paragraph,
                    raw_text=paragraph,
                    source_file=str(source_file),
                )
            )
    return blocks
