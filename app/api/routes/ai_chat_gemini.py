import google.generativeai as genai
from google.ai.generativelanguage_v1beta.types import content
from fastmcp import Client
from pydantic import BaseModel
from fastapi import APIRouter, Request, HTTPException, Depends
from app.core.config import settings
from app.models.user import User
from app.api.deps import get_current_user
from app.core.context import ctx_user

genai.configure(api_key=settings.GOOGLE_API_KEY)

class ChatRequest(BaseModel):
    message: str
    history: list = []

class ChatRequestResponse(BaseModel):
    reply: str

router = APIRouter()

# ---------------------------------------------------------------------------
# SCHEMA CLEANER
# ---------------------------------------------------------------------------
def clean_schema(schema: dict) -> dict:
    if not isinstance(schema, dict):
        return schema
    
    schema = schema.copy()

    for key in ["title", "default", "$schema", "$ref", "$defs", "definitions"]:
        schema.pop(key, None)

    for key in ["anyOf", "oneOf"]:
        if key in schema:
            options = schema.pop(key)
            valid_option = next(
                (opt for opt in options if isinstance(opt, dict) and opt.get("type") != "null"), 
                options[0] if options else {}
            )
            cleaned_option = clean_schema(valid_option)
            schema.update(cleaned_option)

    if "allOf" in schema:
        sub_schemas = schema.pop("allOf")
        for sub in sub_schemas:
            cleaned_sub = clean_schema(sub)
            schema.update(cleaned_sub)

    if isinstance(schema.get("type"), list):
        valid_types = [t for t in schema["type"] if t != "null"]
        schema["type"] = valid_types[0] if valid_types else "string"

    if "properties" in schema:
        for name, prop in schema["properties"].items():
            schema["properties"][name] = clean_schema(prop)
            
    if "items" in schema:
        schema["items"] = clean_schema(schema["items"])

    return schema


@router.post("/ai/chat", response_model=ChatRequestResponse)
async def chat_endpoint(
    request: Request,
    body: ChatRequest,
    current_user: User = Depends(get_current_user)
):

    if not hasattr(request.app.state, "mcp"):
        raise HTTPException(status_code=500, detail="MCP Server not initialized")
    
    mcp_instance = request.app.state.mcp

    token = ctx_user.set(current_user)

    try:
        async with Client(mcp_instance) as client:
            mcp_tools = await client.list_tools()
            
            gemini_tools_declarations = []
            
            for tool in mcp_tools:
                if "chat_endpoint" in tool.name or "ai_chat" in tool.name:
                    continue

                raw_schema = tool.inputSchema.copy() if tool.inputSchema else {}
                final_schema = clean_schema(raw_schema)

                gemini_tools_declarations.append({
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": final_schema
                })

            gemini_tools = [{"function_declarations": gemini_tools_declarations}]

            try:
                model = genai.GenerativeModel(
                    model_name=settings.AI_MODEL_NAME, 
                    tools=gemini_tools
                )
                chat = model.start_chat(enable_automatic_function_calling=False)
                response = await chat.send_message_async(body.message)

            except Exception as e:
                print(f"❌ GEMINI ERROR: {str(e)}")
                raise HTTPException(status_code=500, detail=f"Gemini Error: {str(e)}")

            function_call = None
            for part in response.parts:
                if fn := part.function_call:
                    function_call = fn
                    break
            
            if function_call:
                fn_name = function_call.name
                fn_args = dict(function_call.args)
                
                print(f"🤖 Gemini calling: {fn_name} with {fn_args}")

                try:
                    result_obj = await client.call_tool(fn_name, fn_args)
                    
                    if result_obj and result_obj.content:
                        tool_result = result_obj.content[0].text
                    else:
                        tool_result = "Success"
                        
                except Exception as e:
                    tool_result = f"Error executing tool: {str(e)}"

                response_part = content.Part(
                    function_response=content.FunctionResponse(
                        name=fn_name,
                        response={"result": str(tool_result)} 
                    )
                )
                final_response = await chat.send_message_async([response_part])
                return {"reply": final_response.text}

            return {"reply": response.text}
        
    finally:
        ctx_user.reset(token)