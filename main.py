from fastapi import FastAPI, HTTPException
from agent import run_autonomous_agent
import asyncio

app = FastAPI()

@app.post("/run")
async def run():
    try:
        await run_autonomous_agent()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/health")
def health():
    return {"status": "healthy"}
