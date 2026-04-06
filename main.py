from fastapi import FastAPI, UploadFile, File, Form, Body
from fastapi.middleware.cors import CORSMiddleware
import boto3
import os
import json

# -----------------------------
#  ✅ YMPÄRISTÖMUUTTUJAT (Railway)
# -----------------------------

CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")
R2_BUCKET = os.getenv("R2_BUCKET_NAME")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")

print("DEBUG: BUCKET =", R2_BUCKET)
print("DEBUG: ENDPOINT =", R2_ENDPOINT)

# R2-yhteys boto3:lla (täsmälleen oikein Cloudflare R2:lle)
session = boto3.session.Session()
s3 = session.client(
    service_name="s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY
)

# -----------------------------
# ✅ FASTAPI + CORS
# -----------------------------

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],     # Cloudflare Pages sallitaan
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True
)

# -----------------------------
# ✅ APUFUNKTIOT R2:lle
# -----------------------------

def r2_put_json(key: str, data: dict):
    """Tallenna JSON tiedosto R2:een"""
    body = json.dumps(data, ensure_ascii=False, indent=4).encode("utf-8")
    s3.put_object(
        Bucket=R2_BUCKET,
        Key=key,
        Body=body,
        ContentType="application/json"
    )

def r2_get_json(key: str):
    """Lue JSON tiedosto R2:sta"""
    try:
        obj = s3.get_object(Bucket=R2_BUCKET, Key=key)
        return json.loads(obj["Body"].read())
    except:
        return None

# ===========================================================
# ✅ 1) KOHTEEN METADATA: metadata.json
# ===========================================================

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
        return {"error": "not found"}
    return data

# ===========================================================
# ✅ 2) KOHTEEN KANSIKUVA
# ===========================================================

@app.post("/upload-kansikuva")
async def upload_kansikuva(
    kohde_id: str = Form(...),
    file: UploadFile = File(...)
):
    key = f"kohteet/{kohde_id}/kansikuva.jpg"
    body = await file.read()

    s3.put_object(
        Bucket=R2_BUCKET,
        Key=key,
        Body=body,
        ContentType=file.content_type
    )

    return {"status": "ok", "saved": key}

# ===========================================================
# ✅ 3) HUONEISTON DATA (data.json)
# ===========================================================

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
        return {}  # UI tyhjentää lomakkeen

    return data

# ===========================================================
# ✅ 4) HUONEISTON KUVAT (kuva1.jpg, kuva2.jpg)
# ===========================================================

@app.post("/upload-image")
async def upload_image(
    kohde_id: str = Form(...),
    huoneisto_slug: str = Form(...),
    index: str = Form(...),                    # "1" tai "2"
    file: UploadFile = File(...)
):
    """
    Tallennetaan huoneiston kuva:
    /kohteet/<id>/huoneistot/<slug>/kuva1.jpg
    """

    key = f"kohteet/{kohde_id}/huoneistot/{huoneisto_slug}/kuva{index}.jpg"
    body = await file.read()

    s3.put_object(
        Bucket=R2_BUCKET,
        Key=key,
        Body=body,
        ContentType=file.content_type
    )

    return {"status": "ok", "saved": key}

# ===========================================================
# ✅ 5) KOHTEIDEN LISTAUS (hakutoimintoa varten)
# ===========================================================

@app.get("/list-kohteet")
async def list_kohteet():
    """
    Palauttaa kaikki kohteet:
    /kohteet/<kohde_id>/
    """

    resp = s3.list_objects_v2(
        Bucket=R2_BUCKET,
        Prefix="kohteet/",
        Delimiter="/"
    )

    items = []
    if "CommonPrefixes" in resp:
        for p in resp["CommonPrefixes"]:
            folder = p["Prefix"].replace("kohteet/", "").replace("/", "")
            items.append(folder)

    return {"kohteet": items}

# ===========================================================
# ✅ 6) HUONEISTOPOHJAT (OPTIONAALINEN, TULEVA OMINAISUUS)
# ===========================================================

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
    data = r2_get_json(key)
    return data or {}
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io

@app.post("/generate-report/{kohde_id}")
async def generate_report(kohde_id: str):

    # 1. Lataa metadata.json R2:sta
    meta_key = f"kohteet/{kohde_id}/metadata.json"
    metadata = r2_get_json(meta_key)
    if not metadata:
        return {"error": "metadata.json puuttuu"}

    # 2. Lataa kaikki huoneistot
    huoneistot = metadata.get("huoneistot", [])

    huoneistodata = {}
    for apt in huoneistot:
        slug = slugify(apt)
        key = f"kohteet/{kohde_id}/huoneistot/{slug}/data.json"
        data = r2_get_json(key)
        huoneistodata[apt] = data or {}

    # 3. Lataa logo R2:sta jos halutaan
    # Logo on ladattu frontista → voit myös lukea sen paikallisena tiedostona
    # Tässä käytämme paikallista logoa (jolle teen slotin)
    LOGO_PATH = "rakmentor-logo.png"  # Lataa tämä viereen
    logo = ImageReader(LOGO_PATH)

    # 4. Valmistele PDF canvas
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)

    # Rekisteröi Arial fontit
    pdfmetrics.registerFont(TTFont("Arial", "Arial.ttf"))
    pdfmetrics.registerFont(TTFont("Arial-Bold", "ArialBold.ttf"))

    # ============  KANSI  ================
    pdf.setFont("Arial-Bold", 24)
    pdf.drawString(50, 780, "Kuntoarvioraportti")

    # Kohteen tiedot
    pdf.setFont("Arial", 14)
    pdf.drawString(50, 750, metadata["kohde"]["nimi"])
    pdf.drawString(50, 730, metadata["kohde"]["osoite"])
    pdf.drawString(50, 710, f"{metadata['kohde']['postinumero']} {metadata['kohde']['postitoimipaikka']}")

    # Tarkastuspäivä
    pdf.drawString(50, 680, f"Tarkastuspäivä: {metadata['kohde']['paiva']}")

    # Tilaaja
    tilaaja = metadata["tilaaja"]
    pdf.drawString(50, 650, f"Tilaaja: {tilaaja['etunimi']} {tilaaja['sukunimi']}")

    # Logo oikeaan yläkulmaan
    pdf.drawImage(logo, 400, 730, width=150, height=40, mask="auto")

    # Kansikuva
    try:
        kansikuva_bytes = s3.get_object(
            Bucket=R2_BUCKET,
            Key=f"kohteet/{kohde_id}/kansikuva.jpg"
        )["Body"].read()

        kansi_img = ImageReader(io.BytesIO(kansikuva_bytes))
        pdf.drawImage(kansi_img, 50, 400, width=500, height=220)
    except:
        pass

    pdf.showPage()

    # ============ HUONEISTOT ================
    for apt in huoneistot:
        pdf.setFont("Arial-Bold", 22)
        pdf.drawString(50, 800, f"Huoneisto {apt}")

        data = huoneistodata.get(apt, {})

        y = 760
        pdf.setFont("Arial", 12)

        for k, v in data.items():
            if isinstance(v, str):
                pdf.drawString(50, y, f"{k}: {v}")
                y -= 20

        # Kuvat
        slug = slugify(apt)
        for idx in [1,2]:
            try:
                img_bytes = s3.get_object(
                    Bucket=R2_BUCKET,
                    Key=f"kohteet/{kohde_id}/huoneistot/{slug}/kuva{idx}.jpg"
                )["Body"].read()
                rimg = ImageReader(io.BytesIO(img_bytes))
                pdf.drawImage(rimg, 50 + ((idx-1)*260), 450, width=250, height=250)
            except:
                pass

        pdf.showPage()

    # 5. Sulje PDF
    pdf.save()

    pdf_bytes = buffer.getvalue()

    # 6. Tallenna PDF R2:een
    r2_key = f"kohteet/{kohde_id}/raportti.pdf"

    s3.put_object(
        Bucket=R2_BUCKET,
        Key=r2_key,
        Body=pdf_bytes,
        ContentType="application/pdf"
    )

    # 7. Palauta URL frontendiin
    pdf_url = f"{PUBLIC_URL}/{r2_key}"

    return {"status": "ok", "url": pdf_url}
