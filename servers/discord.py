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
            description="新しい宿題を登録する。複数ある場合はまとめて登録する。",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "ユーザーID（例：tatsuzin）",
                    },
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {
                                    "type": "string",
                                    "description": "宿題の内容（例：教科書ワーク",
                                },
                                "amount": {
                                    "type": "string",
                                    "description": "量（例：3ページ）",
                                },
                                "due_date": {
                                    "type": "string",
                                    "description": "期限（例：2024-04-10）。指定がない場合は、今日の日付をデフォルトとして使用してください。",
                                },
                            },
                            "required": ["title"],
                        },
                    },
                },
                "required": ["user_id", "items"],
            },
        ),
        # 2. タスク・宿題の状態更新 (完了・追加)
        Tool(
            name="sync_todo",
            description="宿題やタスクの状態を更新する。複数まとめて更新可能。",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "updates": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "collection_name": {
                                    "type": "string",
                                    "enum": ["homeworks", "tasks", "projects"],
                                },
                                "doc_id": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": ["未着手", "進行中", "完了"],
                                },
                                "due_date": {
                                    "type": "string",
                                    "description": "期限（例：2024-04-10）。指定がない場合は、今日の日付をデフォルトとして使用してください。",
                                },
                            },
                            "required": ["collection_name", "doc_id", "status"],
                        },
                    },
                },
                "required": ["user_id", "updates"],
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
        # items というリストで受け取る想定
        items = arguments.get("items", [])
        user_id = arguments.get("user_id")
        if not items and "title" in arguments:
            items = [
                {
                    "title": arguments.get("title", ""),
                    "amount": arguments.get("amount", "1"),
                    "due_date": arguments.get("due_date", ""),
                }
            ]

        registered_titles = []
        # Firestoreのバッチ処理を使用する

        batch = db.batch()

        for item in items:
            doc_ref = (
                db.collection("users")
                .document(user_id)
                .collection("homeworks")
                .document()
            )
            data = {
                "title": item.get("title"),
                "amount": item.get("amount"),
                "due_date": item.get("due_date"),
                "status": "未着手",
                "updated_at": firestore.SERVER_TIMESTAMP,
            }
            batch.set(doc_ref, data)
            registered_titles.append(item["title"])
        batch.commit()

        titles_str = "、".join(registered_titles)
        return [
            TextContent(
                type="text",
                text=f"☑️{user_id}の宿題『{titles_str}』を登録したよ！",
            )
        ]

    # --- sync_todo: 更新 ---
    if name == "sync_todo":
        user_id = arguments.get("user.id")
        updates = arguments.get("updates", [])

        # 1件だけのとき
        if not updates and "doc_id" in arguments:
            updates = [
                {
                    "collection_name": arguments.get("collection_name"),
                    "doc_id": arguments.get("doc_id"),
                    "status": arguments.get("status"),
                    "due_date": arguments.get("due_date"),
                }
            ]
        batch = db.batch()
        updated_count = 0

        try:
            for up in updates:
                col = up.get("collection_name")
                did = up.get("doc_id")
                new_status = up.get("status")

                if not (col and did and new_status):
                    continue
                doc_ref = (
                    db.collection("users")
                    .document(user_id)
                    .collection(col)
                    .document(did)
                )
                batch.set(
                    doc_ref,
                    {"status": new_status, "updated_at": firestore.SERVER_TIMESTAMP},
                    merge=True,
                )
                updated_count += 1

            batch.commit()
            return [
                TextContent(
                    type="text",
                    text=f"✅ {updated_count}件のタスクを更新したよ！お疲れ様！",
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
