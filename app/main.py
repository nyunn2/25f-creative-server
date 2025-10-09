from fastapi import FastAPI
from .database import Base, engine
from . import models

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Creative Design Server")

@app.get("/health")
def health_check():
    return {"status": "ok"}
