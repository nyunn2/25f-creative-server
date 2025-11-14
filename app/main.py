import uuid
import shutil
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from app.database import SessionLocal, engine
from app import models
import requests
import os
from dotenv import load_dotenv
import base64

# 서버 기본 설정
app = FastAPI(title="Creative Design Server", version="1.0")

# DB 초기화
models.Base.metadata.create_all(bind=engine)

# 이미지 업로드
UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# env 로드
load_dotenv()
# BASE_DIR = Path(__file__).resolve().parent.parent
# load_dotenv(BASE_DIR / ".env")

# AI 서버
AI_SERVER_URL = os.getenv("AI_SERVER_URL")

# EC2 서버
SERVER_BASE_URL = os.getenv("SERVER_BASE_URL", "http://localhost:8000")

# static mount
app.mount("/static", StaticFiles(directory=UPLOAD_DIR), name="static")

# DB 세션 관리
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# overlay 파일 관리
def save_overlay_file(user_id: int, image_id: int, task: str, b64: str) -> str:
    filename = f"user{user_id}_{image_id}_{task}_{uuid.uuid4().hex}.png"
    save_path = UPLOAD_DIR / filename

    try:
        img_data = base64.b64decode(b64)
        with open(save_path, "wb") as f:
            f.write(img_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Overlay save failed: {str(e)}")

    return f"{SERVER_BASE_URL}/static/{filename}"

# 1. 사용자 생성
@app.post("/api/v1/users")
def create_user(name: str | None = None, db: Session = Depends(get_db)):
    new_user = models.User(name=name)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"user_id": new_user.id}

# 2. 이미지 업로드
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

    image_url = f"{SERVER_BASE_URL}/static/{safe_name}"

    return {"image_id": new_image.id, "image_url": image_url}
    
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

    # 이미지 확인
    image = (
        db.query(models.Image)
        .filter(models.Image.id == image_id, models.Image.user_id == user_id)
        .first()
    )
    if not image:
        raise HTTPException(status_code=404, detail="Image not found for this user")

    # 기존 분석 존재 시 반환
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
            },
            "overlays": {
                "acne": existing.overlay_acne,
                "hemo": existing.overlay_hemo,
                "mela": existing.overlay_mela,
                "pore": existing.overlay_pore,
                "wrinkle": existing.overlay_wrinkle,
            }
        }

    # 이미지 파일 경로 확인
    image_path = Path(image.file_path)
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image file not found on server")

    # AI 서버 호출
    try:
        with image_path.open("rb") as f:
            files = {"file": (image_path.name, f, "image/jpeg")}
            response = requests.post(AI_SERVER_URL, files=files, timeout=90)
            response.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to connect AI server: {str(e)}")

    ai_res = response.json()

    # task 순서
    tasks = ["acne", "hemo", "mela", "pore", "wrinkle"]

    # 점수 + overlay URL 저장 준비
    scores = {}
    overlays = {}

    for t in tasks:
        ratio = ai_res[t]["ratio"]
        overlay_b64 = ai_res[t]["overlay"]

        scores[t] = ratio

        # overlay 이미지를 파일로 저장
        overlay_url = save_overlay_file(user_id, image_id, t, overlay_b64)
        overlays[t] = overlay_url

    # DB 저장
    result = models.AnalysisResult(
        image_id=image_id,
        acne=scores["acne"],
        hemo=scores["hemo"],
        mela=scores["mela"],
        pore=scores["pore"],
        wrinkle=scores["wrinkle"],
        overlay_acne=overlays["acne"],
        overlay_hemo=overlays["hemo"],
        overlay_mela=overlays["mela"],
        overlay_pore=overlays["pore"],
        overlay_wrinkle=overlays["wrinkle"]
    )

    db.add(result)
    db.commit()
    db.refresh(result)

    return {
        "image_id": image_id,
        "scores": scores,
        "overlays": overlays
    }


# 4. 사용자 전체 분석 조회
@app.get("/api/v1/results/user/{user_id}")
def get_user_results(user_id: int, db: Session = Depends(get_db)):

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    rows = (
        db.query(models.Image, models.AnalysisResult)
        .outerjoin(models.AnalysisResult, models.Image.id == models.AnalysisResult.image_id)
        .filter(models.Image.user_id == user_id)
        .order_by(models.Image.uploaded_at.desc())
        .all()
    )

    results = []

    for img, analysis in rows:
        file_name = Path(img.file_path).name
        image_url = f"{SERVER_BASE_URL}/static/{file_name}"

        results.append({
            "image_id": img.id,
            "image_url": image_url,
            "uploaded_at": img.uploaded_at.isoformat(),
            "scores": {
                "acne": analysis.acne if analysis else None,
                "hemo": analysis.hemo if analysis else None,
                "mela": analysis.mela if analysis else None,
                "pore": analysis.pore if analysis else None,
                "wrinkle": analysis.wrinkle if analysis else None,
            },
            "overlays": {
                "acne": analysis.overlay_acne if analysis else None,
                "hemo": analysis.overlay_hemo if analysis else None,
                "mela": analysis.overlay_mela if analysis else None,
                "pore": analysis.overlay_pore if analysis else None,
                "wrinkle": analysis.overlay_wrinkle if analysis else None,
            } if analysis else None,
            "analysis_created_at": analysis.created_at.isoformat() if analysis else None
        })

    return results