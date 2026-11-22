from pathlib import Path

from typing import Literal
from uuid import UUID
from datetime import datetime

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, model_validator
from starlette.concurrency import run_in_threadpool

from rag.documents import DocumentExtractionError, extract_resource
from rag.conversations import (
    ConversationStoreConfigurationError,
    ConversationStoreError,
    get_conversation_store,
)
from rag.ingest import chunk_text, ingest_records
from rag.service import (
    RagConfigurationError,
    RagProviderError,
    RagService,
    RagSettings,
    get_rag_service,
)


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Classe Claire", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/public", StaticFiles(directory=BASE_DIR / "public"), name="public")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

LEVELS = ["CP", "CE1", "CE2", "CM1", "CM2", "6ème"]
SUBJECTS = ["Arabe", "Français", "Mathématiques"]
DURATIONS = ["1 séance", "2 séances", "3 séances", "4 séances", "À définir"]
MAX_RESOURCE_UPLOAD_BYTES = 4 * 1024 * 1024


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    conversation_id: UUID | None = None
    message: str | None = Field(default=None, min_length=1, max_length=4000)
    level: Literal["CP", "CE1", "CE2", "CM1", "CM2", "6ème"] | None = None
    subject: Literal["Mathématiques", "Arabe", "Français"] | None = None
    topic: str = Field(default="", max_length=180)
    pedagogical_prompt: str = Field(default="", max_length=2000)
    resource_session: UUID | None = None
    messages: list[ChatMessage] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def latest_message_must_be_from_user(self):
        if self.conversation_id:
            if not self.message:
                raise ValueError("Un message est requis pour continuer la conversation.")
            return self
        if self.level is None or self.subject is None or not self.messages:
            raise ValueError("Un contexte et un message utilisateur sont requis.")
        if self.messages[-1].role != "user":
            raise ValueError("Le dernier message doit venir de l'enseignant.")
        return self


class SourceReference(BaseModel):
    id: str
    title: str
    page: str | int | None = None
    score: float | None = None
    chapter: str | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceReference]
    evidence_status: Literal["documented", "general"]
    conversation_id: UUID | None = None
    expires_at: datetime | None = None


class ConversationCreateRequest(BaseModel):
    level: Literal["CP", "CE1", "CE2", "CM1", "CM2", "6ème"]
    subject: Literal["Mathématiques", "Arabe", "Français"]
    topic: str = Field(default="", max_length=180)
    pedagogical_prompt: str = Field(default="", max_length=2000)
    resource_session: UUID | None = None


class ConversationTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    sources: list[SourceReference] = Field(default_factory=list)
    evidence_status: Literal["documented", "general"] | None = None


class ConversationResponse(BaseModel):
    id: UUID
    level: Literal["CP", "CE1", "CE2", "CM1", "CM2", "6ème"]
    subject: Literal["Mathématiques", "Arabe", "Français"]
    topic: str
    pedagogical_prompt: str
    resource_session: UUID | None = None
    messages: list[ConversationTurn]
    created_at: datetime
    updated_at: datetime
    expires_at: datetime


class UploadedResource(BaseModel):
    filename: str
    chunks_indexed: int


class ResourceUploadResponse(BaseModel):
    resource_session: UUID
    resources: list[UploadedResource]


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"active_page": "home"},
    )


@app.get("/espace", response_class=HTMLResponse)
async def teacher_workspace(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"active_page": "workspace"},
    )


@app.get("/preparer", response_class=HTMLResponse)
async def prepare(request: Request):
    values = {
        "level": request.query_params.get("level", ""),
        "subject": request.query_params.get("subject", ""),
    }
    return templates.TemplateResponse(
        request=request,
        name="prepare.html",
        context={
            "active_page": "prepare",
            "levels": LEVELS,
            "subjects": SUBJECTS,
            "durations": DURATIONS,
            "values": values,
        },
    )


@app.post("/preparer", response_class=HTMLResponse)
async def create_outline(request: Request):
    form_data = await request.form()
    values = {key: str(value).strip() for key, value in form_data.items()}
    outline = {
        "level": values.get("level", ""),
        "subject": values.get("subject", ""),
        "topic": values.get("topic", "").strip(),
        "duration": values.get("duration", ""),
        "goal": values.get("goal", "").strip(),
    }

    if outline["level"] not in LEVELS or outline["subject"] not in SUBJECTS:
        return templates.TemplateResponse(
            request=request,
            name="prepare.html",
            context={
                "active_page": "prepare",
                "levels": LEVELS,
                "subjects": SUBJECTS,
                "durations": DURATIONS,
                "error": "Sélectionnez un niveau et une matière valides.",
                "values": outline,
            },
            status_code=422,
        )

    return templates.TemplateResponse(
        request=request,
        name="workspace.html",
        context={"active_page": "prepare", "outline": outline},
    )


@app.get("/sequences", response_class=HTMLResponse)
async def sequences(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="sequences.html",
        context={"active_page": "sequences"},
    )


@app.get("/assistant", response_class=HTMLResponse)
async def assistant_page(request: Request):
    requested_level = request.query_params.get("level", "")
    requested_subject = request.query_params.get("subject", "")
    values = {
        "level": requested_level if requested_level in LEVELS else "",
        "subject": requested_subject if requested_subject in SUBJECTS else "",
        "topic": request.query_params.get("topic", "")[:180],
    }
    return templates.TemplateResponse(
        request=request,
        name="assistant.html",
        context={
            "active_page": "assistant",
            "levels": LEVELS,
            "subjects": SUBJECTS,
            "values": values,
        },
    )


@app.post("/api/chat", response_model=ChatResponse)
def assistant_chat(payload: ChatRequest):
    store = None
    record = None
    if payload.conversation_id:
        try:
            store = get_conversation_store()
            record = store.get(payload.conversation_id)
        except ConversationStoreConfigurationError as error:
            raise HTTPException(
                status_code=503,
                detail={"code": "redis_not_configured", "message": "La sauvegarde Redis n’est pas configurée."},
            ) from error
        except ConversationStoreError as error:
            raise HTTPException(
                status_code=503,
                detail={"code": "redis_unavailable", "message": "La conversation n’a pas pu être chargée."},
            ) from error
        if record is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "conversation_expired", "message": "Cette conversation a expiré ou a été supprimée."},
            )

        record["messages"].append({"role": "user", "content": payload.message})
        try:
            store.save(record)
        except ConversationStoreError as error:
            raise HTTPException(
                status_code=503,
                detail={"code": "redis_unavailable", "message": "Le message n’a pas pu être sauvegardé."},
            ) from error

        level = record["level"]
        subject = record["subject"]
        topic = record.get("topic", "")
        pedagogical_prompt = record.get("pedagogical_prompt", "")
        resource_session = record.get("resource_session")
        messages = [
            {"role": message["role"], "content": message["content"]}
            for message in record["messages"][-30:]
        ]
    else:
        level = payload.level
        subject = payload.subject
        topic = payload.topic.strip()
        pedagogical_prompt = payload.pedagogical_prompt.strip()
        resource_session = str(payload.resource_session) if payload.resource_session else None
        messages = [message.model_dump() for message in payload.messages]

    try:
        service = get_rag_service()
        answer = service.answer(
            level=level,
            subject=subject,
            topic=topic,
            pedagogical_prompt=pedagogical_prompt,
            messages=messages,
            resource_session=resource_session,
        )
    except RagConfigurationError as error:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "rag_not_configured",
                "message": "L’assistant documentaire n’est pas encore configuré.",
            },
        ) from error
    except RagProviderError as error:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "rag_provider_error",
                "message": "La recherche ou la génération est temporairement indisponible.",
            },
        ) from error
    if record is None:
        return answer

    record["messages"].append(
        {
            "role": "assistant",
            "content": answer["answer"],
            "sources": answer["sources"],
            "evidence_status": answer["evidence_status"],
        }
    )
    try:
        store.save(record)
    except ConversationStoreError as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "redis_unavailable", "message": "La réponse n’a pas pu être sauvegardée."},
        ) from error
    return {
        **answer,
        "conversation_id": record["id"],
        "expires_at": record["expires_at"],
    }


@app.post("/api/conversations", response_model=ConversationResponse)
def create_conversation(payload: ConversationCreateRequest):
    try:
        store = get_conversation_store()
        record = store.create(
            {
                "level": payload.level,
                "subject": payload.subject,
                "topic": payload.topic.strip(),
                "pedagogical_prompt": payload.pedagogical_prompt.strip(),
                "resource_session": (
                    str(payload.resource_session) if payload.resource_session else None
                ),
            }
        )
        return record
    except ConversationStoreConfigurationError as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "redis_not_configured", "message": "La sauvegarde Redis n’est pas configurée."},
        ) from error
    except ConversationStoreError as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "redis_unavailable", "message": "La conversation n’a pas pu être créée."},
        ) from error


@app.get("/api/conversations/{conversation_id}", response_model=ConversationResponse)
def get_conversation(conversation_id: UUID):
    try:
        record = get_conversation_store().get(conversation_id)
    except ConversationStoreConfigurationError as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "redis_not_configured", "message": "La sauvegarde Redis n’est pas configurée."},
        ) from error
    except ConversationStoreError as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "redis_unavailable", "message": "La conversation n’a pas pu être chargée."},
        ) from error
    if record is None:
        raise HTTPException(status_code=404, detail={"code": "conversation_expired", "message": "Cette conversation a expiré ou a été supprimée."})
    return record


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: UUID):
    try:
        get_conversation_store().delete(conversation_id)
    except ConversationStoreConfigurationError as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "redis_not_configured", "message": "La sauvegarde Redis n’est pas configurée."},
        ) from error
    except ConversationStoreError as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "redis_unavailable", "message": "La conversation n’a pas pu être supprimée."},
        ) from error
    return {"deleted": True}


@app.post("/api/resources", response_model=ResourceUploadResponse)
async def upload_resources(
    resource_session: UUID = Form(...),
    level: Literal["CP", "CE1", "CE2", "CM1", "CM2", "6ème"] = Form(...),
    subject: Literal["Mathématiques", "Arabe", "Français"] = Form(...),
    files: list[UploadFile] = File(...),
):
    if not files or len(files) > 5:
        raise HTTPException(
            status_code=422,
            detail="Choisissez entre un et cinq documents.",
        )

    try:
        service = get_rag_service()
    except RagConfigurationError as error:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "rag_not_configured",
                "message": "Le service documentaire n’est pas encore configuré.",
            },
        ) from error
    except RagProviderError as error:
        raise HTTPException(
            status_code=502,
            detail={"code": "rag_provider_error", "message": str(error)},
        ) from error

    total_bytes = 0
    records = []
    resources = []
    try:
        for upload in files:
            content = await upload.read(MAX_RESOURCE_UPLOAD_BYTES - total_bytes + 1)
            total_bytes += len(content)
            if total_bytes > MAX_RESOURCE_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail="La taille totale des fichiers ne doit pas dépasser 4 Mo.",
                )
            filename = (upload.filename or "ressource").replace("\\", "/").rsplit("/", 1)[-1]
            file_records = extract_resource(filename, content, level, subject)
            records.extend(file_records)
            resources.append({"filename": filename, "records": file_records})
    except DocumentExtractionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        for upload in files:
            await upload.close()

    try:
        await run_in_threadpool(
            ingest_records,
            records,
            service,
            namespace=str(resource_session),
        )
    except RagProviderError as error:
        raise HTTPException(
            status_code=502,
            detail={"code": "rag_provider_error", "message": str(error)},
        ) from error
    return {
        "resource_session": resource_session,
        "resources": [
            {
                "filename": resource["filename"],
                "chunks_indexed": sum(
                    len(chunk_text(record["text"]))
                    for record in resource["records"]
                ),
            }
            for resource in resources
        ],
    }


@app.delete("/api/resources/{resource_session}")
def delete_resource_session(resource_session: UUID):
    try:
        service = get_rag_service()
        service.delete_resource_session(str(resource_session))
    except RagConfigurationError as error:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "rag_not_configured",
                "message": "Le service documentaire n’est pas encore configuré.",
            },
        ) from error
    except RagProviderError as error:
        raise HTTPException(
            status_code=502,
            detail={"code": "rag_provider_error", "message": str(error)},
        ) from error
    return {"deleted": True}