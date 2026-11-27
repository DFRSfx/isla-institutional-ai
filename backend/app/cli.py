"""Utilitário CLI para inicializar utilizadores e executar rotinas administrativas/periódicas."""

import argparse

from sqlalchemy import select

import app.models  # noqa: F401
from app.core.permissions import UserRole
from app.core.security import hash_password
from app.database.session import Base, SessionLocal, engine
from app.models.user import User
from app.services.maintenance import cleanup_expired_data
from app.services.portal_api import PortalSyncService
from app.services.semantic_search import index_publication_embeddings


def create_user_cmd(email: str, password: str, full_name: str, role: str) -> None:
    resolved_role = UserRole(role)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.email == email.lower()))
        if existing:
            print(f"Utilizador '{email}' já existe (id={existing.id}, role={existing.role}).")
            return
        user = User(
            email=email.strip().lower(),
            full_name=full_name.strip(),
            password_hash=hash_password(password),
            role=resolved_role.value,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"Utilizador criado com sucesso: id={user.id}, email={user.email}, role={user.role}")


def sync_portal_cmd(nocache: bool) -> None:
    with SessionLocal() as db:
        snapshot = PortalSyncService().sync_publications(db, nocache=nocache)
        print(
            f"Portal sincronizado (versão={snapshot.source_version}): "
            f"{snapshot.record_count} registos "
            f"(+{snapshot.records_created} / ~{snapshot.records_updated} / -{snapshot.records_removed})"
        )


def cleanup_retention_cmd(days: int | None) -> None:
    with SessionLocal() as db:
        res = cleanup_expired_data(db, retention_days=days)
        print(
            f"Limpeza concluída: {res['deleted_conversations']} conversação(ões) e "
            f"{res['deleted_reports']} relatório(s) removidos."
        )


def index_embeddings_cmd(force: bool) -> None:
    with SessionLocal() as db:
        res = index_publication_embeddings(db, force=force)
        print(
            f"Índice semântico ({res['model']}): {res['indexed_publications']}/{res['total_publications']} "
            f"({res['coverage_pct']}%) | +{res['newly_indexed']} novos, {res['skipped_up_to_date']} atualizados."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="CLI ISLA Institutional AI Agent")
    sub = parser.add_subparsers(dest="command", required=True)

    cu = sub.add_parser("create-user", help="Criar utilizador inicial (admin/direction/faculty)")
    cu.add_argument("--email", required=True)
    cu.add_argument("--password", required=True)
    cu.add_argument("--name", required=True)
    cu.add_argument("--role", choices=[r.value for r in UserRole], default=UserRole.ADMIN.value)

    sp = sub.add_parser("sync-portal", help="Sincronizar API do Portal Científico (cron diário)")
    sp.add_argument("--nocache", action="store_true", help="Forçar nocache=1 (apenas admin)")

    cr = sub.add_parser("cleanup-retention", help="Aplicar política de retenção RGPD")
    cr.add_argument("--days", type=int, default=None, help="Sobrescrever CONVERSATION_RETENTION_DAYS")

    ie = sub.add_parser("index-embeddings", help="Indexar embeddings semânticos locais (RAG)")
    ie.add_argument("--force", action="store_true", help="Reindexar todas as publicações")

    args = parser.parse_args()
    if args.command == "create-user":
        create_user_cmd(args.email, args.password, args.name, args.role)
    elif args.command == "sync-portal":
        sync_portal_cmd(args.nocache)
    elif args.command == "cleanup-retention":
        cleanup_retention_cmd(args.days)
    elif args.command == "index-embeddings":
        index_embeddings_cmd(args.force)


if __name__ == "__main__":
    main()
