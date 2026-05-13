import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlmodel import Session, select

from app.api.deps import (
    assert_can_modify_greenhouse,
    get_authorized_greenhouse,
    get_current_user,
    get_db,
)
from app.core.config import settings
from app.core.context import ctx_user
from app.models.chat import (
    ChatMessage,
    ChatMessageRead,
    ChatRole,
    ChatScope,
    ChatSession,
    ChatSessionRead,
    utc_now_naive,
)
from app.models.command import CommandStatus
from app.models.greenhouse import Greenhouse
from app.models.plant import Plant
from app.models.telemetry import Telemetry
from app.models.user import User
from app.services.device_registry import ensure_greenhouse_devices
from app.services.command_service import publish_tracked_command
from app.services.tenant_service import (
    enforce_ai_message_limit,
    ensure_personal_tenant,
    get_greenhouse_tenant,
    get_user_tenant_ids,
    record_usage_event,
    user_can_access_greenhouse,
)
from app.services.plant_conditions import conditions_summary_for_plants

logger = logging.getLogger(__name__)

router = APIRouter()

PLACEHOLDER_API_KEYS = {"", "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"}
READ_ONLY_TOOL_NAMES = {
    "list_greenhouses_api_greenhouses_get",
    "get_greenhouse_api_greenhouses__greenhouse_id__get",
    "list_greenhouse_telemetry_api_greenhouses__greenhouse_id__telemetry_get",
    "get_device_command_api_greenhouses__greenhouse_id__commands__command_id__get",
    "list_devices_api_greenhouses__greenhouse_id__devices_get",
    "get_plant_types_api_greenhouses__greenhouse_id__plants_plant_types_get",
    "list_plants_api_greenhouses__greenhouse_id__plants_get",
    "get_plant_api_greenhouses__greenhouse_id__plants__plant_id__get",
}
CONFIRMABLE_MUTATION_TOOL_NAMES = {
    "switch_mode_ai_control_api_greenhouses__greenhouse_id__ai_switch__state__post",
    "device_switch_on_off_api_greenhouses__greenhouse_id__devices__device_name__switch__device_state__post",
}
CONFIRMATION_TERMS = ("tasdiqlayman", "i confirm")

DEVICE_DISPLAY_NAMES = {
    "soil_water_pump": "suv nasosi",
    "air_water_pump": "havo nasosi",
    "led": "LED chiroq",
    "fan": "ventilyator",
}


@dataclass(frozen=True)
class PendingControlAction:
    target: str
    state: str


class ChatHistoryItem(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatHistoryItem] = Field(default_factory=list)
    session_id: int | None = None


class ChatRequestResponse(BaseModel):
    reply: str
    session_id: int | None = None


def clean_schema(schema: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return schema

    schema = schema.copy()
    for key in ["title", "default", "$schema", "$ref", "$defs", "definitions"]:
        schema.pop(key, None)

    for key in ["anyOf", "oneOf"]:
        if key in schema:
            options = schema.pop(key)
            valid_option = next(
                (
                    option
                    for option in options
                    if isinstance(option, dict) and option.get("type") != "null"
                ),
                options[0] if options else {},
            )
            schema.update(clean_schema(valid_option))

    if "allOf" in schema:
        for sub_schema in schema.pop("allOf"):
            schema.update(clean_schema(sub_schema))

    if isinstance(schema.get("type"), list):
        valid_types = [type_name for type_name in schema["type"] if type_name != "null"]
        schema["type"] = valid_types[0] if valid_types else "string"

    if "properties" in schema:
        for name, prop in schema["properties"].items():
            schema["properties"][name] = clean_schema(prop)

    if "items" in schema:
        schema["items"] = clean_schema(schema["items"])

    return schema


@dataclass
class ParsedToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: f"dsml_{uuid.uuid4().hex[:8]}")


_DSML_MARKER = "\uff5cDSML\uff5c"


def parse_dsml_tool_calls(content: str) -> tuple[str, list[ParsedToolCall]]:
    """Parse DSML-formatted tool calls that Deepseek sometimes emits as text.

    Returns the text before the DSML block and a list of parsed tool calls.
    """
    if _DSML_MARKER not in content:
        return content, []

    # Extract text before the DSML block
    dsml_start = content.find(f"<{_DSML_MARKER}")
    prefix_text = content[:dsml_start].strip() if dsml_start > 0 else ""

    tool_calls: list[ParsedToolCall] = []

    invoke_pattern = re.compile(
        r'<[^>]*DSML[^>]*invoke\s+name="([^"]+)"[^>]*>(.*?)</[^>]*invoke>',
        re.DOTALL,
    )
    arg_pattern = re.compile(
        r'<[^>]*DSML[^>]*arg\s+name="([^"]+)"[^>]*>(.*?)</[^>]*arg>',
        re.DOTALL,
    )

    for invoke_match in invoke_pattern.finditer(content):
        tool_name = invoke_match.group(1)
        invoke_body = invoke_match.group(2)
        args: dict[str, Any] = {}
        for arg_match in arg_pattern.finditer(invoke_body):
            arg_name = arg_match.group(1)
            arg_value = arg_match.group(2).strip()
            # Convert to appropriate types
            if arg_value.lower() == "true":
                args[arg_name] = True
            elif arg_value.lower() == "false":
                args[arg_name] = False
            elif arg_value.isdigit():
                args[arg_name] = int(arg_value)
            else:
                try:
                    args[arg_name] = float(arg_value)
                except ValueError:
                    args[arg_name] = arg_value
        tool_calls.append(ParsedToolCall(name=tool_name, arguments=args))

    if tool_calls:
        logger.info("Parsed %d DSML tool call(s) from response content", len(tool_calls))

    return prefix_text, tool_calls


def mutation_confirmation_present(message: str) -> bool:
    normalized_message = message.casefold()
    return any(term in normalized_message for term in CONFIRMATION_TERMS)


def detect_requested_state(message: str) -> str | None:
    normalized = message.casefold()
    if any(
        term in normalized
        for term in (
            "o'chir",
            "o‘chir",
            "ochir",
            "off",
            "to'xta",
            "to‘xta",
            "stop",
            "выключ",
        )
    ):
        return "off"
    if any(
        term in normalized
        for term in (
            "yoq",
            "yondir",
            "on",
            "ishlat",
            "enable",
            "включ",
            "och",
            "yoqib",
        )
    ):
        return "on"
    return None


def detect_control_action(message: str) -> PendingControlAction | None:
    state = detect_requested_state(message)
    if state is None:
        return None

    normalized = message.casefold()

    if "ai" in normalized and any(
        term in normalized for term in ("mode", "rejim", "режим")
    ):
        return PendingControlAction(target="ai_mode", state=state)

    if any(term in normalized for term in ("vent", "fan", "shamollat", "вент")):
        return PendingControlAction(target="fan", state=state)

    if any(term in normalized for term in ("led", "chiroq", "lamp", "light", "свет")):
        return PendingControlAction(target="led", state=state)

    if any(term in normalized for term in ("havo nasos", "air pump", "aerat", "аэра")):
        return PendingControlAction(target="air_water_pump", state=state)

    if any(
        term in normalized
        for term in (
            "suv",
            "soil pump",
            "soil_water",
            "tuproq",
            "sugor",
            "sug'or",
            "sug‘or",
            "насос",
            "nasos",
            "pump",
        )
    ):
        return PendingControlAction(target="soil_water_pump", state=state)

    return None


def latest_pending_control_action(
    history: list[ChatHistoryItem] | None,
) -> PendingControlAction | None:
    if not history:
        return None
    for item in reversed(history):
        if item.role == "user":
            action = detect_control_action(item.content)
            if action is not None:
                return action
    return None


def control_action_label(action: PendingControlAction) -> str:
    if action.target == "ai_mode":
        return "AI rejimi"
    return DEVICE_DISPLAY_NAMES.get(action.target, action.target)


def build_control_confirmation_reply(action: PendingControlAction) -> str:
    state_label = "yoqish" if action.state == "on" else "o'chirish"
    return (
        f"Siz {control_action_label(action)}ni {state_label}ni so'radingiz.\n\n"
        "Buni amalga oshirish uchun tasdiqlashingiz kerak. "
        'Iltimos, **"tasdiqlayman"** yoki **"i confirm"** deb yozing.'
    )


def execute_control_action(
    db: Session,
    *,
    greenhouse: Greenhouse,
    current_user: User,
    action: PendingControlAction,
) -> ChatRequestResponse:
    assert_can_modify_greenhouse(db, current_user, greenhouse)

    if action.target == "ai_mode":
        payload = "1" if action.state == "on" else "0"
        mqtt_topic_id = greenhouse.mqtt_topic_id or settings.DEFAULT_MQTT_TOPIC_ID
        command = publish_tracked_command(
            db,
            greenhouse_id=greenhouse.id,
            command_type="ai_mode_switch",
            topic=f"{mqtt_topic_id}/mode/ai",
            payload=payload,
        )
        if command.status == CommandStatus.FAILED:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=command.error or "MQTT broker unavailable",
            )
        greenhouse.ai_mode = action.state == "on"
        db.add(greenhouse)
        db.flush()
        state_label = "yoqish" if action.state == "on" else "o'chirish"
        return ChatRequestResponse(
            reply=(
                f"AI rejimini {state_label} buyrug'i yuborildi. "
                f"Command ID: {command.id}."
            )
        )

    if greenhouse.ai_mode:
        return ChatRequestResponse(
            reply=(
                "Manual qurilma boshqaruvi uchun avval AI rejimini o'chiring. "
                "AI rejimi yoqilgan paytda ESP32 qurilmalarni avtomatik boshqaradi."
            )
        )

    devices = ensure_greenhouse_devices(db, greenhouse)
    device = devices.get(action.target)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )

    payload = "1" if action.state == "on" else "0"
    command = publish_tracked_command(
        db,
        greenhouse_id=greenhouse.id,
        command_type=f"{action.target}_switch",
        topic=f"{device.topic_root}/control",
        payload=payload,
    )
    if command.status == CommandStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=command.error or "MQTT broker unavailable",
        )

    state_label = "yoqish" if action.state == "on" else "o'chirish"
    return ChatRequestResponse(
        reply=(
            f"{control_action_label(action)}ni {state_label} buyrug'i yuborildi. "
            f"Command ID: {command.id}. ESP32 holatni qayta yuborganda dashboard yangilanadi."
        )
    )


def handle_confirmable_control_request(
    db: Session,
    *,
    body: ChatRequest,
    current_user: User,
    greenhouse: Greenhouse | None,
    history: list[ChatHistoryItem] | None,
) -> ChatRequestResponse | None:
    if greenhouse is None:
        return None

    current_action = detect_control_action(body.message)
    if mutation_confirmation_present(body.message):
        action = current_action or latest_pending_control_action(history)
        if action is not None:
            return execute_control_action(
                db,
                greenhouse=greenhouse,
                current_user=current_user,
                action=action,
            )
        return None

    if current_action is not None:
        return ChatRequestResponse(reply=build_control_confirmation_reply(current_action))

    return None


def tool_is_allowed(tool_name: str, allow_mutations: bool = False) -> bool:
    if tool_name in READ_ONLY_TOOL_NAMES:
        return True
    return allow_mutations and tool_name in CONFIRMABLE_MUTATION_TOOL_NAMES


def get_ai_client():
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI chat dependency is missing. Install `openai`.",
        ) from exc

    api_key = settings.DEEPSEEK_API_KEY.strip()
    if api_key in PLACEHOLDER_API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI chat is not configured. Set `DEEPSEEK_API_KEY`.",
        )

    return AsyncOpenAI(api_key=api_key, base_url="https://api.deepseek.com")


def get_mcp_client_class():
    try:
        from fastmcp import Client
    except ImportError:
        return None
    return Client


def latest_telemetry_for_greenhouse(db: Session, greenhouse_id: int) -> Telemetry | None:
    return db.exec(
        select(Telemetry)
        .where(Telemetry.greenhouse_id == greenhouse_id)
        .order_by(Telemetry.time.desc(), Telemetry.id.desc())
    ).first()


def telemetry_to_prompt_payload(telemetry: Telemetry | None) -> dict[str, Any] | None:
    if telemetry is None:
        return None
    return {
        "time": telemetry.time.isoformat() if telemetry.time else None,
        "air": telemetry.air,
        "light": telemetry.light,
        "humidity": telemetry.humidity,
        "temperature": telemetry.temperature,
        "moisture": telemetry.moisture,
        "soil_water_pump": telemetry.soil_water_pump,
        "air_water_pump": telemetry.air_water_pump,
        "led": telemetry.led,
        "fan": telemetry.fan,
        "ai_mode": telemetry.ai_mode,
    }


def greenhouse_prompt_payload(db: Session, greenhouse: Greenhouse) -> dict[str, Any]:
    telemetry = latest_telemetry_for_greenhouse(db, greenhouse.id)
    devices = ensure_greenhouse_devices(db, greenhouse)
    plants = db.exec(
        select(Plant).where(Plant.greenhouse_id == greenhouse.id).limit(20)
    ).all()

    plant_conditions_text = conditions_summary_for_plants(plants)

    payload: dict[str, Any] = {
        "id": greenhouse.id,
        "name": greenhouse.name,
        "mqtt_topic_id": greenhouse.mqtt_topic_id,
        "ai_mode": greenhouse.ai_mode,
        "latest_telemetry": telemetry_to_prompt_payload(telemetry),
        "devices": [
            {
                "name": device.name,
                "type": device.type.value,
                "min_value": device.min_value,
                "max_value": device.max_value,
            }
            for device in devices.values()
        ],
        "plants": [
            {
                "id": plant.id,
                "name": plant.name,
                "type": plant.type.value,
                "variety": plant.variety,
            }
            for plant in plants
        ],
    }
    if plant_conditions_text:
        payload["plant_optimal_conditions"] = plant_conditions_text

    return payload


def accessible_greenhouses_for_user(db: Session, current_user: User) -> list[Greenhouse]:
    tenant_ids = get_user_tenant_ids(db, current_user.id)
    if tenant_ids:
        statement = select(Greenhouse).where(
            or_(
                Greenhouse.owner_id == current_user.id,
                Greenhouse.tenant_id.in_(tenant_ids),
            )
        )
    else:
        statement = select(Greenhouse).where(Greenhouse.owner_id == current_user.id)
    return db.exec(statement.order_by(Greenhouse.id)).all()


def build_global_system_prompt(db: Session, current_user: User) -> str:
    greenhouses = accessible_greenhouses_for_user(db, current_user)
    payload = [greenhouse_prompt_payload(db, greenhouse) for greenhouse in greenhouses[:10]]
    has_plant_conditions = any(p.get("plant_optimal_conditions") for p in payload)
    context_json = json.dumps(payload, ensure_ascii=False, default=str)
    plant_instruction = ""
    if has_plant_conditions:
        plant_instruction = (
            " When plant_optimal_conditions are present, compare current telemetry "
            "against those ranges and warn about deviations."
        )
    return (
        "You are AgroAI, a greenhouse operations assistant. "
        "This is the global assistant view: answer across all greenhouses that "
        "the current user can access. Do not assume greenhouse id 1; ask a short "
        "clarifying question if a control action needs a specific greenhouse. "
        "For device or AI mode changes, ask the user to explicitly confirm with "
        f"'tasdiqlayman' or 'i confirm' before using a control tool.{plant_instruction}\n\n"
        f"Accessible greenhouse context JSON: {context_json}"
    )


def build_scoped_system_prompt(db: Session, greenhouse: Greenhouse) -> str:
    payload = greenhouse_prompt_payload(db, greenhouse)
    context_json = json.dumps(payload, ensure_ascii=False, default=str)
    plant_instruction = ""
    if payload.get("plant_optimal_conditions"):
        plant_instruction = (
            "\n\nIMPORTANT: This greenhouse has plants with known optimal conditions. "
            "When the user asks about plant health, sensor readings, or settings, "
            "compare current telemetry against the plant optimal conditions and "
            "provide specific recommendations. If sensor values are outside optimal "
            "ranges for the planted crops, warn the user and suggest adjustments. "
            "You can suggest device settings changes based on plant requirements."
        )
    return (
        "You are AgroAI, a greenhouse operations assistant. "
        f"This chat is already inside greenhouse id {greenhouse.id} named "
        f"'{greenhouse.name}'. Treat every status question and safe control request "
        "as referring to this greenhouse unless the user explicitly says otherwise. "
        f"Never ask for a greenhouse id in this scoped chat; use greenhouse_id={greenhouse.id} "
        "when a tool requires it. For device or AI mode changes, ask the user to "
        "explicitly confirm with 'tasdiqlayman' or 'i confirm' before using a control "
        f"tool.{plant_instruction}\n\n"
        f"Scoped greenhouse context JSON: {context_json}"
    )


def history_from_session(db: Session, session: ChatSession, limit: int = 20) -> list[ChatHistoryItem]:
    # Senior Level: Limit history to prevent huge context windows and slow queries
    messages = db.exec(
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(limit)
    ).all()
    # Reverse to restore chronological order
    messages.reverse()
    return [
        ChatHistoryItem(
            role=message.role.value if isinstance(message.role, ChatRole) else message.role,
            content=message.content,
        )
        for message in messages
    ]


def build_messages(
    body: ChatRequest,
    *,
    system_prompt: str | None = None,
    persisted_history: list[ChatHistoryItem] | None = None,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": system_prompt
            or (
                "You are a helpful greenhouse assistant. "
                "Do not assume greenhouse id 1 if the user asks for a greenhouse "
                "action without specifying an id. "
                "For device or AI mode changes, ask the user to explicitly confirm "
                "with 'tasdiqlayman' or 'i confirm' before using a control tool."
            ),
        }
    ]

    history = persisted_history if persisted_history is not None else body.history
    for item in history:
        # Only trust conversational turns from the client. System and tool
        # messages must be created by the server during the current request.
        if item.role not in {"user", "assistant"}:
            continue
        messages.append({"role": item.role, "content": item.content})

    messages.append({"role": "user", "content": body.message})
    return messages


def extract_message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = None
            if isinstance(item, dict):
                text = item.get("text")
            else:
                text = getattr(item, "text", None)
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        return "\n".join(parts)
    return ""


def dump_message(message: Any) -> dict[str, Any]:
    if hasattr(message, "model_dump"):
        return message.model_dump(exclude_none=True)
    return {
        "role": "assistant",
        "content": extract_message_text(getattr(message, "content", "")),
    }


def build_tool_definitions(
    mcp_tools: list[Any],
    allow_mutations: bool = False,
    scoped_greenhouse_id: int | None = None,
) -> tuple[list[dict[str, Any]], set[str]]:
    definitions: list[dict[str, Any]] = []
    allowed_tool_names: set[str] = set()
    for tool in mcp_tools:
        if not tool_is_allowed(tool.name, allow_mutations=allow_mutations):
            continue
        if (
            scoped_greenhouse_id is not None
            and tool.name == "list_greenhouses_api_greenhouses_get"
        ):
            continue
        allowed_tool_names.add(tool.name)
        definitions.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": clean_schema(tool.inputSchema.copy() if tool.inputSchema else {}),
                },
            }
        )
    return definitions, allowed_tool_names


def make_chat_title(message: str) -> str:
    title = " ".join(message.strip().split())
    return title[:117] + "..." if len(title) > 120 else title


def resolve_chat_session(
    db: Session,
    *,
    current_user: User,
    body: ChatRequest,
    scope: ChatScope,
    greenhouse_id: int | None,
) -> ChatSession:
    if body.session_id is not None:
        session = db.get(ChatSession, body.session_id)
        if session is None or session.owner_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat session not found",
            )
        if session.scope != scope or session.greenhouse_id != greenhouse_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Chat session scope mismatch",
            )
        return session

    session = ChatSession(
        owner_id=current_user.id,
        greenhouse_id=greenhouse_id,
        scope=scope,
        title=make_chat_title(body.message),
    )
    db.add(session)
    db.flush()
    return session


def persist_chat_turn(
    db: Session, *, session: ChatSession, user_message: str, assistant_reply: str
) -> None:
    now = utc_now_naive()
    session.updated_at = now
    db.add(session)
    db.add(
        ChatMessage(
            session_id=session.id,
            role=ChatRole.USER,
            content=user_message,
            created_at=now,
        )
    )
    db.add(
        ChatMessage(
            session_id=session.id,
            role=ChatRole.ASSISTANT,
            content=assistant_reply,
            created_at=utc_now_naive(),
        )
    )


@router.get("/ai/sessions", response_model=list[ChatSessionRead])
def list_chat_sessions(
    greenhouse_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ChatSessionRead]:
    if greenhouse_id is not None:
        greenhouse = db.get(Greenhouse, greenhouse_id)
        if greenhouse is None or not user_can_access_greenhouse(
            db, current_user.id, greenhouse
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Greenhouse not found",
            )

    statement = select(ChatSession).where(ChatSession.owner_id == current_user.id)
    if greenhouse_id is not None:
        statement = statement.where(ChatSession.greenhouse_id == greenhouse_id)
    statement = statement.order_by(ChatSession.updated_at.desc()).limit(50)
    return [ChatSessionRead.model_validate(session) for session in db.exec(statement).all()]


@router.get("/ai/sessions/{session_id}/messages", response_model=list[ChatMessageRead])
def list_chat_messages(
    session_id: int,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ChatMessageRead]:
    session = db.get(ChatSession, session_id)
    if session is None or session.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found",
        )

    messages = db.exec(
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at, ChatMessage.id)
        .offset(skip)
        .limit(limit)
    ).all()
    return [ChatMessageRead.model_validate(message) for message in messages]


async def run_chat_request(
    *,
    request: Request,
    body: ChatRequest,
    current_user: User,
    db: Session,
    greenhouse: Greenhouse | None = None,
) -> ChatRequestResponse:
    scope = ChatScope.GREENHOUSE if greenhouse is not None else ChatScope.GLOBAL
    greenhouse_id = greenhouse.id if greenhouse is not None else None

    if greenhouse is not None:
        tenant = get_greenhouse_tenant(db, greenhouse, current_user)
        system_prompt = build_scoped_system_prompt(db, greenhouse)
    else:
        tenant = ensure_personal_tenant(db, current_user)
        system_prompt = build_global_system_prompt(db, current_user)

    enforce_ai_message_limit(db, tenant)
    session = resolve_chat_session(
        db,
        current_user=current_user,
        body=body,
        scope=scope,
        greenhouse_id=greenhouse_id,
    )
    persisted_history = history_from_session(db, session) if body.session_id else None

    direct_response = handle_confirmable_control_request(
        db,
        body=body,
        current_user=current_user,
        greenhouse=greenhouse,
        history=persisted_history,
    )
    if direct_response is not None:
        direct_response.session_id = session.id
        persist_chat_turn(
            db,
            session=session,
            user_message=body.message,
            assistant_reply=direct_response.reply,
        )
        record_usage_event(
            db,
            tenant_id=tenant.id,
            user_id=current_user.id,
            event_type="ai_chat_message",
            metadata={"scope": scope.value, "greenhouse_id": greenhouse_id},
        )
        db.commit()
        return direct_response

    llm_client = get_ai_client()
    mcp_instance = getattr(request.app.state, "mcp", None)
    client_class = get_mcp_client_class()
    messages = build_messages(
        body,
        system_prompt=system_prompt,
        persisted_history=persisted_history,
    )
    allow_mutations = mutation_confirmation_present(body.message)
    token = ctx_user.set(current_user)

    try:
        tool_definitions: list[dict[str, Any]] = []
        tool_client = None

        if mcp_instance is not None and client_class is not None:
            tool_client = client_class(mcp_instance)

        if tool_client is not None:
            async with tool_client as active_tool_client:
                mcp_tools = await active_tool_client.list_tools()
                tool_definitions, allowed_tool_names = build_tool_definitions(
                    mcp_tools,
                    allow_mutations=allow_mutations,
                    scoped_greenhouse_id=greenhouse_id,
                )
                response = await run_chat_completion(
                    llm_client=llm_client,
                    messages=messages,
                    tool_definitions=tool_definitions,
                    allowed_tool_names=allowed_tool_names,
                    tool_client=active_tool_client,
                    session_id=session.id,
                    scoped_greenhouse_id=greenhouse_id,
                )
                persist_chat_turn(
                    db,
                    session=session,
                    user_message=body.message,
                    assistant_reply=response.reply,
                )
                record_usage_event(
                    db,
                    tenant_id=tenant.id,
                    user_id=current_user.id,
                    event_type="ai_chat_message",
                    metadata={"scope": scope.value, "greenhouse_id": greenhouse_id},
                )
                db.commit()
                return response

        response = await run_chat_completion(
            llm_client=llm_client,
            messages=messages,
            tool_definitions=[],
            allowed_tool_names=set(),
            tool_client=None,
            session_id=session.id,
            scoped_greenhouse_id=greenhouse_id,
        )
        persist_chat_turn(
            db,
            session=session,
            user_message=body.message,
            assistant_reply=response.reply,
        )
        record_usage_event(
            db,
            tenant_id=tenant.id,
            user_id=current_user.id,
            event_type="ai_chat_message",
            metadata={"scope": scope.value, "greenhouse_id": greenhouse_id},
        )
        db.commit()
        return response
    finally:
        ctx_user.reset(token)


@router.post("/ai/chat", response_model=ChatRequestResponse)
async def chat_endpoint(
    request: Request,
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return await run_chat_request(
        request=request,
        body=body,
        current_user=current_user,
        db=db,
        greenhouse=None,
    )


@router.post("/greenhouses/{greenhouse_id}/ai/chat", response_model=ChatRequestResponse)
async def greenhouse_chat_endpoint(
    request: Request,
    body: ChatRequest,
    greenhouse: Greenhouse = Depends(get_authorized_greenhouse),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return await run_chat_request(
        request=request,
        body=body,
        current_user=current_user,
        db=db,
        greenhouse=greenhouse,
    )


async def run_chat_completion(
    *,
    llm_client: Any,
    messages: list[dict[str, Any]],
    tool_definitions: list[dict[str, Any]],
    allowed_tool_names: set[str],
    tool_client: Any,
    session_id: int | None = None,
    scoped_greenhouse_id: int | None = None,
) -> ChatRequestResponse:
    completion_kwargs: dict[str, Any] = {
        "model": settings.AI_CHAT_MODEL,
        "messages": messages,
    }
    if tool_definitions:
        completion_kwargs["tools"] = tool_definitions
        completion_kwargs["tool_choice"] = "auto"

    try:
        response = await llm_client.chat.completions.create(**completion_kwargs)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("AI provider request failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI provider request failed",
        ) from exc

    response_message = response.choices[0].message
    tool_calls = list(getattr(response_message, "tool_calls", None) or [])

    # Fallback: Deepseek sometimes emits tool calls as DSML text in content
    dsml_parsed: list[ParsedToolCall] = []
    if not tool_calls and tool_client is not None:
        raw_content = extract_message_text(response_message.content)
        prefix_text, dsml_parsed = parse_dsml_tool_calls(raw_content)

    if (tool_calls or dsml_parsed) and tool_client is not None:
        if tool_calls:
            # Standard structured tool calls
            messages.append(dump_message(response_message))
            for tool_call in tool_calls:
                arguments = getattr(tool_call.function, "arguments", "{}")
                try:
                    tool_args = json.loads(arguments or "{}")
                except json.JSONDecodeError:
                    tool_args = {}
                await _execute_tool_call(
                    messages,
                    tool_client,
                    allowed_tool_names,
                    tool_call.id,
                    tool_call.function.name,
                    tool_args,
                    scoped_greenhouse_id=scoped_greenhouse_id,
                )
        else:
            # DSML-parsed tool calls
            assistant_text = prefix_text if prefix_text else "Buyruqni bajarayapman..."
            tc_dicts = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                }
                for tc in dsml_parsed
            ]
            messages.append({
                "role": "assistant",
                "content": assistant_text,
                "tool_calls": tc_dicts,
            })
            for tc in dsml_parsed:
                await _execute_tool_call(
                    messages,
                    tool_client,
                    allowed_tool_names,
                    tc.id,
                    tc.name,
                    tc.arguments,
                    scoped_greenhouse_id=scoped_greenhouse_id,
                )

        try:
            final_response = await llm_client.chat.completions.create(
                model=settings.AI_CHAT_MODEL,
                messages=messages,
            )
        except Exception as exc:
            logger.exception("AI provider final response request failed")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="AI provider request failed",
            ) from exc

        final_text = extract_message_text(final_response.choices[0].message.content)
        if not final_text:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="AI provider returned an empty final response",
            )
        return ChatRequestResponse(reply=final_text, session_id=session_id)

    reply = extract_message_text(response_message.content)
    if not reply:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI provider returned an empty response",
        )
    return ChatRequestResponse(reply=reply, session_id=session_id)


async def _execute_tool_call(
    messages: list[dict[str, Any]],
    tool_client: Any,
    allowed_tool_names: set[str],
    call_id: str,
    tool_name: str,
    tool_args: dict[str, Any],
    *,
    scoped_greenhouse_id: int | None = None,
) -> None:
    try:
        if tool_name not in allowed_tool_names:
            tool_content = "Error: Tool is not allowed for this request."
        elif scoped_greenhouse_id is not None and "greenhouse_id" in tool_args:
            try:
                requested_greenhouse_id = int(tool_args["greenhouse_id"])
            except (TypeError, ValueError):
                requested_greenhouse_id = None
            if requested_greenhouse_id not in {None, scoped_greenhouse_id}:
                tool_content = (
                    f"Error: This scoped chat can only access greenhouse "
                    f"{scoped_greenhouse_id}."
                )
            else:
                tool_args["greenhouse_id"] = scoped_greenhouse_id
                result = await tool_client.call_tool(tool_name, tool_args)
                tool_content = (
                    result.content[0].text
                    if result and getattr(result, "content", None)
                    else "Success"
                )
        else:
            if scoped_greenhouse_id is not None and "__greenhouse_id__" in tool_name:
                tool_args["greenhouse_id"] = scoped_greenhouse_id
            result = await tool_client.call_tool(tool_name, tool_args)
            tool_content = (
                result.content[0].text
                if result and getattr(result, "content", None)
                else "Success"
            )
    except Exception:
        logger.exception("Tool call failed for tool=%s", tool_name)
        tool_content = "Error: tool execution failed"

    messages.append(
        {
            "role": "tool",
            "tool_call_id": call_id,
            "name": tool_name,
            "content": str(tool_content),
        }
    )
