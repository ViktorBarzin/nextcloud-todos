# 0001 Product events, logs and errors to the shared telemetry standard

Status: accepted (2026-11-10)

Viktor asked for one analytics pipeline across every app he hosts (infra ADR-0041, design
`infra/docs/plans/2026-11-09-product-analytics-design.md`). tv was the pilot; nextcloud-todos
follows the same standard through the shared `viktorbarzin-telemetry` 0.1.0 library.

## Decision

1. Logs. Every line is one JSON object on stdout in the OpenTelemetry field names:
   `timestamp`, `severity_text`, `severity_number`, `body`, `logger.name`, `service.name`
   (`nextcloud-todos`), `service.version` (`APP_VERSION`, the commit's short sha baked in by
   the CI build), `deployment.environment.name`, and `extra={...}` fields as snake_case
   attributes. `python -m nextcloud_todos serve` sets this up before uvicorn starts and gives
   uvicorn no logging config of its own, so its lines use the same handler.

2. The Person id is the Authentik hashed user id (`uid`) of the person whose Nextcloud lists
   are watched. Nobody signs in to this service: the webhook and `/api/*` take a bearer
   token, and `/cb/*` takes HMAC-signed links. So the id comes from configuration,
   `TELEMETRY_PERSON_ID`, set in the infra stack, and every event carries it. Every event
   also carries the fixed anonymousId `nextcloud-todos-owner`; without `TELEMETRY_PERSON_ID`
   that is the only id.

3. Product events go to the Event pipeline with the Write key, only when
   `TELEMETRY_WRITE_KEY` is set and `TELEMETRY_ENVIRONMENT=production`, to `TELEMETRY_HOST`.
   Each is sent where the thing happens:

   | Event | Sent from | Properties | Answers |
   |---|---|---|---|
   | `todo.received` | `process_todo`, for a todo seen for the first time | `lane` (`triage`, `ideation`), `source` (`webhook`, `sweep`) | how many todos arrive, and whether the webhook or the 5-minute sweep found them |
   | `todo.triaged` | `process_todo`, after the classifier | `todo_kind`, `priority`, `outcome` (`dropped`, `answer`, `plan`) | what share of todos is noise, and what kinds of work are asked for |
   | `ideation.finished` | `run_ideation` | `status`, `cost_usd`, `duration_s` | whether ideation works and what it costs |
   | `card.delivered` | `POST /api/events/{id}/consume`, the first time | `kind` (`plan`, `answer`), `wait_s` | how long a card waits before the Telegram side picks it up |
   | `approval.recorded` | the `/cb/approve`, `/cb/reject` and `/cb/refine` links | `decision`, `steered`, `wait_s` | how often plans are approved, rejected or refined, and how long they wait |
   | `execution.finished` | `run_execute`, after an approval | `status`, `steered`, `cost_usd`, `duration_s` | whether approved work succeeds and what it costs |

   No property carries a todo's summary or description, a plan or answer, steering notes or a
   calendar name: all of them are the owner's own words.

4. Errors go to GlitchTip through Sentry, with `SENTRY_DSN` (the in-cluster form) in
   production only.

5. There is no browser front end beyond the `/cb/*` confirmation pages, so no Rybbit script
   is loaded.

## Consequences

- Tests and local runs send nothing: no Write key, and the environment is not `production`.
- If a second person's lists are ever watched, `TELEMETRY_PERSON_ID` has to become per list.
- `python -m nextcloud_todos migrate` (the init container) keeps alembic's own log format.

## Open questions

- Whether a per-request `enduser.id` on log lines is worth adding. Today no line carries one,
  since no request names a Person.
