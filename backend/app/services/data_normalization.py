import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.researcher import Researcher
from app.models.school import School

CIENCIA_VITAE_REGEX = re.compile(r"^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$")
QUARTILE_REGEX = re.compile(r"\b(Q[1-4])\b", re.IGNORECASE)

KNOWN_SCHOOL_NAMES: dict[str, str] = {
    "EST": "Escola Superior de Tecnologia",
    "ESG": "Escola Superior de Gestão",
}


def clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value.strip().lower())
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", ascii_only).strip()


def normalize_alnum(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", normalize_text(value))


def normalize_email(value: Any) -> str | None:
    raw = clean_str(value)
    if not raw:
        return None
    lowered = raw.lower()
    if "@" not in lowered or "." not in lowered.split("@")[-1]:
        return None
    return lowered


def normalize_ciencia_vitae_id(value: Any) -> tuple[str | None, list[str]]:
    """
    Valida e normaliza um identificador Ciência Vitae (XXXX-XXXX-XXXX).
    Nunca silencia erros de formatação: devolve uma lista de avisos quando
    deteta pontuação extra (ex.: '9819-8A14-5151)') ou formato inválido.
    """
    raw = clean_str(value)
    if not raw:
        return None, []

    upper = raw.upper()
    if CIENCIA_VITAE_REGEX.fullmatch(upper):
        return upper, []

    # Caso real encontrado no Excel da intranet: parêntese ou pontuação extra
    sanitized = upper.strip("()[]{}.,;: \t\r\n")
    if CIENCIA_VITAE_REGEX.fullmatch(sanitized):
        return sanitized, [f"malformed_ciencia_vitae_sanitized:{raw}->{sanitized}"]

    return None, [f"invalid_ciencia_vitae_format:{raw}"]


def normalize_doi(value: Any) -> str | None:
    raw = clean_str(value)
    if not raw:
        return None
    cleaned = re.sub(r"^https?://(dx\.)?doi\.org/", "", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"^doi:\s*", "", cleaned, flags=re.IGNORECASE).strip().lower()
    if len(cleaned) >= 5 and cleaned.startswith("10."):
        return cleaned
    return None


def normalize_quartile(value: Any) -> str | None:
    raw = clean_str(value)
    if not raw:
        return None
    match = QUARTILE_REGEX.search(raw)
    if match:
        return match.group(1).upper()
    return raw.upper()


def parse_optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    text = clean_str(value)
    if not text:
        return None
    try:
        if "." in text:
            fval = float(text)
            return int(fval) if fval.is_integer() else None
        return int(text)
    except ValueError:
        return None


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = (clean_str(value) or "").lower()
    return text in {"1", "true", "yes", "sim", "y"}


def split_portal_multivalue(
    value: Any,
    delimiters: tuple[str, ...] = (";#", "; ", ";"),
) -> list[str]:
    """
    Divide campos multivalor da API do Portal Científico respeitando
    os delimitadores reais usados em PowerBiApiController.php:
    ';#' (Ciência ID, Email, Escola), '; ' (Nome, Afiliação) e ';' (authors).
    """
    raw = clean_str(value)
    if not raw:
        return []

    for delim in delimiters:
        if delim in raw:
            parts = [p.strip() for p in raw.split(delim)]
            return [p for p in parts if p]
    return [raw]


def compute_canonical_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def resolve_school(db: Session, school_code: str | None) -> School | None:
    cleaned = clean_str(school_code)
    if not cleaned:
        return None
    code = cleaned.upper()
    school = db.scalar(select(School).where(School.code == code))
    if school:
        return school
    school = School(code=code, name=KNOWN_SCHOOL_NAMES.get(code, code))
    db.add(school)
    db.flush()
    return school


class ResearcherMatcher:
    """
    Resolve autores de publicações para docentes da intranet seguindo
    estritamente a política da especificação:
    1) Ciência Vitae ID (exato e inequívoco)
    2) Email institucional (exato)
    3) Nome normalizado -> APENAS hipótese (`needs_validation`), nunca associação automática.
    """

    def __init__(self, researchers: Iterable[Researcher]) -> None:
        self.by_cv: dict[str, list[Researcher]] = {}
        self.by_email: dict[str, Researcher] = {}
        self.by_name: dict[str, list[Researcher]] = {}

        for r in researchers:
            if r.ciencia_vitae_id:
                self.by_cv.setdefault(r.ciencia_vitae_id.upper(), []).append(r)
            if r.email:
                self.by_email[r.email.lower()] = r
            if r.normalized_name:
                self.by_name.setdefault(r.normalized_name, []).append(r)

    def match(
        self,
        *,
        ciencia_vitae_id: str | None,
        email: str | None,
        name: str | None,
    ) -> tuple[Researcher | None, str, str, bool]:
        cv_clean, _ = normalize_ciencia_vitae_id(ciencia_vitae_id)
        email_clean = normalize_email(email)
        name_norm = normalize_text(name)

        if cv_clean and cv_clean in self.by_cv:
            candidates = self.by_cv[cv_clean]
            if len(candidates) == 1:
                return candidates[0], "ciencia_vitae_id", "exact", False
            # Se houver duplicado de CV ID na intranet, desambiguar por email
            if email_clean:
                for cand in candidates:
                    if cand.email and cand.email.lower() == email_clean:
                        return cand, "ciencia_vitae_id", "exact", True
            # Ambíguo: não associar automaticamente sem validação
            return None, "ciencia_vitae_id", "needs_validation", True

        if email_clean and email_clean in self.by_email:
            return self.by_email[email_clean], "institutional_email", "exact", False

        if name_norm and name_norm in self.by_name:
            # Regra explícita da secção 4: correspondência só pelo nome
            # é hipótese que exige validação, nunca associação automática definitiva.
            return None, "name_hypothesis", "needs_validation", True

        return None, "unmatched", "unmatched", False
