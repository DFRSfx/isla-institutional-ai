"""Utilitário CLI para inicializar utilizadores e executar operações administrativas."""

import argparse

from sqlalchemy import select

import app.models  # noqa: F401
from app.core.permissions import UserRole
from app.core.security import hash_password
from app.database.session import Base, SessionLocal, engine
from app.models.user import User


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


def main() -> None:
    parser = argparse.ArgumentParser(description="CLI ISLA Institutional AI Agent")
    sub = parser.add_subparsers(dest="command", required=True)

    cu = sub.add_parser("create-user", help="Criar utilizador inicial (admin/direction/faculty)")
    cu.add_argument("--email", required=True)
    cu.add_argument("--password", required=True)
    cu.add_argument("--name", required=True)
    cu.add_argument("--role", choices=[r.value for r in UserRole], default=UserRole.ADMIN.value)

    args = parser.parse_args()
    if args.command == "create-user":
        create_user_cmd(args.email, args.password, args.name, args.role)


if __name__ == "__main__":
    main()
