###############################################################################
# MAIN.PY v4 — COMPLETE BACKEND with PDF REPORT GENERATOR
###############################################################################

from fastapi import FastAPI, UploadFile, File, Form, Body
from fastapi.middleware.cors import CORSMiddleware
import boto3
import os
import json
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ==========================================================
#  ENVIRONMENT (Railway environment variables)
# ==========================================================

CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")
R2_BUCKET = os.getenv("R2_BUCKET_NAME")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")

PUBLIC_URL = "https://pub-9f421e06dc9f4bd49ae0adcf5690c438.r2.dev"

# ==========================================================
#  CLIENT FOR CLOUDFLARE R2
# ==========================================================

session = boto3.session.Session()

s3 = session.client(
    service_name="s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY
)

# ==========================================================
#  FASTAPI + CORS
# ==========================================================

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True
)

# ==========================================================
#  HELPER FUNCTIONS
# ==========================================================

def slugify(text: str):
    import re
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")

def r2_put_json(key: str, data: dict):
    body = json.dumps(data, ensure_ascii=False, indent=4).encode("utf-8")
    s3.put_object(
        Bucket=R2_BUCKET,
        Key=key,
        Body=body,
        ContentType="application/json"
    )

def r2_get_json(key: str):
    try:
        obj = s3.get_object(Bucket=R2_BUCKET, Key=key)
        return json.loads(obj["Body"].read())
    except:
        return None

# ==========================================================
#  1) SAVE METADATA
# ==========================================================

@app.post("/save-metadata")
async def save_metadata(body: dict = Body(...)):
    kohde_id = body.get("kohde_id")
    metadata = body.get("metadata")
    if not kohde_id:
        return {"error": "kohde_id missing"}

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

# ==========================================================
#  2) UPLOAD KANSIKUVA
# ==========================================================

@app.post("/upload-kansikuva")
async def upload_kansikuva(
    kohde_id: str = Form(...),
    file: UploadFile = File(...)
):
    key = f"kohteet/{kohde_id}/kansikuva.jpg"
    content = await file.read()

    s3.put_object(
        Bucket=R2_BUCKET,
        Key=key,
        Body=content,
        ContentType=file.content_type
    )

    return {"status": "ok", "saved": key}

# ==========================================================
#  3) HUONEISTON DATA
# ==========================================================

@app.post("/upload-data")
async def upload_data(body: dict = Body(...)):

    kohde_id = body.get("kohde_id")
    slug = body.get("huoneisto_slug")
    data = body.get("data")

    if not kohde_id or not slug:
        return {"error": "missing fields"}

    key = f"kohteet/{kohde_id}/huoneistot/{slug}/data.json"
    r2_put_json(key, data)

    return {"status": "ok", "saved": key}

@app.get("/get-apartment/{kohde_id}/{huoneisto_slug}")
async def get_apartment(kohde_id: str, huoneisto_slug: str):

    key = f"kohteet/{kohde_id}/huoneistot/{huoneisto_slug}/data.json"
    data = r2_get_json(key)

    if not data:
        return {}
    return data

# ==========================================================
#  4) HUONEISTON KUVIEN TALLENNUS
# ==========================================================

@app.post("/upload-image")
async def upload_image(
    kohde_id: str = Form(...),
    huoneisto_slug: str = Form(...),
    index: str = Form(...),
    file: UploadFile = File(...)
):
    key = f"kohteet/{kohde_id}/huoneistot/{huoneisto_slug}/kuva{index}.jpg"
    content = await file.read()

    s3.put_object(
        Bucket=R2_BUCKET,
        Key=key,
        Body=content,
        ContentType=file.content_type
    )

    return {"status": "ok", "saved": key}

# ==========================================================
#  5) KOHDELISTA (HAKU)
# ==========================================================

@app.get("/list-kohteet")
async def list_kohteet():
    # Hae kaikki objektit prefixillä "kohteet/"
    resp = s3.list_objects_v2(
        Bucket=R2_BUCKET,
        Prefix="kohteet/"
    )

    kohteet = set()

    if "Contents" in resp:
        for obj in resp["Contents"]:
            key = obj["Key"]

            # Erottaa kohde_id ensimmäisestä polkuelementistä
            # esim:
            #   kohteet/asoy-merikotka-2026-04-05/metadata.json
            # → asoy-merikotka-2026-04-05
            parts = key.split("/")
            if len(parts) >= 3:
                kohde = parts[1]
                if kohde:
                    kohteet.add(kohde)

    return {"kohteet": sorted(kohteet)}

# ==========================================================
#  6) HUONEISTOPOHJAT (VALINNAINEN)
# ==========================================================

@app.post("/save-template")
async def save_template(body: dict = Body(...)):
    kohde_id = body.get("kohde_id")
    nimi = body.get("nimi")
    pohja = body.get("pohja")

    key = f"kohteet/{kohde_id}/pohjat/{nimi}.json"
    r2_put_json(key, pohja)

    return {"status": "ok", "saved": key}

@app.get("/list-templates/{kohde_id}")
async def list_templates(kohde_id: str):
    resp = s3.list_objects_v2(
        Bucket=R2_BUCKET,
        Prefix=f"kohteet/{kohde_id}/pohjat/"
    )

    items = []
    if "Contents" in resp:
        for obj in resp["Contents"]:
            name = obj["Key"].split("/")[-1].replace(".json", "")
            items.append(name)

    return {"pohjat": items}

@app.get("/get-template/{kohde_id}/{nimi}")
async def get_template(kohde_id: str, nimi: str):
    key = f"kohteet/{kohde_id}/pohjat/{nimi}.json"
    return r2_get_json(key) or {}

# ==========================================================
#  7) PDF RAPORTTI — /generate-report/<kohde_id>
# ==========================================================

@app.post("/generate-report/{kohde_id}")
async def generate_report(kohde_id: str):

    # 1. METADATA
    meta_key = f"kohteet/{kohde_id}/metadata.json"
    metadata = r2_get_json(meta_key)
    if not metadata:
        return {"error": "metadata missing"}

    tilaaja = metadata["tilaaja"]
    kohde = metadata["kohde"]
    huoneistot = metadata["huoneistot"]

    # 2. HUONEISTODATA
    apt_data = {}
    for apt in huoneistot:
        slug = slugify(apt)
        key = f"kohteet/{kohde_id}/huoneistot/{slug}/data.json"
        apt_data[apt] = r2_get_json(key) or {}

    # 3. REKISTERÖI ARIAL-FONTIT
    pdfmetrics.registerFont(TTFont("Arial", "Arial.ttf"))
    pdfmetrics.registerFont(TTFont("Arial-Bold", "ArialBold.ttf"))

    # 4. CANVAS
    buff = io.BytesIO()
    pdf = canvas.Canvas(buff, pagesize=A4)
    w, h = A4

    # =======================================================
    #   PAGE 1 — KANSI
    # =======================================================

    # Logo vasemmalle
    try:
        logo = ImageReader("rakmentor-logo.png")
        pdf.drawImage(logo, 40, h - 120, width=180, height=50, mask="auto")
    except:
        pass

    pdf.setFont("Arial-Bold", 26)
    pdf.drawString(40, h - 180, "Kuntoarvioraportti")

    pdf.setFont("Arial-Bold", 20)
    pdf.drawString(40, h - 220, kohde["nimi"])

    pdf.setFont("Arial", 14)
    pdf.drawString(40, h - 245, kohde["osoite"])
    pdf.drawString(40, h - 265, f"{kohde['postinumero']} {kohde['postitoimipaikka']}")
    pdf.drawString(40, h - 295, f"Tarkastuspäivä: {kohde['paiva']}")
    pdf.drawString(40, h - 315, f"Tarkastaja: {kohde['tarkastaja']}")

    # Kansikuva
    try:
        img_bytes = s3.get_object(
            Bucket=R2_BUCKET,
            Key=f"kohteet/{kohde_id}/kansikuva.jpg"
        )["Body"].read()
        img = ImageReader(io.BytesIO(img_bytes))
        pdf.drawImage(img, 40, h - 580, width=500, height=260)
    except:
        pass

    # Footer
    pdf.setFont("Arial", 10)
    pdf.drawString(
        40, 30,
        "Rakmentor Oy | 010 739 8770 | asiakaspalvelu@rakmentor.fi | rakmentor.fi"
    )

    pdf.showPage()

    # =======================================================
    #  PAGE 2 — PERUSTIEDOT
    # =======================================================

    pdf.setFont("Arial-Bold", 22)
    pdf.drawString(40, h - 60, "Perustiedot")

    y = h - 120

    pdf.setFont("Arial-Bold", 14)
    pdf.drawString(40, y, "Tilaajan tiedot:")
    y -= 25
    pdf.setFont("Arial", 12)

    for field in [
        f"{tilaaja['etunimi']} {tilaaja['sukunimi']}",
        tilaaja["yritys"],
        tilaaja["osoite"],
        f"{tilaaja['postinumero']} {tilaaja['postitoimipaikka']}",
        tilaaja["sahkoposti"],
        tilaaja["puhelin"]
    ]:
        pdf.drawString(40, y, field)
        y -= 18

    pdf.showPage()

    # =======================================================
    #  PAGE 3 — RAPPU & HUONEISTOLISTA
    # =======================================================

    pdf.setFont("Arial-Bold", 22)
    pdf.drawString(40, h - 60, "Raput ja huoneistot")

    y = h - 120

    rappu_map = {}
    import re
    for apt in huoneistot:
        m = re.match(r"([^0-9]+)", apt)
        rappu = m.group(1).strip() if m else "Rappu"
        rappu_map.setdefault(rappu, []).append(apt)

    for rappu, asunnot in rappu_map.items():
        pdf.setFont("Arial-Bold", 14)
        pdf.drawString(40, y, rappu)
        y -= 25

        pdf.setFont("Arial", 12)
        for a in asunnot:
            pdf.drawString(60, y, a)
            y -= 18

            if y < 60:
                pdf.showPage()
                y = h - 60

    pdf.showPage()

    # =======================================================
    #  HUONEISTO SIVUT
    # =======================================================

    for apt in huoneistot:
        slug = slugify(apt)
        data = apt_data.get(apt, {})

        pdf.setFont("Arial-Bold", 22)
        pdf.drawString(40, h - 60, f"Huoneisto {apt}")

        y = h - 120
        pdf.setFont("Arial", 12)

        for k, v in data.items():
            if isinstance(v, str):
                pdf.drawString(40, y, f"{k}: {v}")
                y -= 18

                if y < 80:
                    pdf.showPage()
                    y = h - 60

        # Kuvat
        for idx in [1, 2]:
            try:
                img_bytes = s3.get_object(
                    Bucket=R2_BUCKET,
                    Key=f"kohteet/{kohde_id}/huoneistot/{slug}/kuva{idx}.jpg"
                )["Body"].read()

                img = ImageReader(io.BytesIO(img_bytes))
                x = 40 + (idx - 1) * 260
                pdf.drawImage(img, x, 300, width=250, height=250)
            except:
                pass

        pdf.showPage()

    # =======================================================
    #  SAVE PDF → R2
    # =======================================================

    pdf.save()
    pdf_bytes = buff.getvalue()

    r2_key = f"kohteet/{kohde_id}/raportti.pdf"

    s3.put_object(
        Bucket=R2_BUCKET,
        Key=r2_key,
        Body=pdf_bytes,
        ContentType="application/pdf"
    )

    url = f"{PUBLIC_URL}/{r2_key}"

    return {"status": "ok", "url": url}

###############################################################################
# END OF FILE
###############################################################################
``
