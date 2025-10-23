import uuid
import shutil
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from .database import SessionLocal, engine
from . import models

# DB 초기화
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Creative Design Server", version="1.0")

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
