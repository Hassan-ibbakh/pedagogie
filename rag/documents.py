from io import BytesIO
from pathlib import Path
from typing import Any


MAX_EXTRACTED_CHARACTERS = 200_000
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}


class DocumentExtractionError(ValueError):
    """Raised when an uploaded resource is invalid or contains no extractable text."""


def extract_resource(filename: str, content: bytes, level: str, subject: str) -> list[dict[str, Any]]:
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise DocumentExtractionError("Formats acceptés : PDF, DOCX et TXT.")
    if not content:
        raise DocumentExtractionError("Le fichier est vide.")

    try:
        if extension == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(content), strict=False)
            if len(reader.pages) > 250:
                raise DocumentExtractionError("Un document ne peut pas dépasser 250 pages.")
            pages = [
                {"text": page.extract_text() or "", "page": page_number}
                for page_number, page in enumerate(reader.pages, start=1)
            ]
        elif extension == ".docx":
            from docx import Document
            from docx.table import Table
            from docx.text.paragraph import Paragraph

            document = Document(BytesIO(content))
            content_blocks = []
            for block in document.iter_inner_content():
                if isinstance(block, Paragraph):
                    if block.text.strip():
                        content_blocks.append(block.text)
                elif isinstance(block, Table):
                    for row in block.rows:
                        cells = [" ".join(cell.text.split()) for cell in row.cells]
                        if any(cells):
                            content_blocks.append(" | ".join(cells))
            text = "\n".join(content_blocks)
            pages = [{"text": text, "page": None}]
        else:
            text = content.decode("utf-8-sig")
            pages = [
                {"text": text, "page": page_number}
                for page_number, text in enumerate(text.split("\f"), start=1)
            ]
    except DocumentExtractionError:
        raise
    except Exception as error:
        raise DocumentExtractionError(
            "Impossible de lire ce fichier. Vérifiez qu’il n’est pas protégé ou endommagé."
        ) from error

    total_characters = sum(len(page["text"]) for page in pages)
    if total_characters > MAX_EXTRACTED_CHARACTERS:
        raise DocumentExtractionError("Le document contient trop de texte pour une session.")
    if not any(page["text"].strip() for page in pages):
        raise DocumentExtractionError(
            "Aucun texte n’a été extrait. Les PDF scannés nécessitent une étape OCR."
        )

    source = Path(filename).name[:200]
    return [
        {
            "text": page["text"],
            "level": level,
            "subject": subject,
            "source": source,
            "page": page["page"],
        }
        for page in pages
        if page["text"].strip()
    ]