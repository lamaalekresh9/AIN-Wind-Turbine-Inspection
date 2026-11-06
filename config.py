import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _bool(name, default=False):
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _path(p):
    p = Path(p)
    return p if p.is_absolute() else BASE_DIR / p


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")

    INSTANCE_DIR = BASE_DIR / "instance"
    UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", INSTANCE_DIR / "uploads"))
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", f"sqlite:///{(INSTANCE_DIR / 'ain.db').as_posix()}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    MAX_CONTENT_LENGTH = int(os.getenv("MAX_UPLOAD_MB", "500")) * 1024 * 1024
    ALLOWED_IMAGE_EXT = {"jpg", "jpeg", "png", "bmp", "webp"}
    ALLOWED_VIDEO_EXT = {"mp4", "mov", "avi", "mkv"}
    MAX_IMAGE_MB = int(os.getenv("MAX_IMAGE_MB", "25"))

    # Detection model
    MODEL_PATH = _path(os.getenv("MODEL_PATH") or "models/best.pt")
    MODEL_DEVICE = os.getenv("MODEL_DEVICE", "")  # "" = auto, "cpu", "0" for GPU 0
    MODEL_IMGSZ = int(os.getenv("MODEL_IMGSZ", "1024"))
    DEFAULT_CONF = float(os.getenv("DEFAULT_CONF", "0.25"))
    NMS_IOU = float(os.getenv("NMS_IOU", "0.7"))
    MAX_DETECTIONS = int(os.getenv("MAX_DETECTIONS", "300"))

    # Optional blade segmentation model (YOLO-seg). Leave empty for passthrough.
    BLADE_SEG_MODEL_PATH = str(_path(os.getenv("BLADE_SEG_MODEL_PATH"))) if os.getenv("BLADE_SEG_MODEL_PATH") else ""

    # Video
    DEFAULT_FRAME_INTERVAL = float(os.getenv("DEFAULT_FRAME_INTERVAL", "1.0"))
    MAX_FRAMES_PER_VIDEO = int(os.getenv("MAX_FRAMES_PER_VIDEO", "300"))
    DEDUP_IOU = float(os.getenv("DEDUP_IOU", "0.3"))
    DEDUP_CENTER_DIST = float(os.getenv("DEDUP_CENTER_DIST", "0.06"))
    DEDUP_MAX_GAP = int(os.getenv("DEDUP_MAX_GAP", "2"))

    # AI provider for the VLM cross-check and the LLM report (overridden in app.py)
    AI_PROVIDER = os.getenv("AI_PROVIDER", "openai")  # gemini / openai / none
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-6-luna")
    AI_RPM = int(os.getenv("AI_RPM", "8"))
    GEMINI_THINKING = "low"
    OPENAI_REASONING = "low"
    VLM_ENABLED = True
    VLM_WEIGHT = 0.4
    VLM_MIN_FUSED = 0.35
    VLM_AUTO_REJECT = False
    VLM_RELABEL = True
    VLM_ADD_MISSED = True
    VLM_MISSED_MIN_CONF = 0.6
    VLM_MAX_FRAMES = 30
    VLM_SEND_CROPS = True
    VLM_MAX_CROPS = 8
    VLM_EXTRA_INSTRUCTIONS = ""
    CHAT_ENABLED = True
    CHAT_MAX_IMAGES = 4
    VLM_CHECK_EMPTY_IMAGES = True
    LLM_REPORT_ENABLED = True
    REPORT_MAX_IMAGES = 8

    ALLOW_SIGNUP = _bool("ALLOW_SIGNUP", True)
    SEED_DEMO_DATA = _bool("SEED_DEMO_DATA", True)
    WTF_CSRF_TIME_LIMIT = None
