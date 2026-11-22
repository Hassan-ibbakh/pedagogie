from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

from docx import Document
from fastapi.testclient import TestClient

import main
from main import app
from rag.documents import DocumentExtractionError, extract_resource


class FakeIndex:
    def __init__(self):
        self.upsert_options = None
        self.deleted_namespace = None

    def upsert(self, **kwargs):
        self.upsert_options = kwargs

    def delete(self, **kwargs):
        self.deleted_namespace = kwargs["namespace"]


class FakeResourceService:
    def __init__(self):
        self.settings = SimpleNamespace(
            openai_embedding_model="test-embedding",
            pinecone_namespace=None,
        )
        self.index = FakeIndex()
        self.openai = SimpleNamespace(
            embeddings=SimpleNamespace(create=self.create_embeddings)
        )

    def create_embeddings(self, **kwargs):
        texts = kwargs["input"]
        count = len(texts) if isinstance(texts, list) else 1
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.1, 0.2]) for _ in range(count)]
        )

    def delete_resource_session(self, namespace):
        self.index.delete(namespace=namespace)


def test_text_extraction_returns_grade_subject_and_page_metadata():
    records = extract_resource(
        "lesson.txt",
        "Les nombres et les formes".encode("utf-8"),
        "CP",
        "Arabe",
    )

    assert records == [
        {
            "text": "Les nombres et les formes",
            "level": "CP",
            "subject": "Arabe",
            "source": "lesson.txt",
            "page": 1,
        }
    ]


def test_docx_extraction_reads_paragraphs():
    document = Document()
    document.add_paragraph("Comprendre les fractions")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Séance"
    table.cell(0, 1).text = "Objectif"
    table.cell(1, 0).text = "1"
    table.cell(1, 1).text = "Décrire une ville"
    data = BytesIO()
    document.save(data)

    records = extract_resource("lesson.docx", data.getvalue(), "CM1", "Mathématiques")

    assert records[0]["text"].startswith("Comprendre les fractions\n")
    assert "Séance | Objectif" in records[0]["text"]
    assert "1 | Décrire une ville" in records[0]["text"]
    assert records[0]["level"] == "CM1"


def test_scanned_pdf_without_text_is_explained():
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    data = BytesIO()
    writer.write(data)

    try:
        extract_resource("scan.pdf", data.getvalue(), "6ème", "Français")
    except DocumentExtractionError as error:
        assert "OCR" in str(error)
    else:
        raise AssertionError("A scanned PDF without extractable text must be rejected.")


def test_upload_indexes_document_in_session_namespace(monkeypatch):
    service = FakeResourceService()
    monkeypatch.setattr(main, "get_rag_service", lambda: service)
    session_id = uuid4()
    response = TestClient(app).post(
        "/api/resources",
        data={"resource_session": str(session_id), "level": "CE1", "subject": "Arabe"},
        files={"files": ("cours.txt", "Un texte pédagogique.", "text/plain")},
    )

    assert response.status_code == 200
    assert response.json()["resources"][0]["chunks_indexed"] == 1
    options = service.index.upsert_options
    assert options["namespace"] == str(session_id)
    assert options["vectors"][0]["metadata"]["level"] == "CE1"
    assert options["vectors"][0]["metadata"]["subject"] == "Arabe"


def test_upload_enforces_vercel_request_budget(monkeypatch):
    monkeypatch.setattr(main, "get_rag_service", lambda: FakeResourceService())
    response = TestClient(app).post(
        "/api/resources",
        data={"resource_session": str(uuid4()), "level": "CP", "subject": "Français"},
        files={"files": ("large.txt", b"a" * (4 * 1024 * 1024 + 1), "text/plain")},
    )

    assert response.status_code == 413
    assert "4 Mo" in response.json()["detail"]


def test_resource_session_can_be_deleted(monkeypatch):
    service = FakeResourceService()
    monkeypatch.setattr(main, "get_rag_service", lambda: service)
    session_id = uuid4()

    response = TestClient(app).delete(f"/api/resources/{session_id}")

    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert service.index.deleted_namespace == str(session_id)


def test_chat_api_forwards_custom_pedagogical_prompt(monkeypatch):
    class FakeService:
        def answer(self, **kwargs):
            assert kwargs["pedagogical_prompt"] == "Prépare une séquence courte."
            assert kwargs["resource_session"] is not None
            return {"answer": "Réponse.", "sources": [], "evidence_status": "general"}

    monkeypatch.setattr(main, "get_rag_service", lambda: FakeService())
    response = TestClient(app).post(
        "/api/chat",
        json={
            "level": "CP",
            "subject": "Arabe",
            "pedagogical_prompt": "Prépare une séquence courte.",
            "resource_session": str(uuid4()),
            "messages": [{"role": "user", "content": "Les nombres."}],
        },
    )

    assert response.status_code == 200