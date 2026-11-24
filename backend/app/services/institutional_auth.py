from dataclasses import dataclass

import httpx

from app.core.config import Settings, get_settings
from app.core.permissions import UserRole


class InstitutionalAuthError(RuntimeError):
    """Erro de comunicação ou configuração da API de autenticação institucional."""


class InstitutionalAuthUnauthorized(RuntimeError):
    """Credenciais rejeitadas pela API de autenticação institucional."""


class InstitutionalAuthForbiddenRole(RuntimeError):
    """Perfil institucional sem acesso autorizado ao agente."""


@dataclass(frozen=True)
class InstitutionalIdentity:
    username: str
    display_name: str
    email: str
    external_role: str | None
    mapped_role: UserRole


def map_external_role(
    external_role: str | None,
    *,
    allow_students: bool = False,
) -> UserRole:
    normalized = (external_role or "").strip().lower()
    if normalized == "admin":
        return UserRole.ADMIN
    if normalized in {"direction", "direcao"}:
        return UserRole.DIRECTION
    if normalized in {"teacher", "faculty", "docente"}:
        return UserRole.FACULTY
    if normalized == "student":
        if allow_students:
            return UserRole.FACULTY
        raise InstitutionalAuthForbiddenRole(
            "Acesso reservado a docentes, direção e administradores do ISLA."
        )
    # Fallback conservador caso /v1/auth seja usado sem claim de role
    return UserRole.FACULTY


class InstitutionalAuthClient:
    """
    Cliente backend-only para a API de autenticação institucional (`https://auth.dariosoares.dev`).
    O cabeçalho `X-API-Key` nunca é exposto ao navegador nem incluído em logs.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._external_client = http_client

    @property
    def is_configured(self) -> bool:
        return bool(self.settings.institutional_auth_api_key.strip())

    def authenticate(self, username: str, password: str) -> InstitutionalIdentity:
        if not self.is_configured:
            raise InstitutionalAuthError("INSTITUTIONAL_AUTH_API_KEY não está configurada.")

        base = self.settings.institutional_auth_base_url.rstrip("/")
        url = f"{base}/v1/token"
        headers = {
            "X-API-Key": self.settings.institutional_auth_api_key,
            "Origin": self.settings.institutional_auth_origin,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            if self._external_client is not None:
                response = self._external_client.post(
                    url,
                    headers=headers,
                    json={"username": username, "password": password},
                )
            else:
                with httpx.Client(timeout=self.settings.institutional_auth_timeout_seconds) as client:
                    response = client.post(
                        url,
                        headers=headers,
                        json={"username": username, "password": password},
                    )
        except httpx.HTTPError as exc:
            raise InstitutionalAuthError(
                f"Falha ao contactar o serviço de autenticação institucional: {exc}"
            ) from exc

        if response.status_code in {401, 403}:
            raise InstitutionalAuthUnauthorized("Credenciais institucionais inválidas.")
        if response.status_code == 429:
            raise InstitutionalAuthError(
                "Limite de tentativas excedido no serviço de autenticação institucional."
            )
        if response.status_code >= 400:
            raise InstitutionalAuthError(
                f"Serviço de autenticação institucional devolveu HTTP {response.status_code}."
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise InstitutionalAuthError(
                "Resposta inválida do serviço de autenticação institucional."
            ) from exc

        if not payload.get("success") or not isinstance(payload.get("user"), dict):
            raise InstitutionalAuthUnauthorized("Credenciais institucionais inválidas.")

        user_data = payload["user"]
        ext_username = str(user_data.get("username") or username).strip()
        display_name = str(user_data.get("displayName") or ext_username).strip()
        email = str(user_data.get("email") or "").strip().lower()
        if not email:
            raise InstitutionalAuthError(
                "O serviço de autenticação institucional não devolveu email do utilizador."
            )

        external_role = payload.get("role")
        mapped_role = map_external_role(
            str(external_role) if external_role is not None else None,
            allow_students=self.settings.institutional_auth_allow_students,
        )

        return InstitutionalIdentity(
            username=ext_username,
            display_name=display_name,
            email=email,
            external_role=str(external_role) if external_role is not None else None,
            mapped_role=mapped_role,
        )
