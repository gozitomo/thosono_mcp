import asyncio, os, json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from contextlib import AsyncExitStack
from google import genai
from google.genai import types

LOCATION = "asia-northeast1"


def mcp_tool_to_gemini(tool) -> types.FunctionDeclaration:
    """MCPのツール定義をGeminiのFunctionDeclaration形式に変換"""
    schema = dict(tool.inputSchema) if tool.inputSchema else {}

    # Geminiが受け付けないキーを除去
    def clean_schema(obj):
        if isinstance(obj, dict):
            obj.pop("$schema", None)
            obj.pop("additionalProperties", None)
            for value in obj.values():
                clean_schema(value)
        elif isinstance(obj, list):
            for item in obj:
                clean_schema(item)
        return obj

    schema = clean_schema(schema)
    return types.FunctionDeclaration(
        name=tool.name,
        description=tool.description or "",
        parameters=schema,
    )


async def run_autonomous_agent():
    server_params = StdioServerParameters(
        command="python",
        args=["servers/discord.py"],
        env={
            **os.environ,
            "DISCORD_BOT_TOKEN": os.getenv("DISCORD_BOT_TOKEN"),
        },
    )

    async with AsyncExitStack() as stack:
        transport = await stack.enter_async_context(stdio_client(server_params))
        session = await stack.enter_async_context(
            ClientSession(transport[0], transport[1])
        )
        await session.initialize()

        # MCPツール -> Gemini Tool形式に変換
        mcp_tools = await session.list_tools()
        gemini_functions = [mcp_tool_to_gemini(t) for t in mcp_tools.tools]
        gemini_tools = types.Tool(function_declarations=gemini_functions)

        # プロンプト読み込み
        with open("prompts/motivate.md", "r") as f:
            prompt_template = f.read()

        channel_id = os.getenv("DISCORD_CHANNEL_ID")
        prompt = prompt_template.replace("{{channel_id}}", channel_id)

        try:
            client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(tools=[gemini_tools]),
            )

            # function_callが返ってきた場合に実行
            for part in response.candidates[0].content.parts:
                if part.function_call:
                    fc = part.function_call
                    result = await session.call_tool(fc.name, dict(fc.args))
                    print(f"Tool {fc.name} called, result: {result}")
        except Exception as e:
            print(f"エラー: {e}")
            raise
