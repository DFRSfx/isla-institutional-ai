from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LoginRequest(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=255)
    email: str | None = Field(default=None, min_length=1, max_length=255)
    password: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_identifier(self) -> "LoginRequest":
        ident = (self.username or self.email or "").strip()
        if not ident:
            raise ValueError("Indique 'username' ou 'email'.")
        self.username = ident
        return self


class UserProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    researcher_id: UUID | None = None
    permissions: list[str] = Field(default_factory=list)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserProfileResponse


class PortalSyncRequest(BaseModel):
    nocache: bool = False


class SourceSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_type: str
    source_version: str | None
    endpoint_or_filename: str
    content_hash: str
    record_count: int
    records_created: int
    records_updated: int
    records_unchanged: int
    records_removed: int
    cache_ttl_minutes: int | None
    forced_nocache: bool
    diff_summary: dict[str, Any]
    synced_at: datetime


class ExcelImportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    file_sha256: str
    sheet_names: list[str]
    selected_sheet: str
    detected_headers: list[str]
    total_rows: int
    imported_rows: int
    created_rows: int
    updated_rows: int
    duplicate_count: int
    warning_count: int
    error_count: int
    warnings: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    status: str
    snapshot_id: UUID | None
    imported_at: datetime


class ResearcherResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ciencia_vitae_id: str | None
    ciencia_vitae_id_secondary: str | None
    name: str
    email: str | None = None
    school_code: str | None = None
    affiliation: str | None
    training_area: str | None
    degree_code: str | None
    status_code: str | None
    category: str | None
    google_scholar_id: str | None
    scholar_h_index: int | None
    scopus_author_id: str | None
    scopus_h_index: int | None
    wos_researcher_id: str | None
    wos_h_index: int | None
    data_quality_flags: list[str]


class PublicationAuthorResponse(BaseModel):
    author_order: int
    researcher_id: UUID | None
    raw_ciencia_vitae_id: str | None
    raw_name: str | None
    raw_email: str | None = None
    raw_school: str | None
    raw_affiliation: str | None
    match_method: str
    match_confidence: str
    needs_review: bool


class PublicationResponse(BaseModel):
    id: UUID
    portal_id: str
    doi: str | None
    doi_url: str | None
    title: str
    year: int | None
    pub_type: str | None
    status: str | None
    journal_name: str | None
    conference_name: str | None
    venue_name: str | None
    venue_type: str | None
    publisher: str | None
    quartile: str | None
    is_indexed_scopus: bool
    is_indexed_wos: bool
    indexed_in: str | None
    citations_count: int
    references_count: int
    is_open_access: bool
    oa_status: str | None
    oa_url: str | None
    keywords: list[str]
    apa_citation: str | None
    schools_raw: list[str]
    internal_notes: str | None = None
    evaluation_score: str | None = None
    authors: list[PublicationAuthorResponse] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: UUID | None = None


class ReportBundleResponse(BaseModel):
    report_id: str
    title: str
    reproducibility_id: str
    pdf_url: str
    excel_url: str
    pdf_size_bytes: int
    excel_size_bytes: int


class ChatResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID
    answer: str
    needs_clarification: bool
    plan: list[str]
    tool_calls: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    report_bundle: ReportBundleResponse | None = None
    analytics_summary: dict[str, Any] | None = None


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: str
    content: str
    sources_json: list[dict[str, Any]]
    tool_calls_json: list[dict[str, Any]]
    created_at: datetime


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID | None
    user_role: str | None
    action: str
    resource_type: str
    resource_id: str | None
    status: str
    details: dict[str, Any]
    ip_address: str | None = None
    created_at: datetime
