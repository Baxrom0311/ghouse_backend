import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api.routes import ai_chat


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self, exclude_none=True):
        payload = {"role": "assistant"}
        if self.content is not None:
            payload["content"] = self.content
        if self.tool_calls is not None:
            payload["tool_calls"] = [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments,
                    },
                }
                for tool_call in self.tool_calls
            ]
        return payload


class FakeResponse:
    def __init__(self, message):
        self.choices = [SimpleNamespace(message=message)]


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeAIClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=FakeCompletions(responses))


class FakeToolClient:
    def __init__(self, mcp_instance):
        self.mcp_instance = mcp_instance

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def list_tools(self):
        return [
            SimpleNamespace(
                name="list_greenhouses_api_greenhouses_get",
                description="List greenhouses",
                inputSchema={"type": "object", "properties": {}},
            )
        ]

    async def call_tool(self, name, arguments):
        return SimpleNamespace(
            content=[
                SimpleNamespace(
                    text=f"tool={name};args={json.dumps(arguments, sort_keys=True)}"
                )
            ]
        )


def test_ai_chat_basic_reply(login_client: TestClient, monkeypatch):
    fake_ai_client = FakeAIClient([FakeResponse(FakeMessage(content="Mocked reply"))])

    monkeypatch.setattr(ai_chat, "get_ai_client", lambda: fake_ai_client)
    monkeypatch.setattr(ai_chat, "get_mcp_client_class", lambda: None)

    response = login_client.post(
        "/api/ai/chat",
        json={"message": "Hello assistant", "history": []},
    )

    assert response.status_code == 200
    assert response.json() == {"reply": "Mocked reply"}
    assert fake_ai_client.chat.completions.calls[0]["model"] == "deepseek-chat"


def test_ai_chat_tool_flow(login_client: TestClient, monkeypatch):
    tool_call = SimpleNamespace(
        id="tool-call-1",
        function=SimpleNamespace(
            name="list_greenhouses_api_greenhouses_get",
            arguments='{"greenhouse_id": 1}',
        ),
    )
    fake_ai_client = FakeAIClient(
        [
            FakeResponse(FakeMessage(tool_calls=[tool_call])),
            FakeResponse(FakeMessage(content="Greenhouse 1 is healthy.")),
        ]
    )

    monkeypatch.setattr(ai_chat, "get_ai_client", lambda: fake_ai_client)
    monkeypatch.setattr(ai_chat, "get_mcp_client_class", lambda: FakeToolClient)

    response = login_client.post(
        "/api/ai/chat",
        json={"message": "Summarize greenhouse 1", "history": []},
    )

    assert response.status_code == 200
    assert response.json() == {"reply": "Greenhouse 1 is healthy."}
    assert len(fake_ai_client.chat.completions.calls) == 2
