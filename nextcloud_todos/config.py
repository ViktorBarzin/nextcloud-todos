from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Nextcloud / CalDAV
    nextcloud_base_url: str = "https://nextcloud.viktorbarzin.me"
    nextcloud_user: str = "admin"
    caldav_app_password: str = ""
    webhook_bearer_token: str = ""
    list_allowlist: list[str] = ["Personal"]

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
