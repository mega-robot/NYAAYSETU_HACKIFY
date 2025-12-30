import os
import io
import json
import re
import textwrap
import requests
from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

# ---------------------------
# GEMINI CONFIG
# ---------------------------
GEMINI_API_KEY = "AIzaSyDefNzqSnBkkLJkhhq6wvbYhfOE2cArC6o"

PREFERRED_MODELS = [
    "models/gemini-2.5-flash",
    "models/gemini-2.5-pro",
    "models/gemini-pro-latest",
    "models/gemini-flash-latest",
]

LIST_MODELS_URL = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
GEMINI_URL = None
SELECTED_MODEL = None

def fetch_models_list():
    r = requests.get(LIST_MODELS_URL, timeout=15)
    r.raise_for_status()
    return r.json()

def pick_gemini_model():
    global GEMINI_URL, SELECTED_MODEL
    data = fetch_models_list()
    models = {m["name"]: m for m in data.get("models", [])}

    for m in PREFERRED_MODELS:
        if m in models and "generateContent" in models[m].get("supportedGenerationMethods", []):
            SELECTED_MODEL = m
            GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/{m}:generateContent?key={GEMINI_API_KEY}"
            return

    raise RuntimeError("No valid Gemini model found")

pick_gemini_model()

# ---------------------------
# FastAPI setup
# ---------------------------
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------
# Prompt builder
# ---------------------------
def build_prompt(issue_text, proof_text, max_words=450):
    return f"""
SYSTEM: Draft a one-page legal summary. No hallucinations. Keep factual.

WORKER ISSUE:
{issue_text}

PROOF (text evidence):
{proof_text}

RULES:
- Sections: HEADER:, FACTS:, LEGAL CONCERNS:, RELIEF SOUGHT:, ATTACHMENTS:
- Use bullet points
- Max {max_words} words
- No markdown formatting
""".strip()

# ---------------------------
# Gemini Call
# ---------------------------
def call_gemini(prompt):
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 2000}
    }
    headers = {"Content-Type": "application/json"}
    r = requests.post(GEMINI_URL, json=body, headers=headers, timeout=60)
    r.raise_for_status()
    data = r.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]

# ---------------------------
# PDF Creation
# ---------------------------
def render_pdf(text: str):
    buf = io.BytesIO()
    page_w, page_h = A4
    margin = 15 * mm
    usable_w = page_w - 2 * margin

    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(page_w / 2, page_h - margin, "Worker Statement")
    c.setFont("Helvetica", 11)

    wrapper = textwrap.TextWrapper(width=95)
    y = page_h - margin - 30

    for line in text.split("\n"):
        wrapped = wrapper.wrap(line)
        for w in wrapped:
            if y < margin:
                c.showPage()
                y = page_h - margin
                c.setFont("Helvetica", 11)
            c.drawString(margin, y, w)
            y -= 14

    c.showPage()
    c.save()
    buf.seek(0)
    return buf

# ---------------------------
# MAIN API: /generate-pdf
# ---------------------------
@app.post("/generate-pdf")
async def generate_pdf(
    explanation: str = Form(...),
    proof: str = Form(...)
):
    prompt = build_prompt(explanation, proof)
    model_output = call_gemini(prompt)

    pdf_bytes = render_pdf(model_output)

    return StreamingResponse(
        pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=worker_statement.pdf"}
    )


@app.get("/health")
def health():
    return {"status": "ok", "model": SELECTED_MODEL}
 