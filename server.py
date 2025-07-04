from fastapi import FastAPI
import asyncio
from botSpeecha import bot, dp, main  # Импорт из botSpeecha.py

app = FastAPI()

@app.get("/")
def ping():
    return {"message": "Speecha is alive"}

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(main())