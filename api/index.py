from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
import json

from lib.sanitizer import sanitize_geojson

app = FastAPI()


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/sanitize")
def sanitize_help():
    return {
        "message": "Use POST with multipart/form-data and a file field named 'file'."
    }


@app.post("/api/sanitize")
async def sanitize(file: UploadFile = File(...)):
    try:
        raw = await file.read()
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON file: {exc}")

    try:
        sanitized, report = sanitize_geojson(data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Sanitization failed: {exc}")

    return JSONResponse(
        content={
            "filename": file.filename,
            "sanitized": sanitized,
            "report": report,
        }
    )
