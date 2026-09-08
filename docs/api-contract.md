# Provisional Samvev API contract

Status: **v0.1 draft**. This describes the adapter's current boundary, not a final
Samvev Core API. All endpoints are relative to the configured base URL, including any
deployment path.

## Common behavior

- Prefix: `/api/v1`
- Encoding: JSON request and response objects
- Authentication: `Authorization: Bearer <API token>` on every request
- Success: any 2xx status with the documented JSON object
- Authentication failure: 401 or 403
- Other non-2xx status: connection/API failure; response bodies are not copied into
  HA errors or logs
- Client timeout: 10 seconds per request

Unknown response keys are ignored for forward compatibility. Required values and
provided optional values are type-checked. The API token must never appear in an
error response or application log.

## Health

`GET /api/v1/health`

```json
{
  "status": "ok",
  "instance_id": "stable-server-id",
  "name": "Optional display name"
}
```

`status` is required and is currently `ok` or `healthy`. `instance_id` and `name` are
optional strings. A stable, non-secret `instance_id` is strongly recommended; the
config flow uses it to prevent duplicate entries. Otherwise the normalized base URL
is the identity.

Health should be cheap and must not trigger AI work.

## Context projection

`GET /api/v1/context`

```json
{
  "status": "connected",
  "attention_count": 1,
  "next_attention": {
    "id": "attention-123",
    "summary": "Bring the required equipment",
    "due_at": "2026-09-09T08:00:00Z",
    "kind": "reminder"
  }
}
```

All top-level fields are optional. `attention_count` is a non-negative integer or
null. `next_attention` is an object or null; when present, `summary` is required and
the other fields are optional strings. The adapter truncates summaries longer than
255 characters only in the HA state string and retains the full summary as an entity
attribute.

This is a read model computed and stored by Core. Reading it must not invoke an LLM
or redo schedule/rule processing. For early server implementations only, 404 means
the projection capability is absent and yields connected/unknown adapter state.

## Ask

`POST /api/v1/ask`

Request:

```json
{
  "prompt": "What needs attention tomorrow?",
  "context": {"channel": "home"}
}
```

`prompt` is a non-empty string. `context` is optional and caller-controlled.

Response:

```json
{
  "answer": "One item needs attention.",
  "request_id": "request-123",
  "data": {"attention_count": 1}
}
```

`answer` is required. `request_id` and object `data` are optional. The HA action
requires response data and returns these values to the caller.

## Event

`POST /api/v1/events`

Request without entity context:

```json
{
  "type": "household.context_changed",
  "data": {"reason": "automation"},
  "source": "home_assistant"
}
```

If the action explicitly selected entities, an additional context object is sent:

```json
{
  "type": "household.context_changed",
  "data": {},
  "source": "home_assistant",
  "context": {
    "entities": [
      {
        "entity_id": "weather.home",
        "state": "rainy",
        "last_changed": "2026-09-08T12:00:00+00:00"
      }
    ]
  }
}
```

The adapter never adds attributes or unselected entities. `type` is a non-empty
generic string; naming/versioning conventions remain a Core decision. `data` is an
object.

Response:

```json
{
  "accepted": true,
  "event_id": "event-123"
}
```

`accepted` is required and boolean. `event_id` is optional. `accepted: false` becomes
a visible HA action error.

## Expected evolution

A capability/version document, explicit error envelope, idempotency semantics,
reauthentication hints, inbound Core-to-adapter events, and richer deliberately
selected context may be added later. Those changes should be implemented first at
this client boundary and must preserve data minimization.

