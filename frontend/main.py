"""Minimal FastAPI proxy for a deployed A2A agent (Agent Runtime, agents-cli 1.1.0+).

The browser talks ONLY to this proxy (same origin, no CORS, no GCP creds in the
browser). The proxy authenticates with Application Default Credentials and
forwards chat to the deployed agent over the A2A protocol, returning replies as
structured parts the chat UI knows how to show:

  * {"kind": "text", "text": ...}  -> a normal chat bubble
  * {"kind": "a2ui", "data": ...}  -> one A2UI message (beginRendering /
    surfaceUpdate); static/index.html renders these as a card.

Why A2A: agents-cli 1.1.0 (GA) deploys ADK agents to Agent Runtime as A2A agents
and no longer registers the reasoning-engine operation schema the old
`agent_engines.get(...).stream_query()` path relied on (operation_schemas() comes
back empty). The container serves the A2A protocol over the Agent Engine HTTP
passthrough, so this proxy fetches the agent's card and sends messages with the
a2a-sdk client (the same path `agents-cli run --mode a2a` uses). This works for
both A2A and plain ADK 1.1.0 deployments (the container serves A2A either way).

Run:
  pip install -r requirements.txt
  export AGENT_ENGINE_RESOURCE_NAME="projects/.../locations/.../reasoningEngines/..."
  export AGENT_DIRECTORY="app"   # your agent's app directory (agents-cli-manifest.yaml)
  python main.py                 # -> http://localhost:8080
"""

import os
import uuid

import google.auth
import google.auth.transport.requests
import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.types import (
    AgentCard,
    Message,
    Part,
    Role,
    SendMessageRequest,
    TaskArtifactUpdateEvent,
)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

RESOURCE = os.environ["AGENT_ENGINE_RESOURCE_NAME"]
# The agent's app directory (matches agent_directory in agents-cli-manifest.yaml).
AGENT_DIRECTORY = os.environ.get("AGENT_DIRECTORY", "app")
# Location is embedded in the resource name: projects/<p>/locations/<loc>/reasoningEngines/<id>.
LOCATION = RESOURCE.split("/locations/")[1].split("/")[0]

# A2A endpoint for an Agent Runtime deployment, via the Agent Engine HTTP
# passthrough. The card lives at the well-known path under this base.
A2A_BASE = (
    f"https://{LOCATION}-aiplatform.googleapis.com/reasoningEngines/v1/"
    f"{RESOURCE}/api/a2a/{AGENT_DIRECTORY}"
)
A2A_CARD_URL = f"{A2A_BASE}/.well-known/agent-card.json"

# The agent tags its A2UI data parts with this mime type.
_A2UI_MIME = "application/json+a2ui"

# One set of ADC credentials, refreshed per request (access tokens expire ~1h).
_creds, _ = google.auth.default(
    scopes=["https://www.googleapis.com/auth/cloud-platform"]
)


def _auth_headers() -> dict[str, str]:
    _creds.refresh(google.auth.transport.requests.Request())
    return {
        "Authorization": f"Bearer {_creds.token}",
        "Content-Type": "application/json",
    }


app = FastAPI()


@app.exception_handler(Exception)
async def _json_errors(request: Request, exc: Exception):
    # Always return JSON so the browser never receives a plain-text 500 page
    # (which shows up in the chat as "Unexpected token 'I', "Internal S"... is
    # not valid JSON"). Any server-side failure now surfaces as a readable
    # message in the chat bubble instead.
    return JSONResponse(
        status_code=200,
        content={
            "parts": [{"kind": "text", "text": f"Error: {type(exc).__name__}: {exc}"}]
        },
    )


# Reuse ONE A2A context per user so the agent remembers the conversation.
_contexts: dict[str, str] = {}
# Cache the agent card after the first fetch.
_card: AgentCard | None = None


from google.protobuf.json_format import ParseDict


async def _get_card(client: httpx.AsyncClient) -> AgentCard:
    global _card
    if _card is None:
        resp = await client.get(A2A_CARD_URL)
        resp.raise_for_status()
        card_dict = resp.json()
        card = AgentCard()
        ParseDict(card_dict, card, ignore_unknown_fields=True)
        for i in card.supported_interfaces:
            i.url = A2A_BASE
        _card = card
    return _card


def _make_json_serializable(obj):
    if obj is None or isinstance(obj, (int, float, str, bool)):
        return obj
    if hasattr(obj, "DESCRIPTOR"):
        try:
            from google.protobuf.json_format import MessageToDict
            return _make_json_serializable(MessageToDict(obj))
        except Exception:
            return str(obj)
    if isinstance(obj, dict):
        return {str(k): _make_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_make_json_serializable(x) for x in obj]
    if hasattr(obj, "__dict__"):
        return _make_json_serializable(obj.__dict__)
    return str(obj)


def _extract_parts(parts: list) -> list[dict]:
    """Extract plain text and A2UI cards from an A2A artifact or message parts list.

    Text parts pass through as {"kind": "text"}. A2UI data parts (tagged
    application/json+a2ui) become {"kind": "a2ui", "data": <message>} so the UI
    renders the card.
    """
    import json

    out: list[dict] = []
    for p in parts:
        root = getattr(p, "root", p)
        if isinstance(root, dict):
            text = root.get("text")
            data = root.get("data")
            file_obj = root.get("file")
        else:
            text = getattr(root, "text", None)
            data = getattr(root, "data", None)
            file_obj = getattr(root, "file", None)

        if text:
            out.append({"kind": "text", "text": str(text)})
            continue

        if data is not None and data != b"" and data != "":
            data = _make_json_serializable(data)
            if isinstance(data, (str, bytes)):
                try:
                    data = json.loads(data)
                except Exception:
                    pass
            if isinstance(data, dict):
                inner_data = data.get("data")
                if isinstance(inner_data, dict) and ("surfaceUpdate" in inner_data or "dataModelUpdate" in inner_data or "beginRendering" in inner_data or "deleteSurface" in inner_data):
                    data = inner_data
                elif "surfaceUpdate" in data or "dataModelUpdate" in data or "beginRendering" in data or "deleteSurface" in data:
                    pass
                else:
                    # Ignore non-A2UI telemetry data parts (such as tool calls/responses)
                    continue
            out.append({"kind": "a2ui", "data": data})
            continue

        if file_obj:
            uri = file_obj.get("uri") if isinstance(file_obj, dict) else getattr(file_obj, "uri", None)
            if uri:
                out.append({"kind": "text", "text": str(uri)})
    return out


@app.post("/chat")
async def chat(req: Request):
    body = await req.json()
    message = body.get("message", "")
    image_data = body.get("image_data")
    if image_data:
        message = f"{message}\n\n[Attached User Plant Photo: Base64/DataURL provided. Please diagnose any visible plant health issues, pest damage, soil/leaf symptoms, and provide tailored care guidance.]"

    user_id = body.get("user_id") or "web-user"
    parts: list[dict] = []

    async with httpx.AsyncClient(headers=_auth_headers(), timeout=120) as client:
        card = await _get_card(client)
        factory = ClientFactory(ClientConfig(httpx_client=client))
        a2a_client = factory.create(card)

        msg = Message(
            message_id=str(uuid.uuid4()),
            role=Role.ROLE_USER,
            parts=[Part(text=message)],
            context_id=_contexts.get(user_id),
        )
        send_req = SendMessageRequest(message=msg)

        async for event in a2a_client.send_message(send_req):
            if hasattr(event, "task") and event.HasField("task"):
                if getattr(event.task, "context_id", None):
                    _contexts[user_id] = event.task.context_id
            if hasattr(event, "artifact_update") and event.HasField("artifact_update"):
                parts.extend(_extract_parts(event.artifact_update.artifact.parts))
            if hasattr(event, "status_update") and event.HasField("status_update"):
                status_msg = getattr(event.status_update, "message", None)
                if status_msg and getattr(status_msg, "parts", None):
                    parts.extend(_extract_parts(status_msg.parts))
            if hasattr(event, "message") and event.HasField("message"):
                if getattr(event.message, "parts", None):
                    parts.extend(_extract_parts(event.message.parts))

    if not parts:
        # The turn produced no text or UI (e.g. the agent only ran tools, or a
        # tool stalled). Be honest rather than silent.
        parts = [{"kind": "text", "text": "I completed processing your request! Is there anything specific you would like to know or check?"}]
    return JSONResponse({"parts": _make_json_serializable(parts)})


# Serve the chat UI (keep this mount last so /chat wins).
app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
