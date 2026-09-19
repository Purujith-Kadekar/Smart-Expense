"""
Pluggable offline OCR engine.

Two backends, selected by the OCR_ENGINE environment variable:

    OCR_ENGINE=easyocr    (default)  — EasyOCR, PyTorch-based, higher accuracy
    OCR_ENGINE=tesseract             — pytesseract + the Tesseract binary

Both run 100% locally. Neither makes a network call at inference time, and
neither touches AWS Textract, Rekognition, or any paid API.

IMPORTANT — EasyOCR model weights
---------------------------------
EasyOCR downloads its detection/recognition weights (~100 MB) on first use.
That download happens at DOCKER BUILD time in backend/Dockerfile, into
EASYOCR_MODULE_PATH, so the running container never needs network access.
If you run this outside Docker, the first call will download the weights
once and cache them in ~/.EasyOCR.

The Reader object is expensive to construct (it loads the torch models into
memory), so it is built once and cached at module scope. Under gunicorn this
means one Reader per worker process.
"""

import os
import threading

# Language list for EasyOCR. Keep it to English — adding languages multiplies
# both the model download size and the memory footprint.
EASYOCR_LANGS = [lang.strip() for lang in os.environ.get("OCR_LANGS", "en").split(",") if lang.strip()]

_reader = None
_reader_lock = threading.Lock()


def get_engine_name():
    """Return the configured engine name, normalised and validated.

    Falls back to "easyocr" for an unrecognised value rather than raising —
    a typo in an env var should not take the whole ingestion path down.
    """
    name = os.environ.get("OCR_ENGINE", "easyocr").strip().lower()
    if name in {"easyocr", "tesseract", "pytesseract"}:
        return "tesseract" if name == "pytesseract" else name
    print(f"[ocr] Unknown OCR_ENGINE={name!r} — falling back to 'easyocr'")
    return "easyocr"


def _get_easyocr_reader():
    """Build (once) and return the cached EasyOCR Reader.

    `download_enabled=False` is deliberate: the weights are baked into the
    image at build time. If they are missing we want a loud, obvious error
    instead of a silent 100 MB download attempt that hangs a container with
    no egress.
    """
    global _reader
    if _reader is not None:
        return _reader
    with _reader_lock:
        # Re-check inside the lock — two threads can both pass the check above.
        if _reader is not None:
            return _reader
        import easyocr
        model_dir = os.environ.get("EASYOCR_MODULE_PATH") or os.environ.get(
            "EASYOCR_MODEL_PATH"
        )
        kwargs = {"gpu": False, "verbose": False}
        if model_dir:
            kwargs["model_storage_directory"] = os.path.join(model_dir, "model")
            kwargs["user_network_directory"] = os.path.join(model_dir, "user_network")
            kwargs["download_enabled"] = False
        print(f"[ocr] Initialising EasyOCR Reader (langs={EASYOCR_LANGS}, cpu)")
        _reader = easyocr.Reader(EASYOCR_LANGS, **kwargs)
        return _reader


def _ocr_easyocr(image_path):
    """Run EasyOCR and return the recognised text as newline-joined lines.

    EasyOCR returns a list of (bbox, text, confidence) tuples in roughly
    top-to-bottom reading order. We keep only the text and join with
    newlines so the output shape matches pytesseract's, which is what
    parse_ocr.parse_ocr_text() expects (it splits on newlines to find the
    vendor on the first meaningful line).
    """
    reader = _get_easyocr_reader()
    results = reader.readtext(image_path, detail=1, paragraph=False)
    lines = []
    for item in results:
        # detail=1 → (bbox, text, confidence); guard against shape changes.
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            text = item[1]
        else:
            text = str(item)
        if text and str(text).strip():
            lines.append(str(text).strip())
    return "\n".join(lines)


def _ocr_tesseract(image_path):
    """Run pytesseract and return the raw text string."""
    import pytesseract
    from PIL import Image

    with Image.open(image_path) as img:
        return pytesseract.image_to_string(img)


def run_ocr(image_path):
    """Extract text from the image at `image_path`.

    Returns the raw text, or an empty string if the configured engine is
    unavailable. An empty string is graceful degradation, not a crash: the
    parser falls back to vendor="Unknown", amount=0, date=today, and the
    record still lands in DynamoDB so the user sees their upload.

    Raises nothing — every failure path is logged and returns "".
    """
    engine = get_engine_name()
    try:
        if engine == "easyocr":
            return _ocr_easyocr(image_path)
        return _ocr_tesseract(image_path)
    except ImportError as exc:
        print(f"[ocr] Engine {engine!r} is not installed: {exc}")
        print("[ocr] Install it with:  pip install -r lambda/requirements.txt")
        return ""
    except Exception as exc:
        print(f"[ocr] Engine {engine!r} failed on {image_path}: {exc}")
        return ""
