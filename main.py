from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from agent import run_autonomous_agent
import asyncio

app = FastAPI()


class ChatRequest(BaseModel):
    text: str
    user: str


@app.post("/run")
async def run():
    try:
        await run_autonomous_agent()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat")
async def chat(req: ChatRequest):
    try:
        # 引数つきで自律エージェント（メッセージ生成と送信）を実行
        await run_autonomous_agent(user_name=req.user, user_text=req.text)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
def health():
    return {"status": "healthy"}
