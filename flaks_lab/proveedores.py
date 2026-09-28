"""Clientes de OpenAI y Anthropic con errores traducidos al idioma del orquestador."""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from .engines.base import ErrorConfiguracion, ErrorReintentable


def clave(settings: dict, nombre: str, env: str) -> str:
    valor = (settings["claves"].get(nombre) or os.environ.get(env) or "").strip()
    if not valor:
        raise ErrorConfiguracion(f"Falta la clave {env}: cargala en Configuración → Claves")
    return valor


def cliente_openai(settings: dict):
    import openai

    # Los reintentos los maneja el orquestador (espera creciente configurable).
    return openai.OpenAI(api_key=clave(settings, "openai_api_key", "OPENAI_API_KEY"), max_retries=0, timeout=300)


def cliente_anthropic(settings: dict):
    import anthropic

    return anthropic.Anthropic(api_key=clave(settings, "anthropic_api_key", "ANTHROPIC_API_KEY"), max_retries=0,
                               timeout=300)


@contextmanager
def errores_openai() -> Iterator[None]:
    import openai

    try:
        yield
    except (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError,
            openai.InternalServerError, openai.ConflictError) as e:
        raise ErrorReintentable(f"OpenAI: {type(e).__name__}: {e}") from e
    except (openai.AuthenticationError, openai.PermissionDeniedError) as e:
        raise ErrorConfiguracion(f"OpenAI rechazó la clave: {e}") from e
    except openai.NotFoundError as e:
        raise ErrorConfiguracion(f"OpenAI: modelo o recurso inexistente ({e})") from e


@contextmanager
def errores_anthropic() -> Iterator[None]:
    import anthropic

    try:
        yield
    except (anthropic.RateLimitError, anthropic.APITimeoutError, anthropic.APIConnectionError,
            anthropic.InternalServerError, anthropic.ConflictError) as e:
        raise ErrorReintentable(f"Anthropic: {type(e).__name__}: {e}") from e
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
        raise ErrorConfiguracion(f"Anthropic rechazó la clave: {e}") from e
    except anthropic.NotFoundError as e:
        raise ErrorConfiguracion(f"Anthropic: modelo o recurso inexistente ({e})") from e
    except anthropic.APIStatusError as e:
        if e.status_code == 529:  # sobrecargado
            raise ErrorReintentable(f"Anthropic sobrecargado: {e}") from e
        raise
