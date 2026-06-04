from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Nextcloud / CalDAV
    nextcloud_base_url: str = "https://nextcloud.viktorbarzin.me"
    nextcloud_user: str = "admin"
    caldav_app_password: str = ""
    webhook_bearer_token: str = ""
    list_allowlist: Annotated[list[str], NoDecode] = ["Personal"]

    # local classifier
    llama_swap_url: str = "http://llama-swap.llama-cpp.svc.cluster.local:8080"
    llama_swap_model: str = "qwen3-8b"

    # claude-agent-service
    claude_agent_url: str = "http://claude-agent-service.claude-agent.svc.cluster.local:8080"
    claude_agent_token: str = ""
    planner_agent: str = "nextcloud-todos-planner"
    exec_agent: str = "nextcloud-todos-exec"

    # budgets (USD)
    research_soft_cap_usd: float = 20.0
    plan_budget_usd: float = 5.0
    exec_budget_usd: float = 50.0

    # callbacks
    callback_base_url: str = "https://nextcloud-todos.viktorbarzin.me"
    hmac_secret: str = ""

    # db
    db_connection_string: str = "sqlite+aiosqlite:///:memory:"

    @field_validator("list_allowlist", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        # Accept a comma-separated env string (LIST_ALLOWLIST=Personal,Work) as
        # well as a real list. NoDecode stops pydantic-settings from trying to
        # JSON-decode the env value first (which fails on a bare string).
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
