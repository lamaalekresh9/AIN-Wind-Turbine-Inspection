"""Ain: AI wind turbine blade inspection.

Run:  python app.py      then open http://127.0.0.1:5000
API keys go in the .env file (GEMINI_API_KEY / OPENAI_API_KEY), never in this file.
"""
from core import create_app

# ============================ YOLO model ============================
MODEL_PATH = "models/best.pt"   # trained YOLO weights

CONFIDENCE = 0.25        # default confidence threshold (0.05 to 0.95)
                         # higher = fewer, surer boxes / lower = more boxes, more false alarms
                         # used for new inspections and the Live detection page
                         # (users can still adjust it per inspection or live)

IOU = 0.7                # NMS IoU: lower merges overlapping boxes more aggressively
MAX_DETECTIONS = 300     # max boxes per image
IMAGE_SIZE = 1024        # inference size: the YOLO26l model was trained at 1024
DEVICE = ""              # "" = auto, "cpu", or "0" for the first GPU

BLADE_SEG_MODEL_PATH = ""   # optional YOLO-seg blade model for masking; "" = off

# ===================== AI provider (VLM + LLM report) =====================
AI_PROVIDER = "openai"            # "openai", "gemini" (free tier), or "none" (offline templates only)
OPENAI_MODEL = "gpt-6-luna"       # cheapest OpenAI model with image input ($0.10 / $0.50 per 1M tokens)
OPENAI_REASONING = "low"          # none / low / medium / high: low is fast and cheap
GEMINI_MODEL = "gemini-3.8-flash" # used only when AI_PROVIDER = "gemini"
GEMINI_THINKING = "low"
AI_REQUESTS_PER_MINUTE = 60       # OpenAI paid limits are far higher; use 8 for the Gemini free tier

# ----- 1) VLM cross-check of YOLO detections -----
VLM_ENABLED = True       # ask the VLM to confirm / reject / relabel every YOLO box
VLM_WEIGHT = 0.4         # combined score = (1 - VLM_WEIGHT) * YOLO + VLM_WEIGHT * VLM
VLM_MIN_COMBINED = 0.35  # below this, a box the VLM rejects counts as a likely false alarm
VLM_AUTO_REJECT = False  # True = pre-reject likely false alarms (reviewer can still restore them)
VLM_RELABEL = True       # let the VLM correct the class when it is more confident than YOLO
VLM_ADD_MISSED = True    # add clear defects YOLO missed (marked "Found by VLM", still need review)
VLM_MISSED_MIN_CONF = 0.6
VLM_MAX_FRAMES = 30      # max images/frames sent to the VLM per inspection (protects the free quota)
VLM_SEND_CROPS = True    # also send a zoomed crop of every box (much better on small cracks and pits)
VLM_MAX_CROPS = 8
# Extra instructions for the VLM, in plain English. The full class guide (what each defect looks like and what
# it must not be confused with) is in core/services/vlm_prompts.py.
VLM_EXTRA_INSTRUCTIONS = """
These images come from onshore wind farms in Saudi Arabia: expect sand and dust on the blades; dust alone is not a defect.
"""

# ----- 2) LLM inspection report -----
LLM_REPORT_ENABLED = True  # False = always use the offline Arabic templates
REPORT_MAX_IMAGES = 8      # evidence crops sent to the LLM with the report request

# ----- 3) AI chat about an inspection -----
CHAT_ENABLED = True      # "Ask Ain" tab: ask anything about the detections and the VLM results
CHAT_MAX_IMAGES = 4      # evidence crops sent with each question
# ========================================================================

app = create_app({
    "MODEL_PATH": MODEL_PATH,
    "DEFAULT_CONF": CONFIDENCE,
    "NMS_IOU": IOU,
    "MAX_DETECTIONS": MAX_DETECTIONS,
    "MODEL_IMGSZ": IMAGE_SIZE,
    "MODEL_DEVICE": DEVICE,
    "BLADE_SEG_MODEL_PATH": BLADE_SEG_MODEL_PATH,
    "AI_PROVIDER": AI_PROVIDER,
    "GEMINI_MODEL": GEMINI_MODEL,
    "OPENAI_MODEL": OPENAI_MODEL,
    "AI_RPM": AI_REQUESTS_PER_MINUTE,
    "GEMINI_THINKING": GEMINI_THINKING,
    "OPENAI_REASONING": OPENAI_REASONING,
    "VLM_ENABLED": VLM_ENABLED,
    "VLM_WEIGHT": VLM_WEIGHT,
    "VLM_MIN_FUSED": VLM_MIN_COMBINED,
    "VLM_AUTO_REJECT": VLM_AUTO_REJECT,
    "VLM_RELABEL": VLM_RELABEL,
    "VLM_ADD_MISSED": VLM_ADD_MISSED,
    "VLM_MISSED_MIN_CONF": VLM_MISSED_MIN_CONF,
    "VLM_MAX_FRAMES": VLM_MAX_FRAMES,
    "VLM_SEND_CROPS": VLM_SEND_CROPS,
    "VLM_MAX_CROPS": VLM_MAX_CROPS,
    "VLM_EXTRA_INSTRUCTIONS": VLM_EXTRA_INSTRUCTIONS,
    "CHAT_ENABLED": CHAT_ENABLED,
    "CHAT_MAX_IMAGES": CHAT_MAX_IMAGES,
    "LLM_REPORT_ENABLED": LLM_REPORT_ENABLED,
    "REPORT_MAX_IMAGES": REPORT_MAX_IMAGES,
})

if __name__ == "__main__":
    # use_reloader=False keeps background analysis threads from being started twice
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False, threaded=True)
