###############################################################################
# MAIN.PY v6 — COMPLETE BACKEND WITH BRAND-COMPLIANT PDF GENERATOR
###############################################################################

from fastapi import FastAPI, UploadFile, File, Form, Body, Response
from fastapi.middleware.cors import CORSMiddleware
import boto3
import os
import json
import io
from datetime import datetime

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.colors import Color, HexColor

# ==========================================================
#  ENVIRONMENT VARIABLES (Railway)
# ==========================================================

CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")
R2_BUCKET = os.getenv("R2_BUCKET_NAME")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")

PUBLIC_URL = "https://pub-9f421e06dc9f4bd49ae0adcf5690c438.r2.dev"

# ==========================================================
#  S3 CLIENT (Cloudflare R2)
# ==========================================================

session = boto3.session.Session()

s3 = session.client(
    service_name="s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY
)

# ==========================================================
#  FASTAPI + CORS (MUST BE BEFORE ANY ENDPOINT!)
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
#  3) HUONEISTODATA
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
#  4) HUONEISTON KUVIEN UPLOAD
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
#  5) KOHDELISTA (R2 TRUE LIST)
# ==========================================================

@app.get("/list-kohteet")
async def list_kohteet():
    kohteet = set()
    continuation = None

    while True:
        params = {
            "Bucket": R2_BUCKET,
            "Prefix": "kohteet/"
        }
        if continuation:
            params["ContinuationToken"] = continuation

        resp = s3.list_objects_v2(**params)
        contents = resp.get("Contents", [])

        for obj in contents:
            key = obj["Key"]
            parts = key.split("/")
            if len(parts) >= 3:
                cid = parts[1]
                if cid.strip():
                    kohteet.add(cid)

        if resp.get("IsTruncated"):
            continuation = resp.get("NextContinuationToken")
        else:
            break

    return {"kohteet": sorted(kohteet)}


# ==========================================================
#  6) HUONEISTOPOHJAT (OPTIONAL FEATURE)
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
#  7) PDF RAPORTTI — BRAND-COMPLIANT FULL LAYOUT
# ==========================================================

# ==== COLORS (BRAND BOOK 2026) ====
COLOR_TEXT = HexColor("#3B404C")          # Cool Charcoal Darker
COLOR_TABLE_HEADER = HexColor("#C3D9E8")  # PTS otsikkorivin täyttöväri
COLOR_ROW_ALT = HexColor("#F2F7FA")       # Vuorotteleva taustaväri
COLOR_ROW_WHITE = HexColor("#FFFFFF")
COLOR_TABLE_GRID = HexColor("#D0D0D0")    # Kevyt harmaa linjoille

#  PDF PRE-FLIGHT (OPTIONS)
@app.options("/generate-report/{kohde_id}")
async def pdf_options(kohde_id: str):
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "*"
        }
    )


@app.post("/generate-report/{kohde_id}")
async def generate_report(kohde_id: str):

    # ======================================================
    # LOAD METADATA
    # ======================================================
    meta_key = f"kohteet/{kohde_id}/metadata.json"
    metadata = r2_get_json(meta_key)
    if not metadata:
        return {"error": "metadata missing"}

    tilaaja = metadata["tilaaja"]
    kohde = metadata["kohde"]
    huoneistot = metadata["huoneistot"]

    # ======================================================
    # LOAD HUONEISTODATA
    # ======================================================
    apt_data = {}
    for apt in huoneistot:
        slug = slugify(apt)
        key = f"kohteet/{kohde_id}/huoneistot/{slug}/data.json"
        apt_data[apt] = r2_get_json(key) or {}

    # ======================================================
    # REGISTER FONTS (Arial)
    # ======================================================
    pdfmetrics.registerFont(TTFont("Arial", "Arial.ttf"))
    pdfmetrics.registerFont(TTFont("Arial-Bold", "ArialBold.ttf"))

    # ======================================================
    # CREATE PDF BUFFER + CANVAS
    # ======================================================
    buff = io.BytesIO()
    pdf = canvas.Canvas(buff, pagesize=A4)
    w, h = A4

    # ======================================================
    # HELPER: DRAW TABLE
    # ======================================================

    def draw_table(pdf, x, y, rows, col_widths, header=True):
        """
        rows: list of [left_cell, right_cell]
        col_widths: [width_left, width_right]
        header: whether first row is header style
        returns final y-coordinate
        """
        row_height = 22
        current_y = y

        for idx, (left, right) in enumerate(rows):
            is_header = (idx == 0 and header)

            # Background
            if is_header:
                pdf.setFillColor(COLOR_TABLE_HEADER)
            else:
                pdf.setFillColor(COLOR_ROW_ALT if idx % 2 == 1 else COLOR_ROW_WHITE)

            pdf.rect(x, current_y - row_height, col_widths[0] + col_widths[1],
                     row_height, fill=1, stroke=0)

            # Text
            pdf.setFillColor(COLOR_TEXT)
            if is_header:
                pdf.setFont("Arial-Bold", 11)
            else:
                pdf.setFont("Arial", 11)

            pdf.drawString(x + 6, current_y - 15, left)
            pdf.drawString(x + col_widths[0] + 6, current_y - 15, right)

            # Row border
            pdf.setStrokeColor(COLOR_TABLE_GRID)
            pdf.setLineWidth(0.5)
            pdf.line(x, current_y - row_height, x + col_widths[0] + col_widths[1],
                     current_y - row_height)

            current_y -= row_height

        return current_y
# ======================================================
    # =============  PAGE 1 — KANSILEHTI  ==================
    # ======================================================

    # Draw Glacier corner banner (your PNG)
    try:
        banner = ImageReader("corner-small-left-glacier.png")
        pdf.drawImage(
            banner,
            0,                      # x
            h - 160,                # y
            width=600,              # scaled
            height=160,
            mask="auto"
        )
    except:
        pass

    # Logo on top-left of banner
    try:
        logo = ImageReader("rakmentor-logo.png")
        pdf.drawImage(
            logo,
            40, h - 140,
            width=180,
            height=50,
            mask="auto"
        )
    except:
        pass

    # Title: Märkätilojen kosteuskartoitus
    pdf.setFillColor(COLOR_TEXT)
    pdf.setFont("Arial-Bold", 26)
    pdf.drawString(40, h - 200, "Märkätilojen kosteuskartoitus")

    # Kohteen nimi
    pdf.setFont("Arial-Bold", 20)
    pdf.drawString(40, h - 240, kohde["nimi"])

    # Osoite
    pdf.setFont("Arial", 14)
    pdf.drawString(40, h - 265, kohde["osoite"])
    pdf.drawString(40, h - 285,
                   f"{kohde['postinumero']} {kohde['postitoimipaikka']}")

    # Tarkastuspäivä + raportointipäivä
    raportointipaiva = datetime.now().strftime("%d.%m.%Y")

    pdf.drawString(40, h - 315, f"Tarkastuspäivä: {kohde['paiva']}")
    pdf.drawString(40, h - 335, f"Raportointipäivä: {raportointipaiva}")

    # Kansikuva
    try:
        img_bytes = s3.get_object(
            Bucket=R2_BUCKET,
            Key=f"kohteet/{kohde_id}/kansikuva.jpg"
        )["Body"].read()
        img = ImageReader(io.BytesIO(img_bytes))
        pdf.drawImage(img, 40, h - 600, width=500, height=260)
    except:
        pass

    # ====== Footer (ONLY on cover page) ======
    pdf.setFont("Arial", 10)
    pdf.setFillColor(COLOR_TEXT)
    pdf.drawString(40, 40, "Rakmentor Oy | 010 739 8770")
    pdf.drawString(40, 25, "asiakaspalvelu@rakmentor.fi | rakmentor.fi")

    # Cover page has NO page number
    pdf.showPage()

    # =============================
    # PAGE NUMBERING STARTS AT PAGE 2
    # =============================
    current_page = 2


    # ======================================================
    # =========== PAGE 2 — PERUSTIEDOT  ====================
    # ======================================================

    pdf.setFont("Arial-Bold", 22)
    pdf.setFillColor(COLOR_TEXT)
    pdf.drawString(40, h - 60, "Perustiedot")

    # Build table rows for Perustiedot using PTS style
    rows = [["Tilaajan tiedot", ""]]

    rows.append(["Nimi",
                 f"{tilaaja['etunimi']} {tilaaja['sukunimi']}"])
    rows.append(["Yritys", tilaaja["yritys"]])
    rows.append(["Osoite", tilaaja["osoite"]])
    rows.append(["Postitoimipaikka",
                 f"{tilaaja['postinumero']} {tilaaja['postitoimipaikka']}"])
    rows.append(["Sähköposti", tilaaja["sahkoposti"]])
    rows.append(["Puhelin", tilaaja["puhelin"]])

    rows.append(["Kohteen nimi", kohde["nimi"]])
    rows.append(["Kohteen osoite", kohde["osoite"]])
    rows.append(["Tarkastuspäivä", kohde["paiva"]])
    rows.append(["Raportointipäivä", raportointipaiva])
    rows.append(["Tarkastaja", kohde["tarkastaja"]])

    # Draw table
    x = 40
    y = h - 120
    col_widths = [180, 300]

    y = draw_table(pdf, x, y, rows, col_widths, header=True)

    # FOOTER + PAGE NUMBER
    footer_y = 30
    pdf.setFont("Arial", 10)
    pdf.setFillColor(COLOR_TEXT)

    pdf.drawString(40, footer_y, "Rakmentor Oy")
    pdf.drawRightString(555, footer_y, str(current_page))

    pdf.showPage()
    current_page += 1
    # ======================================================
    # ===========  HUONEISTO-SIVUT  ========================
    # ======================================================

    for apt in huoneistot:
        slug = slugify(apt)
        data = apt_data.get(apt, {})

        # ---- Otsikko ----
        pdf.setFont("Arial-Bold", 22)
        pdf.setFillColor(COLOR_TEXT)
        pdf.drawString(40, h - 60, f"Huoneisto {apt}")

        y_pointer = h - 120

        # ==================================================
        #  KUVAT (2 vierekkäin, isokokoisina)
        # ==================================================
        img_w = 240
        img_h = 240

        try:
            img1_bytes = s3.get_object(
                Bucket=R2_BUCKET,
                Key=f"kohteet/{kohde_id}/huoneistot/{slug}/kuva1.jpg"
            )["Body"].read()
            img1 = ImageReader(io.BytesIO(img1_bytes))
        except:
            img1 = None

        try:
            img2_bytes = s3.get_object(
                Bucket=R2_BUCKET,
                Key=f"kohteet/{kohde_id}/huoneistot/{slug}/kuva2.jpg"
            )["Body"].read()
            img2 = ImageReader(io.BytesIO(img2_bytes))
        except:
            img2 = None

        # Draw images if present
        if img1 and img2:
            pdf.drawImage(img1, 40, y_pointer - img_h, width=img_w, height=img_h)
            pdf.drawImage(img2, 300, y_pointer - img_h, width=img_w, height=img_h)
            y_pointer -= (img_h + 40)

        elif img1 and not img2:
            # Center single image
            center_x = (w - img_w) / 2
            pdf.drawImage(img1, center_x, y_pointer - img_h, width=img_w, height=img_h)
            y_pointer -= (img_h + 40)

        elif img2 and not img1:
            center_x = (w - img_w) / 2
            pdf.drawImage(img2, center_x, y_pointer - img_h, width=img_w, height=img_h)
            y_pointer -= (img_h + 40)

        else:
            # No images
            y_pointer -= 20

        # ==================================================
        #  HUONEISTON TIEDOT — PTS-TYYLIN TAULUKKO
        # ==================================================

        # We use the fixed order (A)
        rows = [["Huoneiston tiedot", ""]]

        # 1. Kuntoluokka
        if "kuntoluokka" in data:
            rows.append(["Kuntoluokka", str(data["kuntoluokka"])])

        # 2. Huomio-vaativa
        if "huomio" in data:
            rows.append(["Välitön huomio", str(data["huomio"])])

        # 3. Havainnot
        if "havainnot" in data:
            rows.append(["Havainnot", data["havainnot"]])

        # 4. Toimenpiteet
        if "toimenpiteet" in data:
            rows.append(["Toimenpiteet", data["toimenpiteet"]])

        # 5. Kommentit
        if "kommentit" in data:
            rows.append(["Kommentit", data["kommentit"]])

        # Draw table
        x = 40
        col_widths = [180, 300]

        y_pointer = draw_table(pdf, x, y_pointer, rows, col_widths, header=True)

        # ==================================================
        # FOOTER + PAGE NUMBER
        # ==================================================
        pdf.setFont("Arial", 10)
        pdf.setFillColor(COLOR_TEXT)

        pdf.drawString(40, 30, "Rakmentor Oy")
        pdf.drawRightString(555, 30, str(current_page))

        pdf.showPage()
        current_page += 1
        # ======================================================
    # ==========  SAVE PDF → R2 & RETURN URL  ==============
    # ======================================================

    pdf.save()
    pdf_bytes = buff.getvalue()

    r2_key = f"kohteet/{kohde_id}/raportti.pdf"

    s3.put_object(
        Bucket=R2_BUCKET,
        Key=r2_key,
        Body=pdf_bytes,
        ContentType="application/pdf"
    )

    pdf_url = f"{PUBLIC_URL}/{r2_key}"

    return {"status": "ok", "url": pdf_url}


###############################################################################
# END OF FILE — main.py v6
###############################################################################
