import uuid

from sqlalchemy import Boolean, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.permissions import UserRole
from app.database.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default=UserRole.FACULTY.value, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    researcher_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("researchers.id", use_alter=True, name="fk_users_researcher_id"),
        nullable=True,
        index=True,
    )

    researcher = relationship("Researcher", foreign_keys=[researcher_id])
    conversations = relationship("Conversation", back_populates="user")
    excel_imports = relationship("ExcelImport", back_populates="importer")
    audit_logs = relationship("AuditLog", back_populates="user")
