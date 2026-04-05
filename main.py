from fastapi import FastAPI, UploadFile, File, Form, Body
from fastapi.middleware.cors import CORSMiddleware
import boto3
import os
import json

# -----------------------------
# YMPÄRISTÖMUUTTUJAT (Railway)
# -----------------------------

CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")
R2_BUCKET = os.getenv("R2_BUCKET_NAME")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")

print("DEBUG: BUCKET =", R2_BUCKET)
print("DEBUG: ENDPOINT =", R2_ENDPOINT)

# R2-yhteys (boto3)
session = boto3.session.Session()
s3 = session.client(
    service_name="s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY
)

# -----------------------------
# FASTAPI-APP + CORS
# -----------------------------

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # Cloudflare Pages domain hyväksytään
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True
)

# -----------------------------
# HELPERS
# -----------------------------

def r2_put_json(bucket_key: str, data: dict):
    """Tallenna JSON-objekti R2:een bytes-muodossa"""
    body = json.dumps(data, ensure_ascii=False, indent=4).encode("utf-8")

    s3.put_object(
        Bucket=R2_BUCKET,
        Key=bucket_key,
        Body=body,
        ContentType="application/json"
    )

def r2_get_json(bucket_key: str):
    """Hae JSON R2:sta"""
    try:
        obj = s3.get_object(Bucket=R2_BUCKET, Key=bucket_key)
        return json.loads(obj["Body"].read())
    except Exception:
        return None

# -----------------------------
# 1) METADATA (kohteen tiedot)
# -----------------------------

@app.post("/save-metadata")
async def save_metadata(body: dict = Body(...)):
    kohde_id = body.get("kohde_id")
    metadata = body.get("metadata")

    if not kohde_id:
        return {"error": "kohde_id puuttuu"}

    key = f"kohteet/{kohde_id}/metadata.json"
    r2_put_json(key, metadata)

    return {"status": "ok", "saved": key}

@app.get("/get-metadata/{kohde_id}")
async def get_metadata(kohde_id: str):
    key = f"kohteet/{kohde_id}/metadata.json"
    data = r2_get_json(key)
    if not data:
        return {"error": "metadata not found"}
    return data

# -----------------------------
# 2) KOHDE- KANSIKUVA
# -----------------------------

@app.post("/upload-kansikuva")
async def upload_kansikuva(kohde_id: str = Form(...), file: UploadFile = File(...)):

    key = f"kohteet/{kohde_id}/kansikuva.jpg"
    content = await file.read()

    s3.put_object(
        Bucket=R2_BUCKET,
        Key=key,
        Body=content,
        ContentType=file.content_type
    )

    return {"status": "ok", "key": key}

# -----------------------------
# 3) HUONEISTODATA (data.json)
# -----------------------------

@app.post("/upload-data")
async def upload_data(body: dict = Body(...)):

    kohde_id = body.get("kohde_id")
    slug = body.get("huoneisto_slug")
    data = body.get("data")

    if not kohde_id or not slug:
        return {"error": "kohde_id tai huoneisto_slug puuttuu"}

    key = f"kohteet/{kohde_id}/huoneistot/{slug}/data.json"
    r2_put_json(key, data)

    return {"status": "ok", "saved": key}

@app.get("/get-apartment/{kohde_id}/{huoneisto_slug}")
async def get_apartment(kohde_id: str, huoneisto_slug: str):

    key = f"kohteet/{kohde_id}/huoneistot/{huoneisto_slug}/data.json"
    data = r2_get_json(key)

    if not data:
        return {}  # palautetaan tyhjä → UI tyhjentää lomakkeen

    return data

# -----------------------------
# 4) HUONEISTON KUVAT (1-2 kpl)
# -----------------------------

@app.post("/upload-image")
async def upload_image(
    kohde_id: str = Form(...),
    huoneisto_slug: str = Form(...),
    index: str = Form(...),              # "1" tai "2"
    file: UploadFile = File(...)
):
    """
    Tallentaa huoneistokohtaisen kuvan R2:een.
    index=1 → kuva1.jpg
    index=2 → kuva2.jpg
    """

    key = f"kohteet/{kohde_id}/huoneistot/{huoneisto_slug}/kuva{index}.jpg"
    content = await file.read()

    s3.put_object(
        Bucket=R2_BUCKET,
        Key=key,
        Body=content,
        ContentType=file.content_type
    )

    return {"status": "ok", "saved": key}
