# backend/app.py
"""
Friend's FastAPI server for simulated platform data.

Run deps:
 pip install fastapi uvicorn

Run for LAN access (IMPORTANT):
 uvicorn app:app --reload --host 0.0.0.0 --port 5001

Note:
 - Make sure the machine's firewall allows inbound TCP on port 5001.
 - If running in a VM/container, ensure port mapping is configured.
"""
from fastapi import FastAPI, Body, Path, status
from fastapi.responses import JSONResponse
from typing import Any, Dict

# Import utils (assumes you're running app.py from the backend folder)
from Database import utils

app = FastAPI(title="gigworkers-sim-backend")

from fastapi.middleware.cors import CORSMiddleware

# add after creating app
# DEV: allow_origins=["*"] so it is reachable from browser/dev UIs on LAN.
# In production, replace ["*"] with specific allowed origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _file_error_response(e: FileNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=500, content={"error": str(e)})


# ---------------------------
# Health / root
# ---------------------------
@app.get("/", status_code=status.HTTP_200_OK)
def root() -> Dict[str, Any]:
    return {"ok": True, "service": "gigworkers-sim-backend"}


# ---------------------------
# DB print / read endpoints
# ---------------------------
@app.get("/db/print", status_code=status.HTTP_200_OK)
def api_print_database():
    try:
        data = utils.print_database()
        return JSONResponse(status_code=200, content=data)
    except FileNotFoundError as e:
        return _file_error_response(e)


@app.get("/workers", status_code=status.HTTP_200_OK)
def api_list_workers():
    try:
        workers = utils.list_workers()
        return JSONResponse(status_code=200, content=workers)
    except FileNotFoundError as e:
        return _file_error_response(e)


@app.get("/workers/{worker_id}", status_code=status.HTTP_200_OK)
def api_get_worker_summary(worker_id: str = Path(...)):
    try:
        summary = utils.get_worker_summary(worker_id)
        # preserve same behaviour as Flask: if summary["worker"] is None -> 404
        if isinstance(summary, dict) and summary.get("worker") is None:
            return JSONResponse(status_code=404, content={"error": "worker not found"})
        return JSONResponse(status_code=200, content=summary)
    except FileNotFoundError as e:
        return _file_error_response(e)


# ---------------------------
# Worker CRUD
# ---------------------------
@app.post("/workers", status_code=status.HTTP_201_CREATED)
def api_add_worker(payload: Dict = Body(...)):
    if not payload:
        return JSONResponse(status_code=400, content={"error": "JSON body required"})
    if "worker_id" not in payload:
        return JSONResponse(status_code=400, content={"error": "worker_id required"})

    try:
        ok = utils.add_worker(payload)
        if ok:
            return JSONResponse(status_code=201, content={"ok": True})
        else:
            return JSONResponse(status_code=409, content={"ok": False, "error": "worker_id already exists"})
    except FileNotFoundError as e:
        return _file_error_response(e)


@app.delete("/workers/{worker_id}", status_code=status.HTTP_200_OK)
def api_remove_worker(worker_id: str = Path(...)):
    try:
        deleted = utils.remove_worker(worker_id)
        if deleted:
            return JSONResponse(status_code=200, content={"ok": True})
        else:
            return JSONResponse(status_code=404, content={"ok": False, "error": "worker not found"})
    except FileNotFoundError as e:
        return _file_error_response(e)


# ---------------------------
# Orders CRUD
# ---------------------------
@app.post("/orders", status_code=status.HTTP_201_CREATED)
def api_add_order(payload: Dict = Body(...)):
    if not payload or "order_id" not in payload or "worker_id" not in payload:
        return JSONResponse(
            status_code=400, content={"error": "order_id and worker_id required"}
        )
    try:
        ok = utils.add_order(payload)
        if ok:
            return JSONResponse(status_code=201, content={"ok": True})
        else:
            return JSONResponse(
                status_code=409, content={"ok": False, "error": "order_id already exists or FK failed"}
            )
    except FileNotFoundError as e:
        return _file_error_response(e)


@app.delete("/orders/{order_id}", status_code=status.HTTP_200_OK)
def api_remove_order(order_id: str = Path(...)):
    try:
        deleted = utils.remove_order(order_id)
        if deleted:
            return JSONResponse(status_code=200, content={"ok": True})
        else:
            return JSONResponse(status_code=404, content={"ok": False, "error": "order not found"})
    except FileNotFoundError as e:
        return _file_error_response(e)


# ---------------------------
# Termination status endpoints
# ---------------------------
@app.post("/termination_status", status_code=status.HTTP_200_OK)
def api_add_update_termination_status(payload: Dict = Body(...)):
    if not payload or "worker_id" not in payload:
        return JSONResponse(status_code=400, content={"error": "JSON body with worker_id required"})
    try:
        utils.add_or_update_termination_status(payload)
        return JSONResponse(status_code=200, content={"ok": True})
    except FileNotFoundError as e:
        return _file_error_response(e)


@app.delete("/termination_status/{worker_id}", status_code=status.HTTP_200_OK)
def api_remove_termination_status(worker_id: str = Path(...)):
    try:
        deleted = utils.remove_termination_status(worker_id)
        if deleted:
            return JSONResponse(status_code=200, content={"ok": True})
        else:
            return JSONResponse(status_code=404, content={"ok": False, "error": "termination_status not found"})
    except FileNotFoundError as e:
        return _file_error_response(e)


# ---------------------------
# Termination logs endpoints
# ---------------------------
@app.post("/termination_logs", status_code=status.HTTP_201_CREATED)
def api_add_termination_log(payload: Dict = Body(...)):
    if not payload or "worker_id" not in payload:
        return JSONResponse(status_code=400, content={"error": "JSON body with worker_id required"})
    try:
        log_id = utils.add_termination_log(payload)
        return JSONResponse(status_code=201, content={"ok": True, "log_id": log_id})
    except FileNotFoundError as e:
        return _file_error_response(e)


@app.delete("/termination_logs/{log_id}", status_code=status.HTTP_200_OK)
def api_remove_termination_log(log_id: int = Path(...)):
    try:
        deleted = utils.remove_termination_log(log_id)
        if deleted:
            return JSONResponse(status_code=200, content={"ok": True})
        else:
            return JSONResponse(status_code=404, content={"ok": False, "error": "log not found"})
    except FileNotFoundError as e:
        return _file_error_response(e)


# ---------------------------
# Review counts endpoints
# ---------------------------
@app.post("/review_counts", status_code=status.HTTP_200_OK)
def api_add_update_review_counts(payload: Dict = Body(...)):
    if not payload or "worker_id" not in payload:
        return JSONResponse(status_code=400, content={"error": "JSON body with worker_id required"})
    try:
        utils.add_or_update_review_counts(payload)
        return JSONResponse(status_code=200, content={"ok": True})
    except FileNotFoundError as e:
        return _file_error_response(e)


@app.delete("/review_counts/{worker_id}", status_code=status.HTTP_200_OK)
def api_remove_review_counts(worker_id: str = Path(...)):
    try:
        deleted = utils.remove_review_counts(worker_id)
        if deleted:
            return JSONResponse(status_code=200, content={"ok": True})
        else:
            return JSONResponse(status_code=404, content={"ok": False, "error": "review_counts not found"})
    except FileNotFoundError as e:
        return _file_error_response(e)

# --- paste into backend/app.py alongside other worker routes ---
from fastapi import HTTPException

@app.post("/workers/{worker_id}/fields", status_code=status.HTTP_200_OK)
def api_modify_worker_fields(worker_id: str = Path(...), payload: Dict = Body(...)):
    """
    payload:
      { "op": "add" | "remove", "field": "<field_name>", "value": <any> }
    This modifies arbitrary fields inside a worker record (not DB schema).
    """
    if not payload or "op" not in payload or "field" not in payload:
        return JSONResponse(status_code=400, content={"error": "op and field required"})

    op = payload["op"]
    field = payload["field"]
    try:
        if op == "add":
            value = payload.get("value")
            ok = utils.add_field_to_worker(worker_id, field, value)
            if ok:
                return JSONResponse(status_code=200, content={"ok": True})
            else:
                return JSONResponse(status_code=404, content={"ok": False, "error": "worker not found"})
        elif op == "remove":
            ok = utils.remove_field_from_worker(worker_id, field)
            if ok:
                return JSONResponse(status_code=200, content={"ok": True})
            else:
                return JSONResponse(status_code=404, content={"ok": False, "error": "worker or field not found"})
        else:
            return JSONResponse(status_code=400, content={"error": "unknown op"})
    except FileNotFoundError as e:
        return _file_error_response(e)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
# --- end paste --- 