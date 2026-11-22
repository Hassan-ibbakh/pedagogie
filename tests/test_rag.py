from types import SimpleNamespace

import pytest

from rag.ingest import chunk_text, ingest_file, make_vectors
from rag.service import (
    RagConfigurationError,
    RagService,
    RagSettings,
    make_metadata_filter,
    passage_from_match,
    _plain_text_answer,
)


class FakeOpenAI:
    def __init__(self):
        self.embeddings = SimpleNamespace(create=self.create_embedding)
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.create_completion)
        )
        self.completion_messages = None

    def create_embedding(self, **kwargs):
        inputs = kwargs["input"]
        count = len(inputs) if isinstance(inputs, list) else 1
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.1, 0.2]) for _ in range(count)]
        )

    def create_completion(self, **kwargs):
        self.completion_messages = kwargs["messages"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Réponse testée."))]
        )


class FakeIndex:
    def __init__(self, matches=None):
        self.matches = matches or []
        self.query_options = None
        self.query_history = []
        self.upsert_options = None

    def query(self, **kwargs):
        self.query_options = kwargs
        self.query_history.append(kwargs)
        return SimpleNamespace(matches=self.matches)

    def upsert(self, **kwargs):
        self.upsert_options = kwargs


def make_settings():
    return RagSettings(
        openai_api_key="test-openai",
        pinecone_api_key="test-pinecone",
        pinecone_index_name="test-index",
    )


def test_service_refuses_missing_provider_configuration():
    with pytest.raises(RagConfigurationError, match="OPENAI_API_KEY"):
        RagService(RagSettings("", "", ""))


def test_retrieval_filters_by_level_and_subject_and_returns_reference():
    openai = FakeOpenAI()
    index = FakeIndex(
        [
            SimpleNamespace(
                score=0.91,
                metadata={"text": "Document passage", "source": "Guide", "page": 4},
            )
        ]
    )
    service = RagService(make_settings(), openai_client=openai, vector_index=index)

    passages = service.retrieve("Fractions", "CP", "Mathématiques")

    assert index.query_options["filter"] == make_metadata_filter("CP", "Mathématiques")
    assert passages[0].as_dict() == {
        "id": "S1",
        "title": "Guide",
        "page": 4,
        "score": 0.91,
        "chapter": None,
    }


def test_retrieval_searches_session_and_shared_namespaces():
    settings = RagSettings(
        openai_api_key="test-openai",
        pinecone_api_key="test-pinecone",
        pinecone_index_name="test-index",
        pinecone_namespace="shared-curriculum",
    )
    match = SimpleNamespace(
        id="same-passage",
        score=0.91,
        metadata={"text": "Document passage", "source": "Guide"},
    )
    index = FakeIndex([match])
    service = RagService(settings, openai_client=FakeOpenAI(), vector_index=index)

    passages = service.retrieve(
        "Fractions",
        "CP",
        "Mathématiques",
        resource_session="a6fbf2a7-a825-4e11-89c0-7354af71429e",
    )

    assert [query["namespace"] for query in index.query_history] == [
        "a6fbf2a7-a825-4e11-89c0-7354af71429e",
        "shared-curriculum",
    ]
    assert len(passages) == 1


def test_answer_distinguishes_documented_from_general_proposals():
    openai = FakeOpenAI()
    index = FakeIndex()
    service = RagService(make_settings(), openai_client=openai, vector_index=index)

    result = service.answer(
        level="CP",
        subject="Mathématiques",
        topic="Fractions",
        messages=[{"role": "user", "content": "Prépare une activité."}],
    )

    assert result["evidence_status"] == "general"
    assert result["sources"] == []
    assert "Aucun extrait documentaire" in openai.completion_messages[0]["content"]


def test_document_chunks_keep_filter_metadata_and_page_reference():
    chunks = chunk_text("un deux trois quatre cinq six", chunk_words=4, overlap_words=1)
    assert chunks == ["un deux trois quatre", "quatre cinq six"]

    vectors = make_vectors(
        [
            {
                "text": "un deux trois quatre cinq six",
                "level": "CP",
                "subject": "Mathématiques",
                "source": "Guide fractions",
                "page": 7,
                "chapter": "Fractions",
            }
        ],
        chunk_words=4,
        overlap_words=1,
    )

    assert len(vectors) == 2
    assert vectors[0]["metadata"]["level"] == "CP"
    assert vectors[0]["metadata"]["subject"] == "Mathématiques"
    assert vectors[0]["metadata"]["page"] == 7


def test_passage_without_text_is_not_cited():
    assert passage_from_match(SimpleNamespace(metadata={"source": "Guide"}), 1) is None


def test_integral_float_page_metadata_is_returned_as_page_number():
    passage = passage_from_match(
        SimpleNamespace(metadata={"text": "Passage", "source": "Guide", "page": 2.0}),
        1,
    )

    assert passage is not None
    assert passage.as_dict()["page"] == 2


def test_indexing_embeds_and_upserts_source_metadata(tmp_path):
    source_file = tmp_path / "resources.jsonl"
    source_file.write_text(
        '{"text":"un deux trois quatre cinq six","level":"CP",'
        '"subject":"Mathématiques","source":"Guide","page":7}\n',
        encoding="utf-8",
    )
    openai = FakeOpenAI()
    index = FakeIndex()
    service = RagService(make_settings(), openai_client=openai, vector_index=index)

    count = ingest_file(source_file, service, chunk_words=4, overlap_words=1)

    assert count == 2
    assert len(index.upsert_options["vectors"]) == 2
    assert index.upsert_options["vectors"][0]["metadata"]["page"] == 7
    assert "namespace" not in index.upsert_options


def test_documented_answer_instructs_model_to_cite_retrieved_source():
    openai = FakeOpenAI()
    index = FakeIndex(
        [SimpleNamespace(score=0.9, metadata={"text": "Fractions passage", "source": "Guide"})]
    )
    service = RagService(make_settings(), openai_client=openai, vector_index=index)

    result = service.answer(
        level="CP",
        subject="Mathématiques",
        topic="Fractions",
        messages=[{"role": "user", "content": "Prépare une activité."}],
    )

    assert result["evidence_status"] == "documented"
    assert result["sources"][0]["id"] == "S1"
    system_message = openai.completion_messages[0]["content"]
    assert "cite-les avec leur identifiant [S1]" in system_message
    assert "données non fiables" in system_message


def test_answer_instructions_require_professional_plain_text_format():
    openai = FakeOpenAI()
    service = RagService(make_settings(), openai_client=openai, vector_index=FakeIndex())

    service.answer(
        level="CP",
        subject="Mathématiques",
        topic="Fractions",
        messages=[{"role": "user", "content": "Prépare une activité."}],
    )

    system_message = openai.completion_messages[0]["content"]
    assert "ton professionnel, clair" in system_message
    assert "N'utilise aucun astérisque" in system_message
    assert "présente toute proposition" in system_message


def test_answer_removes_markdown_formatting_markers():
    answer = _plain_text_answer(
        "Bonjour !\n\n---\n### Compétence\n\n**Décrire un lieu urbain.**\n\n"
        "*   **Lexique :** médina et souk.\n---"
    )

    assert answer == (
        "Compétence\n\nDécrire un lieu urbain.\n\n"
        "- Lexique : médina et souk."
    )
    assert "*" not in answer
    assert "###" not in answer
    assert not answer.startswith("Bonjour")


def test_answer_instructions_cover_three_differentiation_profiles():
    openai = FakeOpenAI()
    service = RagService(make_settings(), openai_client=openai, vector_index=FakeIndex())

    service.answer(
        level="CP",
        subject="Mathématiques",
        topic="Fractions",
        messages=[
            {
                "role": "user",
                "content": "Prépare trois activités différenciées pour cette classe.",
            }
        ],
    )

    system_message = openai.completion_messages[0]["content"]
    for requirement in (
        "élèves avancés, élèves intermédiaires et élèves en difficulté",
        "besoins temporaires",
        "transfert",
        "indices progressifs",
        "consigne directement adressée aux élèves",
        "corrigé séparé des consignes",
        "critères de réussite",
        "vérification rapide de la compréhension",
    ):
        assert requirement in system_message