import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

from rag.service import RagService, RagSettings


LEVELS = {"CP", "CE1", "CE2", "CM1", "CM2", "6ème"}
SUBJECTS = {"Mathématiques", "Arabe", "Français"}


def chunk_text(text: str, chunk_words: int = 220, overlap_words: int = 40) -> list[str]:
    words = text.split()
    if not words:
        return []
    if chunk_words < 1 or overlap_words < 0 or overlap_words >= chunk_words:
        raise ValueError("La taille du fragment et son chevauchement sont invalides.")

    step = chunk_words - overlap_words
    return [
        " ".join(words[start : start + chunk_words])
        for start in range(0, len(words), step)
        if words[start : start + chunk_words]
    ]


def make_vectors(
    records: Iterable[dict[str, Any]],
    chunk_words: int = 220,
    overlap_words: int = 40,
) -> list[dict[str, Any]]:
    vectors = []
    for record_number, record in enumerate(records, start=1):
        text = record.get("text")
        level = record.get("level")
        subject = record.get("subject")
        source = record.get("source")
        if not all(isinstance(value, str) and value.strip() for value in (text, level, subject, source)):
            raise ValueError(f"Le document {record_number} doit contenir text, level, subject et source.")
        if level not in LEVELS:
            raise ValueError(f"Niveau non pris en charge dans le document {record_number}: {level}")
        if subject not in SUBJECTS:
            raise ValueError(f"Matière non prise en charge dans le document {record_number}: {subject}")

        page = record.get("page")
        chapter = record.get("chapter")
        resource_type = record.get("resource_type")
        for chunk_number, chunk in enumerate(
            chunk_text(text, chunk_words=chunk_words, overlap_words=overlap_words)
        ):
            raw_id = f"{source}\n{page}\n{chunk_number}\n{chunk}"
            metadata = {
                "text": chunk,
                "level": level,
                "subject": subject,
                "source": source.strip(),
            }
            if isinstance(page, (str, int)):
                metadata["page"] = page
            if isinstance(chapter, str) and chapter.strip():
                metadata["chapter"] = chapter.strip()
            if isinstance(resource_type, str) and resource_type.strip():
                metadata["resource_type"] = resource_type.strip()
            vectors.append(
                {
                    "id": hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:32],
                    "text": chunk,
                    "metadata": metadata,
                }
            )
    return vectors


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open("r", encoding="utf-8-sig") as source_file:
        for line_number, line in enumerate(source_file, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"JSON invalide à la ligne {line_number}.") from error
            if not isinstance(record, dict):
                raise ValueError(f"La ligne {line_number} doit contenir un objet JSON.")
            records.append(record)
    return records


def ingest_records(
    records: Iterable[dict[str, Any]],
    service: RagService,
    namespace: str | None = None,
    chunk_words: int = 220,
    overlap_words: int = 40,
) -> int:
    vectors = make_vectors(
        records, chunk_words=chunk_words, overlap_words=overlap_words
    )
    if not vectors:
        return 0

    batch_size = 32
    for start in range(0, len(vectors), batch_size):
        batch = vectors[start : start + batch_size]
        embedded = service.openai.embeddings.create(
            model=service.settings.openai_embedding_model,
            input=[vector["text"] for vector in batch],
        )
        pinecone_vectors = [
            {"id": vector["id"], "values": item.embedding, "metadata": vector["metadata"]}
            for vector, item in zip(batch, embedded.data, strict=True)
        ]
        upsert_options = {"vectors": pinecone_vectors}
        target_namespace = namespace or service.settings.pinecone_namespace
        if target_namespace:
            upsert_options["namespace"] = target_namespace
        service.index.upsert(**upsert_options)
    return len(vectors)


def ingest_file(
    path: Path,
    service: RagService,
    chunk_words: int = 220,
    overlap_words: int = 40,
) -> int:
    return ingest_records(
        load_jsonl(path),
        service,
        chunk_words=chunk_words,
        overlap_words=overlap_words,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Indexe des ressources pédagogiques JSONL dans Pinecone."
    )
    parser.add_argument("jsonl_file", type=Path, help="Fichier UTF-8 contenant un document JSON par ligne")
    parser.add_argument("--chunk-words", type=int, default=int(os.getenv("RAG_CHUNK_WORDS", "220")))
    parser.add_argument("--overlap-words", type=int, default=int(os.getenv("RAG_OVERLAP_WORDS", "40")))
    arguments = parser.parse_args()

    service = RagService(RagSettings.from_environment())
    count = ingest_file(
        arguments.jsonl_file,
        service,
        chunk_words=arguments.chunk_words,
        overlap_words=arguments.overlap_words,
    )
    print(f"{count} fragments indexés dans {service.settings.pinecone_index_name}.")


if __name__ == "__main__":
    main()