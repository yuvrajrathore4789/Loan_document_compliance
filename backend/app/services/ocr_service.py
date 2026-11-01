"""Text extraction: PyMuPDF for digital PDFs, OpenCV preprocessing + Tesseract for scans/images.

Digital PDF pages with too little embedded text fall back to OCR (rendered at OCR_DPI).
Per-page confidence is kept (None for embedded text, 0-1 for OCR).
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, UnidentifiedImageError

from app.config import get_settings

logger = logging.getLogger(__name__)
MIN_EMBEDDED_CHARS = 40  # fewer characters than this on a page => treat the page as scanned


class DocumentUnreadable(Exception):
    """Corrupted, encrypted, empty or otherwise unreadable document (a processing exception, not fraud)."""


class OcrUnavailable(DocumentUnreadable):
    """OCR was needed but the engine is missing/disabled."""


@dataclass
class PageText:
    page: int
    text: str
    method: str                      # pdf_text | ocr
    confidence: float | None = None  # 0-1 for OCR; None for embedded text
    rows: list[str] = field(default_factory=list)  # layout-aware lines (pdfplumber), digital PDFs only


@dataclass
class ExtractionResult:
    pages: list[PageText]
    page_count: int

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.pages)

    @property
    def method(self) -> str:
        methods = {p.method for p in self.pages}
        return "mixed" if len(methods) > 1 else (next(iter(methods)) if methods else "none")

    @property
    def ocr_confidence(self) -> float | None:
        confs = [p.confidence for p in self.pages if p.confidence is not None]
        return round(float(np.mean(confs)), 4) if confs else None


# ------------------------------------------------------------------ image preprocessing
def preprocess_for_ocr(img: Image.Image) -> np.ndarray:
    """Grayscale -> upscale small images -> denoise -> contrast (CLAHE) -> adaptive binarisation."""
    import cv2

    arr = np.array(img.convert("L"))
    h, w = arr.shape
    if max(h, w) < 1400:  # tiny images OCR poorly
        scale = 1400 / max(h, w)
        arr = cv2.resize(arr, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    arr = cv2.fastNlMeansDenoising(arr, None, h=12, templateWindowSize=7, searchWindowSize=21)
    arr = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(arr)
    return cv2.adaptiveThreshold(arr, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15)


def ocr_image(img: Image.Image) -> tuple[str, float]:
    """Return (text, mean word confidence 0-1). Raises OcrUnavailable if Tesseract is missing."""
    if not get_settings().ocr_enabled:
        raise OcrUnavailable("OCR is disabled (OCR_ENABLED=false).")
    try:
        import pytesseract
    except ImportError as exc:
        raise OcrUnavailable("pytesseract is not installed.") from exc
    try:
        data = pytesseract.image_to_data(Image.fromarray(preprocess_for_ocr(img)), lang="eng",
                                         config="--psm 6", output_type=pytesseract.Output.DICT)
    except (pytesseract.TesseractNotFoundError, FileNotFoundError) as exc:
        raise OcrUnavailable("Tesseract OCR engine is not installed.") from exc

    lines: dict[tuple[int, int, int], list[str]] = {}
    confs: list[float] = []
    for i, word in enumerate(data["text"]):
        word = (word or "").strip()
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if not word or conf < 0:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(word)
        confs.append(conf)
    text = "\n".join(" ".join(ws) for _, ws in sorted(lines.items()))
    return text, (float(np.mean(confs)) / 100.0 if confs else 0.0)


# ------------------------------------------------------------------ main entry points
def _pdf_rows(path: str, page_index: int) -> list[str]:
    """Row-grouped text via pdfplumber (keeps table rows on one line)."""
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            txt = pdf.pages[page_index].extract_text() or ""
        return [ln for ln in txt.splitlines() if ln.strip()]
    except Exception:  # noqa: BLE001 - optional enhancement only
        return []


def extract_pdf(path: str) -> ExtractionResult:
    import pymupdf as fitz  # PyMuPDF

    try:
        doc = fitz.open(path)
    except Exception as exc:  # noqa: BLE001
        raise DocumentUnreadable(f"PDF could not be opened (corrupted or unsupported): {type(exc).__name__}") from exc
    try:
        if doc.is_encrypted or doc.needs_pass:
            raise DocumentUnreadable("PDF is password-protected/encrypted and cannot be read.")
        if doc.page_count == 0:
            raise DocumentUnreadable("PDF has no pages.")
        if doc.page_count > 30:
            raise DocumentUnreadable("PDF has more than 30 pages; not supported in this demo.")
        pages: list[PageText] = []
        dpi = get_settings().ocr_dpi
        for i, page in enumerate(doc):
            try:
                text = page.get_text("text") or ""
            except Exception as exc:  # noqa: BLE001
                raise DocumentUnreadable(f"PDF page {i + 1} is damaged: {type(exc).__name__}") from exc
            if len(text.strip()) >= MIN_EMBEDDED_CHARS:
                pages.append(PageText(i + 1, text, "pdf_text", None, _pdf_rows(path, i)))
                continue
            pix = page.get_pixmap(dpi=dpi)  # scanned page: OCR fallback
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            otext, conf = ocr_image(img)
            pages.append(PageText(i + 1, otext, "ocr", conf, otext.splitlines()))
        return ExtractionResult(pages, doc.page_count)
    finally:
        doc.close()


def extract_image(path: str) -> ExtractionResult:
    try:
        with Image.open(path) as im:
            im.load()
            img = im.copy()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise DocumentUnreadable(f"Image could not be decoded: {type(exc).__name__}") from exc
    if img.width < 50 or img.height < 50:
        raise DocumentUnreadable("Image is too small to contain readable text.")
    text, conf = ocr_image(img)
    return ExtractionResult([PageText(1, text, "ocr", conf, text.splitlines())], 1)


def extract_text(path: str, content_type: str) -> ExtractionResult:
    """Dispatch on the (content-sniffed) type. Raises DocumentUnreadable for unreadable inputs."""
    result = extract_pdf(path) if content_type == "application/pdf" else extract_image(path)
    if not result.text.strip():
        raise DocumentUnreadable("No text could be extracted from the document (blank or unreadable).")
    return result
