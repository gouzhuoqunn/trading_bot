from __future__ import annotations

import re
from typing import Sequence

import numpy as np
import pytesseract
from pytesseract import TesseractNotFoundError
from PIL import Image


class OcrEngine:
    """Lightweight OCR wrapper using pytesseract."""

    def __init__(
        self,
        *,
        address_pattern: str = r"0[xX][a-fA-F0-9]{40}",
        tesseract_cmd: str | None = None,
        language: str = "eng",
    ) -> None:
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        self.address_pattern = re.compile(address_pattern)
        self._loose_address_pattern = re.compile(
            r"0\s*[xX](?:\s*[0-9a-fA-F]){40}"
        )
        self._language = language

    def is_ready(self) -> bool:
        try:
            pytesseract.get_tesseract_version()
        except (TesseractNotFoundError, FileNotFoundError):
            return False
        return True

    def ensure_ready(self) -> None:
        if not self.is_ready():
            raise RuntimeError(
                "Tesseract OCR executable not found. Install Tesseract or set TESSERACT_CMD to its path."
            )

    def run_ocr(self, image: np.ndarray) -> str:
        pil_image = Image.fromarray(image)
        return pytesseract.image_to_string(pil_image, lang=self._language)

    def extract_addresses(self, text: str) -> Sequence[str]:
        if not text:
            return []
        addresses = list(dict.fromkeys(self.address_pattern.findall(text)))
        if addresses:
            return [addr.lower() for addr in addresses]

        loose_matches = self._loose_address_pattern.finditer(text)
        normalized: list[str] = []
        seen: set[str] = set()
        for match in loose_matches:
            raw = match.group(0)
            cleaned = re.sub(r"\s+", "", raw).lower()
            if len(cleaned) != 42:
                continue
            if not cleaned.startswith("0x"):
                continue
            hex_part = cleaned[2:]
            if not all(ch in "0123456789abcdef" for ch in hex_part):
                continue
            if cleaned not in seen:
                seen.add(cleaned)
                normalized.append(cleaned)
        return normalized
