"""Nastavení chatbota. Všechno z proměnných prostředí, klíče nikdy v kódu ani v logu."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".agent-state"


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # Klíč se čte jen ze serverového prostředí (.env není v gitu).
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    dataset_db: Path = STATE / "validator.sqlite"      # čte se jen v režimu read-only
    chatbot_db: Path = STATE / "chatbot.sqlite"        # limity a ad hoc požadavky
    allowed_origins: tuple[str, ...] = ()
    trust_proxy: bool = False
    # Limity (útok na peněženku)
    max_message_chars: int = 500
    max_history_turns: int = 6
    max_tool_rounds: int = 4
    max_output_tokens: int = 1024
    per_client_per_minute: int = 6
    per_client_per_day: int = 60
    llm_calls_per_day: int = 300          # globální strop volání Gemini
    adhoc_per_question: int = 1
    adhoc_per_client_per_day: int = 3
    adhoc_per_day: int = 20               # globální strop ad hoc hledání (Exa)
    salt: str = field(default="", repr=False)

    @classmethod
    def from_env(cls) -> "Settings":
        origins = tuple(o.strip() for o in os.getenv("CHAT_ALLOWED_ORIGINS", "").split(",") if o.strip())
        return cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
            gemini_model=os.getenv("GEMINI_MODEL", cls.gemini_model),
            dataset_db=Path(os.getenv("CHAT_DATASET_DB", str(cls.dataset_db))),
            chatbot_db=Path(os.getenv("CHAT_STATE_DB", str(cls.chatbot_db))),
            allowed_origins=origins,
            trust_proxy=os.getenv("CHAT_TRUST_PROXY") == "1",
            per_client_per_minute=_int("CHAT_PER_CLIENT_PER_MINUTE", cls.per_client_per_minute),
            per_client_per_day=_int("CHAT_PER_CLIENT_PER_DAY", cls.per_client_per_day),
            llm_calls_per_day=_int("CHAT_LLM_CALLS_PER_DAY", cls.llm_calls_per_day),
            adhoc_per_day=_int("CHAT_ADHOC_PER_DAY", cls.adhoc_per_day),
            salt=os.getenv("CHAT_CLIENT_SALT", ""),
        )
