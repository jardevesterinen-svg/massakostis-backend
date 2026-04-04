from fastapi import FastAPI, UploadFile, File, Form, Body
import boto3
import os
import json

# ✅ Railway EI käytä .env-tiedostoa → EI load_dotenv
# from dotenv import load_dotenv
# dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
# load_dotenv(dotenv_path)

# ✅ Lue ympäristömuuttujat suoraan Railwayssa
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")
R2_BUCKET = os.getenv("R2_BUCKET_NAME")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")

print("DEBUG: ACCOUNT_ID =", CLOUDFLARE_ACCOUNT_ID)
print("DEBUG: BUCKET =", R2_BUCKET)
print("DEBUG: ACCESS_KEY_ID =", R2_ACCESS_KEY_ID)
print("DEBUG: ENDPOINT =", R2_ENDPOINT)

app = FastAPI()

# ✅ R2-yhteys boto3:lla
session = boto3.session.Session()
s3 = session.client(
    service_name="s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
)

# ✅ Kuvan upload
@app.post("/upload-image")
async def upload_image(file: UploadFile = File(...), path: str = Form(...)):
    data = await file.read()

    s3.put_object(
        Bucket=R2_BUCKET,
        Key=path,
        Body=data,
        ContentType=file.content_type
    )

    return {"status": "ok", "path": path}

# ✅ JSON-datan tallennus
@app.post("/upload-data")
async def upload_data(data: dict = Body(...)):

    save_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(save_dir, exist_ok=True)

    huoneisto = data.get("huoneisto")
    if not huoneisto:
        return {"error": "Kenttä 'huoneisto' puuttuu."}

    filepath = os.path.join(save_dir, f"{huoneisto}.json")

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    return {"status": "ok", "saved_as": filepath}
