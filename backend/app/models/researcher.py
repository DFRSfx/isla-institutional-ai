import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Researcher(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "researchers"

    # Não aplicamos UNIQUE em ciencia_vitae_id porque o Excel real contém duplicados
    # que devem ser preservados e sinalizados em data_quality_flags para auditoria.
    ciencia_vitae_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    ciencia_vitae_id_secondary: Mapped[str | None] = mapped_column(String(64), nullable=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)

    school_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("schools.id"),
        nullable=True,
        index=True,
    )
    school_code_raw: Mapped[str | None] = mapped_column(String(64), nullable=True)

    affiliation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    training_area: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Códigos mantidos no formato bruto até confirmação do dicionário de dados institucional
    degree_code: Mapped[str | None] = mapped_column(String(16), index=True, nullable=True)
    status_code: Mapped[str | None] = mapped_column(String(16), index=True, nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)

    google_scholar_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    scholar_h_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scopus_author_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    scopus_h_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wos_researcher_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    wos_h_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    last_import_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("excel_imports.id", use_alter=True, name="fk_researchers_last_import_id"),
        nullable=True,
        index=True,
    )
    data_quality_flags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    school = relationship("School", back_populates="researchers")
    authorships = relationship("PublicationAuthor", back_populates="researcher")
