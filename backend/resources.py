from pathlib import Path
from pypdf import PdfReader
import json

# Local dev: twin/data. Lambda package: ./data next to resources.py
_DATA_CANDIDATES = [
    Path(__file__).resolve().parent / "data",
    Path(__file__).resolve().parent.parent / "data",
]
DATA_DIR = next((p for p in _DATA_CANDIDATES if p.exists()), _DATA_CANDIDATES[0])

# Read LinkedIn PDF
try:
    reader = PdfReader(DATA_DIR / "linkedin.pdf")
    linkedin = ""
    for page in reader.pages:
        text = page.extract_text()
        if text:
            linkedin += text
except FileNotFoundError:
    linkedin = "LinkedIn profile not available"

# Read other data files
with open(DATA_DIR / "summary.txt", "r", encoding="utf-8") as f:
    summary = f.read()

with open(DATA_DIR / "style.txt", "r", encoding="utf-8") as f:
    style = f.read()

with open(DATA_DIR / "facts.json", "r", encoding="utf-8") as f:
    facts = json.load(f)