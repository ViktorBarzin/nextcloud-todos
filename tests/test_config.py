from nextcloud_todos.config import Settings


def test_defaults(monkeypatch):
    monkeypatch.setenv("WEBHOOK_BEARER_TOKEN", "x")
    monkeypatch.setenv("HMAC_SECRET", "y")
    monkeypatch.setenv("CALDAV_APP_PASSWORD", "z")
    s = Settings()
    assert s.nextcloud_user == "admin"
    assert s.list_allowlist == ["Personal"]
    assert s.llama_swap_model == "qwen3-8b"
    assert s.research_soft_cap_usd == 20.0
    assert s.exec_budget_usd == 50.0


def test_list_allowlist_parses_csv_env(monkeypatch):
    monkeypatch.setenv("LIST_ALLOWLIST", "Personal")
    assert Settings().list_allowlist == ["Personal"]


def test_list_allowlist_parses_multiple(monkeypatch):
    monkeypatch.setenv("LIST_ALLOWLIST", "Personal, Work Todo ,Goals 2026")
    assert Settings().list_allowlist == ["Personal", "Work Todo", "Goals 2026"]


def test_ideation_allowlist_default_empty(monkeypatch):
    monkeypatch.delenv("IDEATION_ALLOWLIST", raising=False)
    s = Settings()
    assert s.ideation_allowlist == []
    assert s.ideation_budget_usd == 3.0


def test_ideation_allowlist_parses_csv_env(monkeypatch):
    monkeypatch.setenv("IDEATION_ALLOWLIST", "Noticing File, Date Ideas")
    assert Settings().ideation_allowlist == ["Noticing File", "Date Ideas"]
