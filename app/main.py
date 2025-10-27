import uuid
import shutil
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.orm import Session
from .database import SessionLocal, engine
from . import models
import requests
import io
from pydantic import BaseModel
import os
from dotenv import load_dotenv

# DB 초기화
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Creative Design Server", version="1.0")

# AI 서버
load_dotenv()
AI_SERVER_URL = os.getenv("AI_SERVER_URL")

# DB 세션 관리
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 1. 사용자 생성
@app.post("/api/v1/users")
def create_user(name: str | None = None, db: Session = Depends(get_db)):
    new_user = models.User(name=name)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"user_id": new_user.id}

# 2. 이미지 업로드 
UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

@app.post("/api/v1/upload")
def upload_image(
    user_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    # 사용자 존재 확인
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 확장자 확인
    ext = Path(file.filename).suffix.lower()
    if ext not in [".jpg", ".jpeg", ".png"]:
        raise HTTPException(status_code=400, detail="Invalid file format")

    # UUID 기반 파일명 생성
    safe_name = f"user{user_id}_{uuid.uuid4().hex}{ext}"
    save_path = UPLOAD_DIR / safe_name

    # 파일 저장
    try:
        with save_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File save failed: {str(e)}")

    # DB 기록
    new_image = models.Image(user_id=user_id, file_path=str(save_path))
    db.add(new_image)
    db.commit()
    db.refresh(new_image)

    return {"image_id": new_image.id, "file_path": str(save_path)}
    
# 3. 이미지 분석 요청
@app.post("/api/v1/analyze/{image_id}")
async def analyze_image(
    image_id: int,
    user_id: int = Query(..., description="요청 사용자 ID"),
    db: Session = Depends(get_db)
):
    # 사용자 확인
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 이미지 확인 (해당 user_id의 이미지인지 검증)
    image = (
        db.query(models.Image)
        .filter(models.Image.id == image_id, models.Image.user_id == user_id)
        .first()
    )
    if not image:
        raise HTTPException(status_code=404, detail="Image not found for this user")

    # 기존 분석 결과가 있으면 바로 반환
    existing = db.query(models.AnalysisResult).filter(
        models.AnalysisResult.image_id == image_id
    ).first()

    if existing:
        return {
            "image_id": image_id,
            "scores": {
                "acne": existing.acne,
                "hemo": existing.hemo,
                "mela": existing.mela,
                "pore": existing.pore,
                "wrinkle": existing.wrinkle,
            }
        }

    # 이미지 파일 경로 확인
    image_path = Path(image.file_path)
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image file not found on server")

    # AI 서버로 요청 (모든 항목 일괄 분석)
    try:
        with image_path.open("rb") as f:
            files = {"file": (image_path.name, f, "image/jpeg")}
            response = requests.post(AI_SERVER_URL, files=files, timeout=90)
            response.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to connect AI server: {str(e)}")

    raw_scores = response.json()

    # DB 저장용 점수
    scores = {
        "acne": raw_scores.get("acne"),
        "hemo": raw_scores.get("hemo"),
        "mela": raw_scores.get("mela"),
        "pore": raw_scores.get("pore"),
        "wrinkle": raw_scores.get("wrinkle"),
    }

    # DB 저장
    result = models.AnalysisResult(image_id=image_id, **scores)
    db.add(result)
    db.commit()
    db.refresh(result)

    return {
        "image_id": image_id,
        "scores": scores
    }

# 4. 특정 이미지 분석 결과 조회
@app.get("/results/image/{image_id}")
async def get_analysis_result(
    image_id: int,
    db: Session = Depends(get_db)
):
    result = db.query(models.AnalysisResult).filter(
        models.AnalysisResult.image_id == image_id
    ).first()

    if not result:
        raise HTTPException(status_code=404, detail="Analysis result not found")

    return {
        "image_id": result.image_id,
        "acne": result.acne,
        "hemo": result.hemo,
        "mela": result.mela,
        "pore": result.pore,
        "wrinkle": result.wrinkle,
        "created_at": result.created_at
    }
