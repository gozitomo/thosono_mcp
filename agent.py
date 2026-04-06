import asyncio, os, json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from contextlib import AsyncExitStack
from google import genai
from google.genai import types
from datetime import datetime
import pytz

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


async def run_autonomous_agent(
    user_name: str, user_text: str = None, mode: str = "reply"
):
    # JSTで時刻を取得
    jst = pytz.timezone("Asia/Tokyo")
    now = datetime.now(jst)
    current_time_str = now.strftime("%Y年%m月%d日 %H時%M分")

    # 時間帯の判定（AIが判断しやすいように）
    hour = now.hour
    if 5 <= hour < 16:
        period = "始動・応援モード"
    elif 16 <= hour < 21:
        period = "集中・進捗確認モード"
    else:
        period = "振り返り・承認モード"

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
        prompt_file = "prompts/motivate.md" if mode == "reply" else "prompts/remind.md"
        with open(prompt_file, "r") as f:
            prompt_template = f.read()

        # 共通のヘッダーを作成
        context_header = f"【現在の時刻: {current_time_str} （{period}）】\n"
        channel_id = os.getenv("DISCORD_CHANNEL_ID")
        prompt = context_header + prompt_template.replace("{{channel_id}}", channel_id)
        if mode == "reply":
            prompt += f"\n現在、{user_name}さんから「{user_text}」というメッセージが届いています。返事をしてください。"
        else:
            # 定時実行時
            prompt += f"\n夕方の定期リマインドの時間です。まずはツールの get_todo_list を使って、{user_name}さんの現在の状況を確認してから、話しかけてください。"

        try:
            client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
            # メッセージ履歴を管理（会話の流れをGeminiに理解させるため）
            # 最初のユーザー（システム）からの指示
            chat_history = [types.Content(role="user", parts=[types.Part(text=prompt)])]

            # 1回目のリクエスト
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=chat_history,
                config=types.GenerateContentConfig(tools=[gemini_tools]),
            )

            # --- ここからループ（ツール呼び出しがなくなるまで繰り返す） ---
            current_response = response.candidates[0].content

            while True:
                # 履歴にGeminiの回答（function_callを含む可能性がある）を追加
                chat_history.append(current_response)

                # function_call が含まれているか確認
                found_fc = False
                for part in current_response.parts:
                    if part.function_call:
                        found_fc = True
                        fc = part.function_call

                        # ツール実行
                        print(f"Executing tool: {fc.name} with args {fc.args}")
                        result = await session.call_tool(fc.name, dict(fc.args))

                        # MCPの TextContent から文字列を抽出
                        # ここで 'str' object has no attribute 'json' を回避
                        tool_output_texts = [
                            c.text for c in result.content if hasattr(c, "text")
                        ]
                        final_tool_output = "\n".join(tool_output_texts)
                        print(f"Tool {fc.name} output: {final_tool_output}")

                        # ツール実行結果をGeminiに差し戻す用の Part を作成
                        tool_response_part = types.Part(
                            function_response=types.FunctionResponse(
                                name=fc.name, response={"result": final_tool_output}
                            )
                        )

                        # ツール結果を履歴に追加して、再度Geminiに投げる
                        new_response = client.models.generate_content(
                            model="gemini-2.5-flash",
                            contents=chat_history
                            + [types.Content(role="tool", parts=[tool_response_part])],
                            config=types.GenerateContentConfig(tools=[gemini_tools]),
                        )

                        # responseが空の時はスキップ
                        if (
                            not new_response.candidates
                            or not new_response.candidates[0].content
                        ):
                            print("全タスクを終了しました")
                            current_response = None
                            found_fc = False
                            break
                        current_response = new_response.candidates[0].content
                        break  # 1つずつ処理してループを回す

                # function_call が見つからなければ、通常のテキスト返答が得られたと判断して終了
                if not found_fc:
                    # current_response や parts が存在するかチェック
                    if (
                        current_response
                        and hasattr(current_response, "parts")
                        and current_response.parts
                    ):
                        # テキストが含まれているPartだけを取り出す
                        text_parts = [
                            p.text
                            for p in current_response.parts
                            if hasattr(p, "text") and p.text
                        ]
                        final_text = "".join(text_parts)
                        # 最後に得られたテキストを表示
                        if final_text:
                            print(f"かあさんの回答: {final_text}")
                        else:
                            print("かあさん回答なし")
                    else:
                        print("かあさん回答空でした")
                    break

        except Exception as e:
            print(f"エラー: {e}")
            import traceback

            traceback.print_exc()  # 詳細なエラー箇所を表示
            raise
