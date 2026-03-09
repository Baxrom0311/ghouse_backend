import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.context import ctx_user
from app.models.user import User

router = APIRouter()

PLACEHOLDER_API_KEYS = {"", "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"}
SAFE_TOOL_MARKERS = ("_api_greenhouses", "_api_plant")
BLOCKED_TOOL_PREFIXES = ("delete_",)


class ChatHistoryItem(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatHistoryItem] = Field(default_factory=list)


class ChatRequestResponse(BaseModel):
    reply: str


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


def tool_is_allowed(tool_name: str) -> bool:
    if tool_name.startswith(BLOCKED_TOOL_PREFIXES):
        return False
    return any(marker in tool_name for marker in SAFE_TOOL_MARKERS)


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


def build_messages(body: ChatRequest) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are a helpful greenhouse assistant. "
                "Use greenhouse id 1 if the user asks for a greenhouse action "
                "without specifying an id."
            ),
        }
    ]

    for item in body.history:
        if item.role not in {"system", "user", "assistant", "tool"}:
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


def build_tool_definitions(mcp_tools: list[Any]) -> list[dict[str, Any]]:
    definitions: list[dict[str, Any]] = []
    for tool in mcp_tools:
        if not tool_is_allowed(tool.name):
            continue
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
    return definitions


@router.post("/ai/chat", response_model=ChatRequestResponse)
async def chat_endpoint(
    request: Request,
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    llm_client = get_ai_client()
    mcp_instance = getattr(request.app.state, "mcp", None)
    client_class = get_mcp_client_class()
    messages = build_messages(body)
    token = ctx_user.set(current_user)

    try:
        tool_definitions: list[dict[str, Any]] = []
        tool_client = None

        if mcp_instance is not None and client_class is not None:
            tool_client = client_class(mcp_instance)

        if tool_client is not None:
            async with tool_client as active_tool_client:
                mcp_tools = await active_tool_client.list_tools()
                tool_definitions = build_tool_definitions(mcp_tools)
                return await run_chat_completion(
                    llm_client=llm_client,
                    messages=messages,
                    tool_definitions=tool_definitions,
                    tool_client=active_tool_client,
                )

        return await run_chat_completion(
            llm_client=llm_client,
            messages=messages,
            tool_definitions=[],
            tool_client=None,
        )
    finally:
        ctx_user.reset(token)


async def run_chat_completion(
    *,
    llm_client: Any,
    messages: list[dict[str, Any]],
    tool_definitions: list[dict[str, Any]],
    tool_client: Any,
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
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI provider request failed: {exc}",
        ) from exc

    response_message = response.choices[0].message
    tool_calls = list(getattr(response_message, "tool_calls", None) or [])
    if tool_calls and tool_client is not None:
        messages.append(dump_message(response_message))

        for tool_call in tool_calls:
            arguments = getattr(tool_call.function, "arguments", "{}")
            try:
                tool_args = json.loads(arguments or "{}")
            except json.JSONDecodeError:
                tool_args = {}

            try:
                result = await tool_client.call_tool(tool_call.function.name, tool_args)
                tool_content = (
                    result.content[0].text
                    if result and getattr(result, "content", None)
                    else "Success"
                )
            except Exception as exc:
                tool_content = f"Error: {exc}"

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.function.name,
                    "content": str(tool_content),
                }
            )

        try:
            final_response = await llm_client.chat.completions.create(
                model=settings.AI_CHAT_MODEL,
                messages=messages,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"AI provider request failed: {exc}",
            ) from exc

        final_text = extract_message_text(final_response.choices[0].message.content)
        if not final_text:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="AI provider returned an empty final response",
            )
        return ChatRequestResponse(reply=final_text)

    reply = extract_message_text(response_message.content)
    if not reply:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI provider returned an empty response",
        )
    return ChatRequestResponse(reply=reply)
