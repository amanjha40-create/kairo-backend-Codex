#!/usr/bin/env python3
"""Generate deterministic PDF and DOCX documents for the synthetic 7G corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from html import escape
from pathlib import Path

from reportlab.pdfgen import canvas

_FIXED_ZIP_TIME = (2020, 1, 1, 0, 0, 0)


def write_pdf(path: Path, text: str) -> None:
    document = canvas.Canvas(str(path), pagesize=(612, 792), invariant=1)
    y = 754
    page_has_content = False
    for line in text.splitlines():
        if line.startswith(("PAGE 2 ", "PAGE 3 ")) and page_has_content:
            document.showPage()
            y = 754
            page_has_content = False
        if y < 42:
            document.showPage()
            y = 754
            page_has_content = False
        document.setFont("Helvetica", 10)
        document.drawString(42, y, line[:120])
        y -= 14
        page_has_content = True
    document.save()


def zip_entry(archive: zipfile.ZipFile, name: str, content: str) -> None:
    info = zipfile.ZipInfo(name, _FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, content.encode())


def write_docx(path: Path, text: str) -> None:
    paragraphs = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{escape(line)}</w:t></w:r></w:p>'
        for line in text.splitlines()
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{paragraphs}<w:sectPr/></w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        zip_entry(archive, "[Content_Types].xml", content_types)
        zip_entry(archive, "_rels/.rels", relationships)
        zip_entry(archive, "word/document.xml", document)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate(corpus_path: Path, output: Path) -> dict[str, object]:
    fixtures = json.loads(corpus_path.read_text())
    output.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, object]] = []
    for fixture in fixtures:
        for file_format in fixture["formats"]:
            path = output / f"{fixture['id']}.{file_format}"
            if file_format == "pdf":
                write_pdf(path, fixture["text"])
            elif file_format == "docx":
                write_docx(path, fixture["text"])
            else:
                raise ValueError(f"Unsupported fixture format: {file_format}")
            files.append(
                {
                    "fixture_id": fixture["id"],
                    "format": file_format,
                    "path": path.name,
                    "byte_size": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
    manifest = {
        "synthetic_only": True,
        "fixture_count": len(fixtures),
        "document_count": len(files),
        "files": files,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = generate(args.corpus, args.output)
    print(
        json.dumps(
            {
                "document_count": manifest["document_count"],
                "fixture_count": manifest["fixture_count"],
                "synthetic_only": manifest["synthetic_only"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
