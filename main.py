from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from agent import run_autonomous_agent
import asyncio

app = FastAPI()


class ChatRequest(BaseModel):
    text: str
    user: str


ALLOWED_USERS = ["tatsuzine_43909"]


@app.post("/run")
async def run():
    try:
        await run_autonomous_agent(
            user_name="tatsuzine_43909", user_text="", mode="regular"
        )
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat")
async def chat(req: ChatRequest):
    if req.user not in ALLOWED_USERS:
        print("DEBUG: 許可されていないユーザーアクセス")
        return {"status": "ignored", "message": "User not authorized"}
    try:
        # 引数つきで自律エージェント（メッセージ生成と送信）を実行
        await run_autonomous_agent(user_name=req.user, user_text=req.text)
        print(f"DEBUG: Received request from {req.user}")
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
def health():
    return {"status": "healthy"}
