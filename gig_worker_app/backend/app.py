# app.py

from dotenv import load_dotenv
load_dotenv(".env.local")

"""
Rakshak AI - /seek POST returning final decision + relevant DB fields
Run deps:
    pip install fastapi uvicorn requests python-dotenv
Set env vars:
    EXTERNAL_PLATFORM_BASE_URL (e.g. http://10.221.246.153:5001)
    GEMINI_API_URL (optional)
    GEMINI_API_KEY (optional)  -> used as query param if present
Run:
    uvicorn app:app --reload --host 0.0.0.0 --port 8000
"""
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# ---------- config ----------
EXTERNAL_PLATFORM_BASE_URL = os.environ.get(
    "EXTERNAL_PLATFORM_BASE_URL", "http://10.221.246.153:5001"
).rstrip("/")
EXTERNAL_REQUEST_TIMEOUT = float(os.environ.get("EXTERNAL_REQUEST_TIMEOUT", "5.0"))

GEMINI_API_URL = os.environ.get("GEMINI_API_URL", "").rstrip("/")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")  # key-only setup supported
GEMINI_TIMEOUT = float(os.environ.get("GEMINI_TIMEOUT", "10.0"))

# Default Google REST endpoint for gemini-2.5-flash generateContent (used if GEMINI_API_URL empty)
DEFAULT_GEMINI_MODEL_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

BASE_WORKER_URL = f"{EXTERNAL_PLATFORM_BASE_URL}/workers"
SAVE_DIR = Path("seek_results")
SAVE_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Rakshak AI - /seek with relevant DB fields")

# ---------- request model ----------
class SeekPostRequest(BaseModel):
    workerId: str
    transcript: Optional[str] = None
    platformName: Optional[str] = None
    entities: Optional[Dict] = None

# ---------- helpers ----------
def utc_timestamp_str() -> str:
    return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

def save_json_to_file(payload: dict, worker_id: str) -> str:
    filename = f"seek_{worker_id}_{utc_timestamp_str()}.json"
    filepath = SAVE_DIR / filename
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return str(filepath)

def fetch_worker_from_external(worker_id: str) -> Any:
    url = f"{BASE_WORKER_URL}/{worker_id}"
    try:
        r = requests.get(url, timeout=EXTERNAL_REQUEST_TIMEOUT)
        r.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Failed to fetch from external ({url}): {e}")
    try:
        return r.json()
    except Exception:
        return {"_raw": r.text}

def extract_number_from_text(text: str) -> Optional[float]:
    m = re.search(r"(?<![\d.])(\d{1,6}(?:\.\d{1,2})?)(?![\d.])", text or "")
    if not m:
        return None
    try:
        return float(m.group(1))
    except:
        return None

def transcript_mentions_termination(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in ["terminate", "terminated", "suspend", "suspended", "deactivated", "blocked", "banned"])

def transcript_mentions_payout_or_paid(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in ["payout", "paid", "not paid", "unpaid", "payment", "paid ₹", "paid rs", "rupees", "rs."])

def transcript_mentions_rating_or_algo(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in ["rating", "algo", "algorithm", "penalty", "deduct", "deduction"])

# Local discrepancy check (company DB precedence)
def check_discrepancy(transcript: Optional[str], worker_db: dict) -> bool:
    """
    Return True if a local discrepancy exists that mandates an Invalid complaint.
    Simple heuristics:
      - Transcript claims termination/suspension but DB shows is_terminated == 0
      - Transcript claims payout amount that contradicts latest platform payout by >100
      - Transcript claims 'no notice' but DB contains termination_reason_text
      - Transcript claims 'not paid' but orders show payment_compliant==1 for relevant orders
    """
    t = (transcript or "").lower()

    term = worker_db.get("termination_status") or worker_db.get("terminationStatus") or {}
    is_terminated = None
    if isinstance(term, dict) and "is_terminated" in term:
        try:
            is_terminated = int(term.get("is_terminated", 0))
        except:
            is_terminated = None

    # 1) termination contradiction
    if transcript_mentions_termination(transcript) and is_terminated is not None and is_terminated == 0:
        return True

    # 2) payout contradiction
    claimed_amount = extract_number_from_text(transcript)
    payouts = worker_db.get("payouts") or (worker_db.get("worker") or {}).get("payouts") or []
    if claimed_amount is not None and isinstance(payouts, list) and payouts:
        try:
            latest_amt = float(payouts[0].get("amount", 0))
            if abs(latest_amt - claimed_amount) > 100:
                return True
        except Exception:
            pass

    # 3) 'no notice' vs termination_reason_text
    if any(kw in t for kw in ["no notice", "sudden", "immediately", "without notice"]):
        if isinstance(term, dict) and term.get("termination_reason_text"):
            return True

    # 4) not paid vs payment_compliant == 1 for orders
    if any(kw in t for kw in ["not paid", "didn't get paid", "unpaid", "not received", "not paid to me"]):
        orders = worker_db.get("orders") or []
        if isinstance(orders, list) and orders:
            has_payment_flags = any("payment_compliant" in o for o in orders)
            if has_payment_flags:
                all_compliant = all((o.get("payment_compliant") in (1, True, "1")) for o in orders if "payment_compliant" in o)
                if all_compliant:
                    return True

    return False

# Extract relevant DB fields based on transcript
def get_relevant_db_fields(transcript: Optional[str], worker_db: dict) -> Dict[str, Any]:
    t = (transcript or "").lower()
    relevant: Dict[str, Any] = {}

    # termination-related
    if transcript_mentions_termination(transcript) or "termination" in t or "appeal" in t:
        if "termination_status" in worker_db:
            relevant["termination_status"] = worker_db["termination_status"]
        if "termination_logs" in worker_db:
            relevant["termination_logs"] = worker_db["termination_logs"]

    # payouts / payment issues
    if transcript_mentions_payout_or_paid(transcript) or any(k in t for k in ["payout", "paid", "unpaid", "payment"]):
        if "payouts" in worker_db:
            relevant["payouts"] = worker_db["payouts"]
        if "orders" in worker_db:
            # include orders that look recent or have payment flags
            orders = worker_db["orders"]
            # include all orders if small, otherwise filter to those with payment flags or recent date
            if isinstance(orders, list) and len(orders) > 10:
                filtered = [o for o in orders if o.get("payment_compliant") in (0, "0", False) or "reduction_reason" in o or "payout_amount" in o]
                relevant["orders"] = filtered or orders[:10]
            else:
                relevant["orders"] = orders

    # rating/algorithm/penalty issues
    if transcript_mentions_rating_or_algo(transcript) or any(k in t for k in ["rating", "algorithm", "algo", "penalty", "deduct", "deduction"]):
        if "penalties" in worker_db:
            relevant["penalties"] = worker_db["penalties"]
        if "orders" in worker_db:
            relevant.setdefault("orders", worker_db["orders"])

    # generic / fallback fields that may help frontend or UI
    # always include basic worker info if present
    if "worker" in worker_db:
        relevant.setdefault("worker", worker_db["worker"])
    else:
        # some APIs might put top-level worker fields instead
        for k in ("name", "phone", "email", "joined_at", "current_status"):
            if k in worker_db:
                relevant.setdefault("worker", {})
                relevant["worker"][k] = worker_db[k]

    # include review counts if complaint mentions ratings or reviews
    if "review" in t or transcript_mentions_rating_or_algo(transcript):
        if "review_counts" in worker_db:
            relevant["review_counts"] = worker_db["review_counts"]

    return relevant

# Call Gemini API (flexible auth)
def call_gemini_api(text: str, db_payload: dict) -> Dict[str, Any]:
    """
    Calls Gemini 2.5 Flash generateContent endpoint.
    Returns {"ok": True, "decision": "...", "raw": <resp_json>} on success
    or {"ok": False, "error": "...", "raw": <resp_json_or_text>} on failure.
    """
    # changed guard: require only the key; URL optional (uses default if empty)
    if not GEMINI_API_KEY:
        return {"ok": False, "error": "Gemini not configured (GEMINI_API_KEY missing)"}

    base_url = GEMINI_API_URL or DEFAULT_GEMINI_MODEL_URL
    url = f"{base_url.rstrip('/') + ('?key=' + GEMINI_API_KEY)}"

    # Build a compact prompt: instruct model to consider Karnataka Gig Workers Act + precedence rule,
    # and reply with exactly either: Valid complaint  OR  Invalid complaint
    instruction = (
        "You are a legal assistant. Given a gig-worker complaint (TEXT) and a company database (DB), "
        "decide whether the complaint is VALID or INVALID under the Karnataka Gig Workers Act.\n\n"
        "Important rules:\n"
        "1) If any contradiction exists between the worker's claim and the company DB, the DB has precedence => INVALID.\n"
        "2) Otherwise evaluate lawfully and return only one of these exact phrases: \"Valid complaint\" or \"Invalid complaint\".\n\n"
        "Now evaluate and answer with only the phrase (no explanation):\n\n"
        "COMPLAINT:\n"
        f"{text}\n\n"
        "COMPANY_DB:\n"
        f"{json.dumps(db_payload, ensure_ascii=False, indent=2)}\n\n"
        "Answer:"
    )

    # Gemini generateContent expects a JSON body containing 'messages' or 'contents' depending on
    # the REST shape; using the widely-supported "contents" / "candidates" extraction method below.
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": instruction}
                ]
            }
        ],
        # you can tune temperature, maxOutputTokens etc if needed:
        "temperature": 0.0,
        "maxOutputTokens": 128,
    }

    try:
        resp = requests.post(url, json=payload, timeout=GEMINI_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        return {"ok": False, "error": str(e)}

    # Try to extract decision text:
    try:
        j = resp.json()
    except Exception:
        text_resp = (resp.text or "").strip()
        return {"ok": True, "decision": text_resp, "raw": resp.text}

    # Typical field to look for: 'candidates' or 'outputs' or 'candidates' -> content -> parts
    # We attempt a few known shapes
    try:
        # shape: { "candidates": [ { "content": { "parts": ["..."] } } ] }
        if isinstance(j, dict) and "candidates" in j and j["candidates"]:
            cand = j["candidates"][0]
            # some shapes: cand["content"]["parts"][0] OR cand["content"]["parts"]
            txt = None
            if isinstance(cand.get("content"), dict):
                parts = cand["content"].get("parts") or cand["content"].get("text") or []
                if isinstance(parts, list) and parts:
                    txt = parts[0]
            if not txt and isinstance(cand.get("content"), str):
                txt = cand.get("content")
            if txt:
                return {"ok": True, "decision": txt.strip(), "raw": j}
        # alternate shape: { "outputs": [ { "content": [ { "type":"message_text", "text":"..." } ] } ] }
        if isinstance(j, dict) and "outputs" in j and j["outputs"]:
            out = j["outputs"][0]
            # search for text inside output
            content = out.get("content") or []
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and "text" in c:
                        return {"ok": True, "decision": c["text"].strip(), "raw": j}
        # last resort: plain top-level text or nested field
        # try to stringify the most-likely text
        fallback = json.dumps(j)[:2000]
        return {"ok": True, "decision": fallback, "raw": j}
    except Exception as e:
        return {"ok": False, "error": f"Failed to parse Gemini response: {e}", "raw": j}

# Local fallback decision if Gemini not configured or errors
def fallback_local_decision(transcript: str, worker_db: dict) -> str:
    t = (transcript or "").lower()
    triggers = ["suspend", "suspended", "terminated", "termination", "no notice", "deduct", "penalty", "reduced", "unpaid", "not paid", "appeal"]
    if any(w in t for w in triggers):
        term = worker_db.get("termination_status") or {}
        if isinstance(term, dict) and term.get("is_terminated") in (0, "0", False):
            return "Invalid complaint"
        return "Valid complaint"
    return "Invalid complaint"

# ---------- endpoint ----------
@app.post("/seek")
def seek_post(body: SeekPostRequest):
    worker_id = body.workerId
    if not worker_id:
        raise HTTPException(status_code=400, detail="workerId is required")

    # 1) fetch DB
    try:
        external_data = fetch_worker_from_external(worker_id)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    # 2) save JSON file (meta + db)
    payload = {
        "meta": {
            "called_at": datetime.utcnow().isoformat() + "Z",
            "requested_worker": worker_id,
            "transcript": body.transcript,
            "platformName": body.platformName,
            "entities": body.entities,
        },
        "worker_db": external_data
    }
    try:
        saved_path = save_json_to_file(payload, worker_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    # 3) local discrepancy check (company DB precedence)
    if check_discrepancy(body.transcript, external_data):
        # extract relevant fields for frontend and return Invalid
        relevant = get_relevant_db_fields(body.transcript, external_data)
        return {"final_decision": "Invalid complaint", "relevant_db": relevant}

    # 4) call gemini if available
    gemini_resp = call_gemini_api(body.transcript or "", payload)
    if gemini_resp.get("ok"):
        dec = str(gemini_resp.get("decision", "")).strip()
        if dec.lower().startswith("valid"):
            final = "Valid complaint"
        elif dec.lower().startswith("invalid"):
            final = "Invalid complaint"
        elif "invalid" in dec.lower():
            final = "Invalid complaint"
        elif "valid" in dec.lower():
            final = "Valid complaint"
        else:
            final = fallback_local_decision(body.transcript or "", external_data)
        relevant = get_relevant_db_fields(body.transcript, external_data)
        return {"final_decision": final, "relevant_db": relevant, "gemini_raw": gemini_resp.get("raw")}
    else:
        # gemini failed/unconfigured -> local fallback
        final = fallback_local_decision(body.transcript or "", external_data)
        relevant = get_relevant_db_fields(body.transcript, external_data)
        return {"final_decision": final, "relevant_db": relevant, "gemini_error": gemini_resp.get("error")}

# ---------- health ----------
@app.get("/__health")
def health():
    return {
        "ok": True,
        "external_platform_base_url": EXTERNAL_PLATFORM_BASE_URL,
        "gemini_configured": bool(GEMINI_API_KEY),
        "save_dir": str(SAVE_DIR),
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)