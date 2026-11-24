from collections.abc import Generator
from io import BytesIO
from typing import Any

import openpyxl
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.permissions import UserRole
from app.core.security import create_access_token, hash_password
from app.database.session import Base, get_db
from app.main import create_app
from app.models.user import User


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    app = create_app()

    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client


def make_user(
    db: Session,
    *,
    email: str,
    role: UserRole,
    full_name: str = "Utilizador Teste",
    password: str = "Segredo123!",
    researcher_id=None,
) -> User:
    user = User(
        email=email,
        full_name=full_name,
        password_hash=hash_password(password),
        role=role.value,
        is_active=True,
        researcher_id=researcher_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role)
    return {"Authorization": f"Bearer {token}"}


def build_synthetic_researchers_xlsx(rows: list[list[Any]] | None = None) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Docentes"
    headers = [
        "CienciaVitae",
        "Docente",
        "Email",
        "Acivo",
        "CienciaVitae2",
        "Grau",
        "Escola",
        "Afiliação",
        "Área Formação",
        "Google scholar",
        "Scopus",
        "scholar h-index",
        "scopus h-index",
        "Web of Science",
        "WoS h-index",
        "Categoria",
    ]
    ws.append(headers)
    default_rows = [
        [
            "AAAA-1111-BBBB",
            "Ana Silva",
            "ana.silva@isla.test",
            "Y",
            "AAAA-1111-BBBB",
            "D",
            "EST",
            "CIDI",
            "Informática",
            "GS_ANA_01",
            "57200000001",
            6,
            4,
            "AAA-1111-2022",
            3,
            "Teacher",
        ],
        [
            "CCCC-2222-DDDD",
            "Bruno Costa",
            "bruno.costa@isla.test",
            "A",
            "CCCC-2222-DDDD)",  # Parêntese extra simulando erro real encontrado no Excel
            "M",
            "ESG",
            "CEOS",
            "Gestão",
            None,
            None,
            None,
            None,
            None,
            None,
            "Teacher",
        ],
        [
            "EEEE-3333-FFFF",
            "Carla Duarte",
            "carla.duarte@isla.test",
            "N",
            "EEEE-3333-9999",  # Divergência entre CienciaVitae e CienciaVitae2
            "L",
            "EST",
            None,
            "Engenharia",
            None,
            None,
            None,
            None,
            None,
            None,
            "Student",
        ],
        [
            "AAAA-1111-BBBB",  # Duplicado intencional de Ciência Vitae
            "Diogo Ferreira",
            "diogo.ferreira@isla.test",
            "O",
            "AAAA-1111-BBBB",
            "N",
            "ESG",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "Teacher",
        ],
    ]
    for r in (rows if rows is not None else default_rows):
        ws.append(r)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
