import os
import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from google.cloud import firestore

server = Server("discord")

db = firestore.Client(project=os.getenv("GOOGLE_CLOUD_PROJECT"), database="to-do-list")


@server.list_tools()
async def list_tools():
    return [
        # 1. 宿題の新規登録
        Tool(
            name="add_homework",
            description="新しい宿題を登録する。args=[ユーザーID、内容、量、期日]",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "ユーザーID（例：tatsuzin）",
                    },
                    "title": {"type": "string", "description": "宿題の内容"},
                    "amount": {"type": "string", "description": "量（例: 3ページ"},
                    "due_date": {"type": "string", "description": "期日（YYYY-MM-DD）"},
                },
                "required": ["user_id", "title", "amount", "due_date"],
            },
        ),
        # 2. タスク・宿題の状態更新 (完了・追加)
        Tool(
            name="sync_todo",
            description="宿題、プロジェクトの状態を更新する。完了報告の際に使用する。",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "collection_name": {
                        "type": "string",
                        "enum": ["homeworks", "tasks", "projects"],
                    },
                    "doc_id": {
                        "type": "string",
                        "description": "更新するドキュメントID",
                    },
                    "status": {"type": "string", "enum": ["未着手", "進行中", "完了"]},
                },
                "required": ["user_id", "collection_name", "doc_id", "status"],
            },
        ),
        # 3. TODOリストの一括取得
        Tool(
            name="get_todo_list",
            description="現在の宿題、ルーティン、プロジェクトの一覧をすべて取得する。",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                },
                "required": ["user_id"],
            },
        ),
        # 4. メッセージ送信（既存）
        Tool(
            name="send_message",
            description="Discordのチャンネルにメッセージを送信する",
            inputSchema={
                "type": "object",
                "properties": {
                    "channel_id": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["channel_id", "content"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    user_id = arguments.get("user_id")

    # --- add_homework: 登録 ---
    if name == "add_homework":
        doc_ref = (
            db.collection("users").document(user_id).collection("homeworks").document()
        )
        data = {
            "title": arguments["title"],
            "amount": arguments["amount"],
            "due_date": arguments["due_date"],
            "status": "未着手",
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        doc_ref.set(data)
        return [
            TextContent(
                type="text",
                text=f"☑️{user_id}の宿題『{arguments['title']}』を登録したよ！",
            )
        ]

    # --- sync_todo: 更新 ---
    if name == "sync_todo":
        try:
            doc_ref = (
                db.collection("users")
                .document(user_id)
                .collection(arguments["collection_name"])
                .document(arguments["doc_id"])
            )
            doc_ref.update(
                {
                    "status": arguments["status"],
                    "updated_at": firestore.SERVER_TIMESTAMP,
                }
            )
            return [
                TextContent(
                    type="text",
                    text=f"✨ {arguments['doc_id']} を『{arguments['status']}』にしたよ！",
                )
            ]
        except Exception as e:
            print(f"ERROR: sync_todo failed:{e}")
            return [TextContent(type="text", text="更新に失敗しちゃった。ごめんね。")]

    # ---get_todo_list: 取得 ---
    if name == "get_todo_list":
        user_ref = db.collection("users").document(user_id)

        # 3つのコレクションを並列で取得
        results = []
        for col in ["homeworks", "tasks", "projects"]:
            docs = list(user_ref.collection(col).stream())
            items = []
            for d in docs:
                data = d.to_dict()
                items.append(
                    f"- ID: {d.id} / 内容: {data.get('title')} [{data.get('status', 'なし')}]"
                )
            results.append(f"【{col}】】\n" + ("\n".join(items) if items else "なし"))
        return [TextContent(type="text", text="\n\n".join(results))]

    # --- send_message: 送信 ---
    if name == "send_message":
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://discord.com/api/v10/channels/{arguments['channel_id']}/messages",
                headers={
                    "Authorization": f"Bot {os.getenv('DISCORD_BOT_TOKEN')}",
                    "Content-Type": "application/json",
                    "User-Agent": "DiscordBot (https://github.com/discord/discord-api-docs, 10)",
                },
                json={"content": arguments["content"]},
            )
        return [TextContent(type="text", text="送信しました")]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
