from fastapi import FastAPI
from .database import Base, engine

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Creative Design Server")

@app.get("/health")
def health_check():
    return {"status": "ok"}
