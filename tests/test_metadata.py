"""Cheap document metadata and filename version hints."""

from __future__ import annotations

import pytest

from doc_bundle_inventory.metadata import extract_metadata
from doc_bundle_inventory.names import version_hints


def test_docx_and_pdf_metadata(sample_tools) -> None:
    docx = extract_metadata("docx", sample_tools.build_docx())
    assert docx == {
        "title": sample_tools.DOCX_TITLE,
        "author": sample_tools.AUTHOR,
        "modified": sample_tools.MODIFIED,
        "page_count": 2,
    }
    pdf = extract_metadata("pdf", sample_tools.build_pdf())
    assert pdf["title"] == sample_tools.PDF_TITLE
    assert pdf["author"] == sample_tools.AUTHOR
    assert pdf["modified"] == "2024-06-01T09:00:00Z"
    assert pdf["page_count"] == 1


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("项目说明_v1.2_终稿.txt", ["v1.2", "终稿"]),
        ("报告/第3版.docx", ["第3版"]),
        ("spec_final.pdf", ["final"]),
        ("notes_draft.md", ["draft"]),
        ("overview.txt", []),
        ("合同_终稿.docx", ["终稿"]),
    ],
)
def test_version_hints(name: str, expected: list[str]) -> None:
    assert version_hints(name) == expected
