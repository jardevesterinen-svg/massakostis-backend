print("### MAIN.PY V7 ACTIVE ###")
###############################################################################
# MAIN.PY v7 — BRAND-COMPLIANT PDF GENERATOR (STONE HEADER + GLACIER COVER)
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
from reportlab.lib.colors import HexColor

# ==========================================================
#  ENVIRONMENT VARIABLES (Railway)
# ==========================================================

CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")
R2_BUCKET = os.getenv("R2_BUCKET_NAME")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")
HEADER_HEIGHT = 48
IMAGES_MAX_HEIGHT = 220
MATERIALS_HEIGHT = 120
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
#  FASTAPI + CORS
# ==========================================================

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://massakostis-frontend.pages.dev"
    ],
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
    return r2_get_json(key) or {"error": "metadata not found"}


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
    return r2_get_json(key) or {}


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
    key = f"kohteet/{kohde_id}/huoneistot/{slugify(huoneisto_slug)}/kuva{index}.jpg"
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
#  6) HUONEISTOPOHJAT
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
#  PDF COLORS — BRAND BOOK (FINAL)
# ==========================================================

COLOR_TEXT = HexColor("#3B404C")           # Cool Charcoal
COLOR_BORDER = HexColor("#C3D9E8")         # 6 pt border
COLOR_HEADER = HexColor("#ECECE7")         # Stone Lighter (confirmed)
COLOR_TABLE_HEADER = HexColor("#C3D9E8")   # PTS header fill
COLOR_ROW_ALT = HexColor("#F2F7FA")        # Alternating row fill
COLOR_ROW_WHITE = HexColor("#FFFFFF")      # Even rows
COLOR_GRID = HexColor("#D0D0D0")           # Light grey gridlines


# ==========================================================
#  PDF OPTIONS (CORS Preflight)
# ==========================================================

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


# ==========================================================
#  PDF HEADER FUNCTION (used on ALL pages except cover)
# ==========================================================

def draw_stone_header(pdf, w, h):
    
    # --- Stone background (full width)
    pdf.setFillColor(COLOR_HEADER)
    pdf.rect(0, h - HEADER_HEIGHT, w, HEADER_HEIGHT, fill=1, stroke=0)

    # --- Logo (correct aspect ratio)
    try:
        logo = ImageReader("rakmentor-logo.png")
        pdf.drawImage(
        logo,
        14,
        h - HEADER_HEIGHT + 12,   # ✅ sisällä, EI yläpuolella
        width=140,
        height=HEADER_HEIGHT - 30,  # ✅ pakota korkeus    
        preserveAspectRatio=True,
        mask="auto"
        )
    except:
        pass

    # --- Blue border over everything (6 pt border)
    pdf.setLineWidth(6)
    pdf.setStrokeColor(COLOR_BORDER)
    pdf.rect(3, 3, w - 6, h - 6, stroke=1, fill=0)


# ==========================================================
#  START PDF GENERATOR
# ==========================================================

@app.post("/generate-report/{kohde_id}")
async def generate_report(kohde_id: str):
    
    def draw_scaled_image(pdf, img, x, y, max_w):
        orig_w, orig_h = img.getSize()
        scale = max_w / orig_w
        new_w = max_w
        new_h = orig_h * scale
        pdf.drawImage(img, x, y - new_h, width=new_w, height=new_h, mask="auto")
        return new_h
        
    # ---- LOAD METADATA ----
    meta_key = f"kohteet/{kohde_id}/metadata.json"
    metadata = r2_get_json(meta_key)
    if not metadata:
        return {"error": "metadata missing"}

    tilaaja = metadata["tilaaja"]
    kohde = metadata["kohde"]
    huoneistot = metadata["huoneistot"]

    # ---- LOAD HUONEISTOT ----
    apt_data = {}
    for apt in huoneistot:
        slug = slugify(apt)
        key = f"kohteet/{kohde_id}/huoneistot/{slug}/data.json"
        apt_data[apt] = r2_get_json(key) or {}

    # ---- FONTS ----
    pdfmetrics.registerFont(TTFont("Arial", "Arial.ttf"))
    pdfmetrics.registerFont(TTFont("Arial-Bold", "ArialBold.ttf"))

    # ---- PDF CANVAS ----
    buff = io.BytesIO()
    pdf = canvas.Canvas(buff, pagesize=A4)
    w, h = A4
    
    # ==========================
    # KIINTEÄ HUONEISTOLAYOUT
    # ==========================
    
    HEADER_BOTTOM_Y = h - HEADER_HEIGHT
         
    IMAGES_TOP_Y = HEADER_BOTTOM_Y - 40
    MATERIALS_TOP_Y = IMAGES_TOP_Y - IMAGES_MAX_HEIGHT - 30
    TABLE_TOP_Y = MATERIALS_TOP_Y - MATERIALS_HEIGHT - 30

    # ======================================================
    # =============  PAGE 1 — KANSILEHTI  ==================
    # ======================================================

    # ---- Stone Header (full width, 17 mm ≈ 48 pt) ----
    
    pdf.setFillColor(COLOR_HEADER)   # #ECECE7 (Stone Lighter)
    pdf.rect(0, h - HEADER_HEIGHT, w, HEADER_HEIGHT, fill=1, stroke=0)

    # ---- Glacier Corner Shape (ONLY ON COVER) ----
    try:
        glacier = ImageReader("corner-small-left-glacier.png")
        pdf.drawImage(
            glacier,
            6,
            h - HEADER_HEIGHT - 15,     # slightly above stone header overlap
            width=160,
            height=59,
            mask="auto"
        )
    except:
        pass

    # ---- Logo on top of Glacier shape (correct aspect ratio) ----
    try:
        logo = ImageReader("rakmentor-logo.png")
        pdf.drawImage(
        logo,
        14,
        h - HEADER_HEIGHT + 12,   # ✅ sisällä, EI yläpuolella
        width=140,
        height=HEADER_HEIGHT - 30,  # ✅ pakota korkeus    
        preserveAspectRatio=True,
        mask="auto"
        )
    except:
        pass
    # ---- Blue Border (6 pt) OVER EVERYTHING ----
    pdf.setLineWidth(6)
    pdf.setStrokeColor(COLOR_BORDER)   # #C3D9E8
    pdf.rect(3, 3, w - 6, h - 6, stroke=1, fill=0)

    # ---- Title Block ----
    pdf.setFillColor(COLOR_TEXT)
    pdf.setFont("Arial-Bold", 26)
    pdf.drawString(40, h - 140, "Märkätilojen kosteuskartoitus")

    # ---- Kohde nimi ----
    pdf.setFont("Arial-Bold", 20)
    pdf.drawString(40, h - 180, kohde["nimi"])

    # ---- Kohteen osoite ----
    pdf.setFont("Arial", 14)
    pdf.drawString(40, h - 205, kohde["osoite"])
    pdf.drawString(
        40,
        h - 225,
        f"{kohde['postinumero']} {kohde['postitoimipaikka']}"
    )

    # ---- Tarkastus- ja raportointipäivä ----
    raportointipaiva = datetime.now().strftime("%d.%m.%Y")
    pdf.drawString(40, h - 255, f"Tarkastuspäivä: {kohde['paiva']}")
    pdf.drawString(40, h - 275, f"Raportointipäivä: {raportointipaiva}")

    # ---- Kansikuva ----
    try:
        img_bytes = s3.get_object(
            Bucket=R2_BUCKET,
            Key=f"kohteet/{kohde_id}/kansikuva.jpg"
        )["Body"].read()

        img = ImageReader(io.BytesIO(img_bytes))
        orig_w, orig_h = img.getSize()

        target_w = 500
        target_h = target_w * orig_h / orig_w
        
        pdf.drawImage(
            img,
            40,
            h - 300 - target_h,  # siisti sijainti
            width=target_w,
            height=target_h,
            mask="auto"
        )
    except:
        pass

    # ---- Footer (ONLY on cover) ----
    pdf.setFont("Arial", 10)
    pdf.setFillColor(COLOR_TEXT)
    pdf.drawString(40, 40, "Rakmentor Oy | 010 739 8770")
    pdf.drawString(40, 25, "asiakaspalvelu@rakmentor.fi | rakmentor.fi")

    # Cover has NO page number
    pdf.showPage()

    # ======================================================
    # ==========  PAGE 2 — PERUSTIEDOT  =====================
    # ======================================================

    # Draw Stone header + logo + border
    draw_stone_header(pdf, w, h)

    pdf.setFillColor(COLOR_TEXT)
    pdf.setFont("Arial-Bold", 22)
    pdf.drawString(40, h - HEADER_HEIGHT - 40, "Perustiedot")

    current_page = 2

    
    # ======================================================
    #  TABLE DRAW FUNCTION (PTS STYLE)
    # ======================================================

    def draw_pts_table(pdf, x, y, rows, col_widths, w):
        """
        Draws a PTS‑style table with:
        - #C3D9E8 header background
        - alternating rows (#FFFFFF / #F2F7FA)
        - #D0D0D0 gridlines
        """
        row_h = 22
        cur_y = y

        for idx, (left, right) in enumerate(rows):
            is_header = (idx == 0)

            # Background
            if is_header:
                pdf.setFillColor(COLOR_TABLE_HEADER)
            else:
                pdf.setFillColor(COLOR_ROW_ALT if idx % 2 == 1 else COLOR_ROW_WHITE)

            pdf.rect(x, cur_y - row_h, col_widths[0] + col_widths[1],
                     row_h, fill=1, stroke=0)

            # Text
            pdf.setFillColor(COLOR_TEXT)
            if is_header:
                pdf.setFont("Arial-Bold", 11)
            else:
                pdf.setFont("Arial", 11)

            pdf.drawString(x + 6, cur_y - 15, left)
            pdf.drawString(x + col_widths[0] + 6, cur_y - 15, right)

            # Gridline
            pdf.setStrokeColor(COLOR_GRID)
            pdf.setLineWidth(0.5)
            pdf.line(x, cur_y - row_h,
                     x + col_widths[0] + col_widths[1],
                     cur_y - row_h)

            cur_y -= row_h

        return cur_y


    # ======================================================
    #  PERUSTIEDOT — BUILD ROWS (PTS STYLE)
    # ======================================================

    rows = [
        ["Tilaajan tiedot", ""],
        ["Nimi", f"{tilaaja['etunimi']} {tilaaja['sukunimi']}"],
        ["Yritys", tilaaja["yritys"]],
        ["Osoite", tilaaja["osoite"]],
        ["Postitoimipaikka",
         f"{tilaaja['postinumero']} {tilaaja['postitoimipaikka']}"],
        ["Sähköposti", tilaaja["sahkoposti"]],
        ["Puhelin", tilaaja["puhelin"]],
        ["Kohteen nimi", kohde["nimi"]],
        ["Kohteen osoite", kohde["osoite"]],
        ["Tarkastuspäivä", kohde["paiva"]],
        ["Raportointipäivä", raportointipaiva],
        ["Tarkastaja", kohde["tarkastaja"]],
    ]

    # Draw table under the "Perustiedot" heading
    table_x = 40
    table_y = h - HEADER_HEIGHT - 90
    col_widths = [180, 300]

    table_y = draw_pts_table(pdf, table_x, table_y, rows, col_widths, w)

    # Footer + Page Number
    pdf.setFont("Arial", 10)
    pdf.setFillColor(COLOR_TEXT)

    pdf.drawString(40, 30, "Rakmentor Oy")
    pdf.drawRightString(555, 30, str(current_page))

    pdf.showPage()
    current_page += 1
    # ======================================================
    # ===============  HUONEISTO-SIVUT  ====================
    # ======================================================


    for apt in huoneistot:
        slug = slugify(apt)
        data = apt_data.get(apt, {})
    
        # ---- Stone header + logo + border ----
        draw_stone_header(pdf, w, h)
    
        # ---- Headerin oikean reunan lisätiedot ----
        pdf.setFont("Arial", 9)
        pdf.setFillColor(COLOR_TEXT)
        
        info_x = w - 80   # infosarakkeen oikea reuna
        page_x = w - 40    # sivunumeron äärioikea
        
        y = h - 18
        
        pdf.drawRightString(info_x, y, f"Huoneisto {apt}")
        y -= 11
        pdf.drawRightString(info_x, y, f"Tarkastuspäivä: {kohde['paiva']}")
        y -= 11
        pdf.drawRightString(
            info_x,
            y,
            f"{kohde['osoite']}, {kohde['postitoimipaikka']}"
        )
        
        # Sivunumero ERIKSEEN aivan oikealle
        pdf.drawRightString(page_x, h + 10 , f"Sivu {current_page}")
       
        # (tähän kuvat, materiaalit, taulukko...)
    
        # ==================================================
        #  LOAD IMAGES (two side-by-side)
        # ==================================================
        img_w = 240
        img_h = 240
        gap = 40

        def load_img(path):
            try:
                b = s3.get_object(Bucket=R2_BUCKET, Key=path)["Body"].read()
                return ImageReader(io.BytesIO(b))
            except:
                return None

        img1 = load_img(f"kohteet/{kohde_id}/huoneistot/{slug}/kuva1.jpg")
        img2 = load_img(f"kohteet/{kohde_id}/huoneistot/{slug}/kuva2.jpg")

        # ---- Render images ----
       
        MAX_IMG_W = (w - 40*2 - 20) / 2
        y_img = IMAGES_TOP_Y
        
        if img1 and img2:
            draw_scaled_image(pdf, img1, 40, y_img, MAX_IMG_W)
            draw_scaled_image(pdf, img2, 40 + MAX_IMG_W + 20, y_img, MAX_IMG_W)
                    
        elif img1:
            draw_scaled_image(pdf, img1, 40, y_img, MAX_IMG_W*2 + 20)
                    
        elif img2:
            draw_scaled_image(pdf, img2, 40, y_img, MAX_IMG_W*2 + 20)
      
        
        # ======================
        # PINTARAKENTEIDEN MATERIAALIT
        # ======================
        y_mat = MATERIALS_TOP_Y
        pdf.setFont("Arial-Bold", 14)
        pdf.setFillColor(COLOR_TEXT)
        pdf.drawString(40, MATERIALS_TOP_Y, "Pintarakenteiden materiaalit")
                    
        COL_GAP = 20
        COL_W = (w - 40*2 - COL_GAP*2) / 3
        
        def draw_material_block(title, items, x, y):
            pdf.setFont("Arial-Bold", 11)
            pdf.drawString(x, y, title)
            y -= 14
        
            pdf.setFont("Arial", 11)
            for item in items:
                pdf.drawString(x + 10, y, f"• {item}")
                y -= 13
        
            return y
        
        # Pilko putket listaksi
        vesiputket = [s.strip() for s in data.get("materiaalit_vesiputket", "").split(",") if s.strip()]
        lampoputket = [s.strip() for s in data.get("materiaalit_lampoputket", "").split(",") if s.strip()]
        
        col1_y = draw_material_block(
            "Seinien pintamateriaali",
            [data.get("materiaalit_seinat_valinta", "–")],
            40,
            MATERIALS_TOP_Y - 20
        )
        
        col2_y = draw_material_block(
            "Lattian pintamateriaali",
            [data.get("materiaalit_lattia_valinta", "–")],
            40 + COL_W + COL_GAP,
            MATERIALS_TOP_Y - 20
        )
        
        col3_y = draw_material_block(
            "Vesiputket",
            vesiputket or ["–"],
            40 + (COL_W + COL_GAP) * 2,
            MATERIALS_TOP_Y - 20
        )
               
        
        # Toinen rivi
        col1_y = draw_material_block(
            "Katon pintamateriaali",
            [data.get("materiaalit_katto_valinta", "–")],
            40,
            col1_y - 10
        )
        
        col2_y = draw_material_block(
            "Lämpöputket",
            lampoputket or ["–"],
            40 + COL_W + COL_GAP,
            col1_y - 10
        )
        
        # ==================================================
        #  HUONEISTON TIEDOT (PTS TABLE)
        # ==================================================
        col_widths = [160, 80, 240]
        rows = [
            ["Tarkastuskohde", "Kuntoluokka", "Havainnot ja toimenpiteet"]
        ]
        
        TARKASTUSKOHTEET = [
            ("lattian_kosteus", "Lattian kosteus"),
            ("seinien_kosteus", "Seinien kosteus"),
            ("lapiviennit", "Läpiviennit"),
            ("pinnat_saumat", "Pinnat, saumat, silikoni"),
            ("vesikalusteet", "Vesikalusteet"),
            ("ilmanvaihto", "Ilmanvaihto"),
            ("ovikynnys", "Ovikynnys"),
            ("lattiakaivo", "Lattiakaivo"),
            ("lattiakallistukset", "Lattiakallistukset"),
        ]
        tarkastukset = data.get("tarkastukset", {})

        for key, label in TARKASTUSKOHTEET:
            item = tarkastukset.get(key, {})
            kuntoluokka = item.get("kuntoluokka", "–")
        
            havainnot = item.get("havainnot", "").strip()
            toimenpiteet = item.get("toimenpiteet", "").strip()
        
            if not havainnot and not toimenpiteet:
                teksti = "Havainnot: Ei havaittu puutteita"
            else:
                parts = []
                if havainnot:
                    parts.append(f"Havainnot: {havainnot}")
                if toimenpiteet:
                    parts.append(f"Toimenpiteet: {toimenpiteet}")
                teksti = " ".join(parts)
        
            rows.append([
                label,
                str(kuntoluokka),
                teksti
            ])
             
            draw_pts_table(
                pdf,
                40,
                TABLE_TOP_Y,
                rows,
                col_widths,
                w
            )
        
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
    #  SAVE PDF → R2 AND RETURN URL
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
# END OF FILE — main.py v7
###############################################################################
