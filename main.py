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

# CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")
R2_BUCKET = os.getenv("R2_BUCKET_NAME")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")
HEADER_HEIGHT = 48
IMAGES_MAX_HEIGHT = 220
# MATERIALS_HEIGHT = 120
PUBLIC_URL = os.getenv("PUBLIC_URL")
MIN_SPACE = 150  # minimaalinen tila uudelle taulukolle

KOSTEUSKARTOITUS_TEKSTI = """
Märkätilojen kosteuskartoituksessa tarkastellaan tilojen pintarakenteita, liitoksia ja läpivientejä aistinvaraisesti sekä tarvittaessa pintakosteusmittauksin. Kartoitus ei sisällä rakenteiden avaamista eikä rakenteiden sisäisiä mittauksia. Mahdolliset mittaustulokset ovat suuntaa-antavia. Kartoituksessa ei arvioida rakenteiden teknistä käyttöikää eikä energiatehokkuutta. Havaitut puutteet ja riskit kirjataan raporttiin. Raportti ei ole rakenteellinen kuntotutkimus. Tarvittaessa suositellaan tarkempia tutkimuksia. Kartoitus perustuu tarkastushetken havaintoihin.
"""

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

@app.on_event("startup")
def startup():
    print("PUBLIC_URL =", os.getenv("PUBLIC_URL"))
    print("BUCKET =", os.getenv("R2_BUCKET_NAME"))


# 🔥 LISÄÄ TÄMÄ TÄHÄN
@app.get("/debug")
def debug():
    print("DEBUG ENDPOINT CALLED2")
    return {
        "PUBLIC_URL": os.getenv("PUBLIC_URL"),
        "BUCKET": os.getenv("R2_BUCKET_NAME")
    }


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

from reportlab.pdfbase.pdfmetrics import stringWidth

def wrap_text(text, font_name, font_size, max_width):
    words = text.split(" ")
    lines = []
    current = ""
       
    for word in words:
        test = current + (" " if current else "") + word
        if stringWidth(test, font_name, font_size) <= max_width:
            current = test
        else:
            lines.append(current)
            current = word

    if current:
        lines.append(current)

    return lines

def draw_pts_table(pdf, x, y, rows, col_widths):
    """
    Draws a PTS-style 2-column table with:
    - wrapped text
    - dynamic row height
    - proper alignment
    """

    cur_y = y
    LINE_HEIGHT = 14
    BASE_ROW_HEIGHT = 22

    for idx, (left, right) in enumerate(rows):
        is_header = (idx == 0)

        # --- FONT ---
        font_name = "Arial-Bold" if is_header else "Arial"
        font_size = 11 if is_header else 10

        pdf.setFont(font_name, font_size)
        pdf.setFillColor(COLOR_TEXT)

        # --- WRAP TEXT (vain oikea sarake tarvitsee) ---
        right_text = str(right or "").replace("\n", " ")
        right_lines = wrap_text(
            right_text,
            font_name,
            font_size,
            col_widths[1] - 12
        )

        # vasen sarake yleensä lyhyt → yksi rivi riittää
        left_text = str(left or "")

        # --- RIVIKORKEUS ---
        content_height = max(1, len(right_lines)) * LINE_HEIGHT
        row_h = max(BASE_ROW_HEIGHT, content_height + 8)

        # --- TAUSTA ---
        if is_header:
            pdf.setFillColor(COLOR_TABLE_HEADER)
        else:
            pdf.setFillColor(COLOR_ROW_ALT if idx % 2 == 1 else COLOR_ROW_WHITE)

        pdf.rect(
            x,
            cur_y - row_h,
            col_widths[0] + col_widths[1],
            row_h,
            fill=1,
            stroke=0
        )

        # tekstiväri takaisin
        pdf.setFillColor(COLOR_TEXT)
        pdf.setFont(font_name, font_size)

        # --- VASEN SARKE ---
        pdf.drawString(
            x + 6,
            cur_y - 15,
            left_text
        )

        # --- OIKEA SARKE (WRAPPED) ---
        text_y = cur_y - 15

        for line in right_lines:
            pdf.drawString(
                x + col_widths[0] + 6,
                text_y,
                line
            )
            text_y -= LINE_HEIGHT

        # --- GRID ---
        pdf.setStrokeColor(COLOR_GRID)
        pdf.setLineWidth(0.5)
        pdf.line(
            x,
            cur_y - row_h,
            x + col_widths[0] + col_widths[1],
            cur_y - row_h
        )

        # 👇 siirrytään seuraavaan riviin
        cur_y -= row_h

    return cur_y

def maybe_new_page(pdf, y, current_page, min_space=MIN_SPACE):
    if y < min_space:
        pdf.showPage()
        current_page += 1
        draw_stone_header(pdf, w, h)
        return h - HEADER_HEIGHT - 70, current_page
    return y, current_page
    
def draw_table_with_paging(pdf, rows, col_widths, y_start, current_page, title=None):
    y = y_start

    if title:
        pdf.setFont("Arial-Bold", 14)
        if y < 120:
            pdf.showPage()
            current_page += 1
            draw_stone_header(pdf, w, h)
            y = h - HEADER_HEIGHT - 40
        pdf.drawString(40, y, title)
        y -= 30

    chunk = [["", ""]]
    i = 0
    while i < len(rows):
        if i == 0:
            chunk = [rows[0]]
        chunk.append(rows[i])
        if len(chunk) >= 15 or i == len(rows) - 1:
            if y < 120:
                pdf.showPage()
                current_page += 1
                draw_stone_header(pdf, w, h)
                y = h - HEADER_HEIGHT - 40
            y = draw_pts_table(pdf, TABLE_X, y, chunk, col_widths)
            y -= 20
            chunk = [rows[0]]
        i += 1

    return y, current_page  # ← palauttaa molemmat
    
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

@app.get("/debug")
def debug():
    print("🔥 DEBUG CALLED2")
    return {
        "PUBLIC_URL": os.getenv("PUBLIC_URL"),
        "BUCKET": os.getenv("R2_BUCKET_NAME")
    }


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

        for obj in resp.get("Contents", []):
            key = obj.get("Key")

            # Esim: kohteet/kohde123/metadata.json
            parts = key.split("/")

            if len(parts) >= 3:
                kohde = parts[1]

                if kohde.strip():
                    kohteet.add(kohde)

        if resp.get("IsTruncated"):
            continuation = resp.get("NextContinuationToken")
        else:
            break

    print("✅ LÖYDETYT KOHTEET:", kohteet)

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

# ==========================
# LAYOUT CONSTANTS
# ==========================
w, h = A4
CONTENT_X = 40
CONTENT_GAP = 20
CONTENT_WIDTH = w - CONTENT_X * 2

TABLE_X = CONTENT_X
TABLE_WIDTH = CONTENT_WIDTH

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
    try:    
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

        # ==================================================
        # TARKASTUSKOHTEET (SIIRRETTY GLOBAALIKSI)
        # ==================================================
        
        TARKASTUSKOHTEET = [
            ("lattian_kosteus", "Lattian kosteus"),
            ("seinien_kosteus", "Seinien kosteus"),
            ("läpiviennit", "Läpiviennit"),
            ("pinnat", "Pinnat ja saumat"),
            ("vesikalusteet", "Vesikalusteet"),
            ("ilmanvaihto", "Ilmanvaihto"),
            ("ovikynnys", "Ovikynnys"),
            ("lattiakaivo", "Lattiakaivo"),
            ("lattiakallistukset", "Lattiakallistukset"),
        ]
    
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
             
        IMAGES_TOP_Y = HEADER_BOTTOM_Y - 15
        MATERIALS_TOP_Y = IMAGES_TOP_Y - IMAGES_MAX_HEIGHT
        
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
        
        def format_date(date_str):
            if not date_str:
                return ""
            try:
                return datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
            except:
                return date_str
        raportointipaiva = datetime.now().strftime("%d.%m.%Y")
        pdf.drawString(40, h - 255, f"Tarkastuspäivä: {format_date(kohde['paiva'])}")
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
            ["Tarkastaja", kohde["tarkastaja"]],
        ]
        table_y = h - HEADER_HEIGHT - 60
        
        col_widths_2col = [
            TABLE_WIDTH * 0.40,
            TABLE_WIDTH * 0.60
        ]

        table_y = draw_pts_table(pdf, TABLE_X, table_y, rows, col_widths_2col)
               
        TEXT_START_Y = table_y - 30
        TEXT_WIDTH = TABLE_WIDTH
        
        pdf.setFont("Arial-Bold", 12)
        pdf.drawString(TABLE_X, TEXT_START_Y, "Märkätilojen kosteuskartoituksen sisältö ja rajaukset")
        
        pdf.setFont("Arial", 10)
        
        lines = wrap_text(
            KOSTEUSKARTOITUS_TEKSTI.strip(),
            "Arial",
            10,
            TEXT_WIDTH
        )
        
        y_text = TEXT_START_Y - 18
        
        for line in lines:
            pdf.drawString(TABLE_X, y_text, line)
            y_text -= 14
       
        kunto_y = y_text - 30
                       
        col_widths_kunto = [
            TABLE_WIDTH * 0.15,
            TABLE_WIDTH * 0.85
        ]
        pdf.setFont("Arial", 9)
        rows = [
            ["Kuntoluokka", "Kuntoluokan selitys"],
            ["1", """Rakenteet ovat hyvässä kunnossa eikä merkittäviä puutteita havaittu. Vain normaalia kulumista voi esiintyä."""] ,
            ["2", """Rakenteissa on havaittavissa vähäisiä puutteita tai kulumaa. Korjaustarpeet eivät ole välittömiä."""] ,
            ["3", """Rakenteissa on selkeitä puutteita tai vaurioita. Korjaustoimenpiteet suositellaan tehtäväksi lähivuosina."""] ,
            ["4", """Rakenteissa on merkittäviä vaurioita tai kosteusriski. Korjaustoimenpiteet ovat kiireellisiä."""] ,
        ]
        
        kunto_y = draw_pts_table(pdf, TABLE_X, kunto_y, rows, col_widths_kunto)
    
        # Footer + Page Number
        pdf.setFont("Arial", 10)
        pdf.setFillColor(COLOR_TEXT)
    
        pdf.drawString(40, 30, "Rakmentor Oy")
        pdf.drawRightString(555, 30, str(current_page))
    
        pdf.showPage()
        current_page += 1

        # =========================
        # DATA YHTEENVETOA VARTEN
        # =========================
        kunto_counts = {"1":0, "2":0, "3":0, "4":0}
        kunto_lists = {"1":[], "2":[], "3":[], "4":[]}
        ei_tark_lista = []
        
        for apt in huoneistot:
            data = apt_data.get(apt, {})
        
            # ✅ kuntoluokka
            k = str(data.get("kokonaiskunto") or "")
            if k in kunto_counts:
                kunto_counts[k] += 1
                kunto_lists[k].append(apt)
        
            # ✅ ei tarkastettu
            if data.get("ei_tarkastettu"):
                syy = data.get("ei_tarkastettu_syy") or "–"
                ei_tark_lista.append((apt, syy))
        
        kayttoika_map = {}
        havainnot_map = {}
        toimenpiteet_map = {}
        
        for apt in huoneistot:
            data = apt_data.get(apt, {})
        
            # ✅ käyttöikä
            k = data.get("kayttoika_jaljella")
            if k:
                kayttoika_map.setdefault(k, []).append(apt)
        
            # ✅ havainnot + toimenpiteet (yhdistettynä tekstiin)
            for key, label in TARKASTUSKOHTEET:
        
                hav = (
                    data.get(f"{key}_havainnot_textarea") or
                    data.get(f"{key}_havainnot_select") or
                    ""
                ).strip()
        
                toimenp = (
                    data.get(f"{key}_toimenpiteet_textarea") or
                    data.get(f"{key}_toimenpiteet_select") or
                    ""
                ).strip()
        
                # --- HAVAINNOT
                if hav:
                    havainnot_map.setdefault(hav, []).append(apt)
        
                # --- TOIMENPITEET
                if toimenp:
                    toimenpiteet_map.setdefault(toimenp, []).append(apt)
                    
        # =========================
        # YHTEENVETO SIVU
        # =========================
        
        draw_stone_header(pdf, w, h)
        
        pdf.setFillColor(COLOR_TEXT)
        
        # -------- OTSIKKO --------
        pdf.setFont("Arial-Bold", 20)
        pdf.drawString(40, h - HEADER_HEIGHT - 40, "Yhteenveto")
        
        # =========================
        # KUNTOLUOKKAJAKAUMA
        # =========================
        
        pdf.setFont("Arial-Bold", 14)
        pdf.drawString(40, h - HEADER_HEIGHT - 80, "Kuntoluokkajakauma")
        
        y = h - HEADER_HEIGHT - 110
        
        # värit kuntoluokille
        colors = {
            "1": HexColor("#2ecc71"),  # vihreä
            "2": HexColor("#f1c40f"),  # keltainen
            "3": HexColor("#e67e22"),  # oranssi
            "4": HexColor("#e74c3c"),  # punainen
        }
        
        max_count = max(kunto_counts.values()) if kunto_counts else 1
        
        for k in ["1","2","3","4"]:
            count = kunto_counts[k]
        
            # skaalattu palkki
            bar_width = 0
            if max_count > 0:
                bar_width = (count / max_count) * 200
        
            pdf.setFillColor(colors[k])
            pdf.rect(40, y - 5, bar_width, 10, fill=1, stroke=0)
        
            pdf.setFillColor(COLOR_TEXT)
            pdf.setFont("Arial", 11)
            pdf.drawString(40 + 210, y - 2, f"{k}: {count} kpl")
        
            y -= 20
        
        # =========================
        # HUONEISTOLISTAT
        # =========================
        
        y -= 10
        pdf.setFont("Arial-Bold", 12)
        
        # =========================
        # KUNTOLUOKKALISTA TAULUKKONA
        # =========================
        
        y -= 10
        
        rows = [
            ["Kuntoluokka", "Huoneistot"]
        ]
        
        for k in ["1","2","3","4"]:
            if kunto_lists[k]:
                lista = ", ".join(kunto_lists[k])
                rows.append([k, lista])
        
        col_widths = [
            TABLE_WIDTH * 0.20,
            TABLE_WIDTH * 0.80
        ]
        
        y, current_page = draw_table_with_paging(pdf, rows, col_widths, y, current_page)
        
       
        # =========================
        # EI TARKASTETUT TAULUKKO
        # =========================
        
        if ei_tark_lista:
        
            y -= 30
        
            pdf.setFont("Arial-Bold", 14)
            pdf.drawString(40, y, "Tarkastamatta jääneet huoneistot")
        
            y -= 15
        
            rows = [
                ["Huoneisto", "Syy"]
            ]
        
            for apt, syy in ei_tark_lista:
                rows.append([apt, syy])
        
            col_widths = [
                TABLE_WIDTH * 0.25,
                TABLE_WIDTH * 0.75
            ]
        
            y, current_page = draw_table_with_paging(pdf, rows, col_widths, y, current_page)

        # draw_stone_header(pdf, w, h)
        
        # pdf.setFont("Arial-Bold", 14)
        # pdf.drawString(40, h - HEADER_HEIGHT - 40, "Huoneistojen arvioidut käyttöiät")
        
        # y = h - HEADER_HEIGHT - 70
        
        rows = [
            ["Käyttöikä", "Huoneistot"]
        ]
        
        for k, apts in kayttoika_map.items():
            rows.append([k, ", ".join(apts)])
        
        col_widths = [
            TABLE_WIDTH * 0.30,
            TABLE_WIDTH * 0.70
        ]
        y, current_page = maybe_new_page(pdf, y, current_page)        
        y, current_page = draw_table_with_paging(
            pdf, rows, col_widths, y, current_page,
            title="Huoneistojen arvioidut käyttöiät"
        )
                
        # draw_stone_header(pdf, w, h)

        # pdf.setFont("Arial-Bold", 14)
        # pdf.drawString(40, h - HEADER_HEIGHT - 40, "Havainnot huoneistoittain")
        
        # y = h - HEADER_HEIGHT - 70
        
        rows = [["Huoneistot", "Havainto"]]
        
        for teksti, apts in havainnot_map.items():
            rows.append([", ".join(apts), teksti])
            
        y, current_page = maybe_new_page(pdf, y, current_page)
        y, current_page = draw_table_with_paging(
            pdf, rows, col_widths, y, current_page,
            title="Havainnot huoneistoittain"
        )
        
        # draw_stone_header(pdf, w, h)

        # pdf.setFont("Arial-Bold", 16)
        # pdf.drawString(40, h - HEADER_HEIGHT - 40, "Toimenpide-ehdotukset")
        
        # y = h - HEADER_HEIGHT - 70
        
        rows = [["Huoneistot", "Toimenpide"]]
        
        for teksti, apts in toimenpiteet_map.items():
            rows.append([", ".join(apts), teksti])
        
        y, current_page = maybe_new_page(pdf, y, current_page)
        y, current_page = draw_table_with_paging(
            pdf, rows, col_widths, y, current_page,
            title="Toimenpide-ehdotukset"
        )

        # =========================
        # FOOTER
        # =========================
        
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
            
            pdf.setFillColor(COLOR_TEXT)
            
            info_x = w - 80   # infosarakkeen oikea reuna
            page_x = w - 40    # sivunumeron äärioikea
            
            y = h - 18
            pdf.setFont("Arial", 11)
            pdf.drawRightString(info_x - 200, y - 11 , f"Huoneisto {apt}")
            y -= 5
            pdf.setFont("Arial", 9)
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
            # img_w = 240
            # img_h = 240
            # gap = 40
            
            def load_img(path):
                try:
                    b = s3.get_object(Bucket=R2_BUCKET, Key=path)["Body"].read()
                    return ImageReader(io.BytesIO(b))
                except:
                    return None
    
            img1 = load_img(f"kohteet/{kohde_id}/huoneistot/{slug}/kuva1.jpg")
            img2 = load_img(f"kohteet/{kohde_id}/huoneistot/{slug}/kuva2.jpg")
    
            # ---- Render images ----
           
            MAX_IMG_W = (CONTENT_WIDTH - CONTENT_GAP) / 2
            y_img = IMAGES_TOP_Y
            
            def get_ratio(img_reader):
                try:
                    img = Image.open(io.BytesIO(img_reader._image.fp.read()))
                    w, h = img.size
                    return w / h
                except:
                    return 1.33  # fallback
            
            def is_wide(r):
                return r > 1.6  # ~16:9
            
            
            r1 = get_ratio(img1) if img1 else None
            r2 = get_ratio(img2) if img2 else None
            
            # ---- määritä leveydet ----
            def get_width(r):
                if r and is_wide(r):
                    return MAX_IMG_W * 0.85   # 👉 pienennetään leveää kuvaa
                return MAX_IMG_W
            
            
            w1 = get_width(r1)
            w2 = get_width(r2)
            
            # keskitys jos leveydet pienempiä
            total_width = w1 + w2 + CONTENT_GAP
            start_x = CONTENT_X + (CONTENT_WIDTH - total_width) / 2
            
            # ---- render ----
            if img1 and img2:
                draw_scaled_image(pdf, img1, start_x, y_img, w1)
                draw_scaled_image(pdf, img2, start_x + w1 + CONTENT_GAP, y_img, w2)
            

            elif img1:
                single_w = get_width(r1)
                x = CONTENT_X + (CONTENT_WIDTH - single_w) / 2
                draw_scaled_image(pdf, img1, x, y_img, single_w)
            
            elif img2:
                single_w = get_width(r2)
                x = CONTENT_X + (CONTENT_WIDTH - single_w) / 2
                draw_scaled_image(pdf, img2, x, y_img, single_w)

          
            # ✅ EI TARKASTETTU CASE
            if str(data.get("ei_tarkastettu")).lower() == "true":
            
                y_text = IMAGES_TOP_Y - IMAGES_MAX_HEIGHT - 30
            
                pdf.setFont("Arial-Bold", 16)
                pdf.setFillColor(HexColor("#b00000"))
                pdf.drawString(CONTENT_X, y_text, "EI TARKASTETTU")
            
                pdf.setFont("Arial", 12)
                pdf.setFillColor(COLOR_TEXT)
            
                syy = data.get("ei_tarkastettu_syy")
                if syy:
                    y_text -= 20
            
                    lines = wrap_text(
                        f"Syy: {syy}",
                        "Arial",
                        12,
                        CONTENT_WIDTH
                    )
            
                    for line in lines:
                        pdf.drawString(CONTENT_X, y_text, line)
                        y_text -= 14
            
                # ✅ footer tähän pageen
                pdf.setFont("Arial", 10)
                pdf.setFillColor(COLOR_TEXT)
            
                pdf.drawString(40, 30, "Rakmentor Oy")
                pdf.drawRightString(555, 30, str(current_page))
            
                pdf.showPage()
                current_page += 1
            
                continue   # 🔥 tärkein
            
            # ======================
            # PINTARAKENTEIDEN MATERIAALIT
            # ======================
            
            MAT_TITLE_Y = MATERIALS_TOP_Y
            MAT_ROW1_Y  = MAT_TITLE_Y - 24
            MAT_ROW2_Y  = MAT_ROW1_Y - 44
    
            pdf.setFont("Arial-Bold", 14)
            pdf.setFillColor(COLOR_TEXT)
            pdf.drawString(40, MAT_TITLE_Y, "Pintarakenteiden materiaalit")
                        
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
            def safe_split(value):
                if not value:
                    return []
                if isinstance(value, list):
                    return value
                if isinstance(value, str):
                    return [s.strip() for s in value.split(",") if s.strip()]
                return []
            
            vesiputket = safe_split(data.get("materiaalit_vesiputket"))
            lampoputket = safe_split(data.get("materiaalit_lampoputket"))
            
            # --- RIVI 1 ---
            draw_material_block(
                "Seinien pintamateriaali",
                [data.get("materiaalit_seinat_valinta", "–")],
                40,
                MAT_ROW1_Y
            )
            
            draw_material_block(
                "Lattian pintamateriaali",
                [data.get("materiaalit_lattia_valinta", "–")],
                40 + COL_W + COL_GAP,
                MAT_ROW1_Y
            )
            
            draw_material_block(
                "Vesiputket",
                vesiputket or ["–"],
                40 + (COL_W + COL_GAP) * 2,
                MAT_ROW1_Y
            )
            
            # --- RIVI 2 ---
            draw_material_block(
                "Katon pintamateriaali",
                [data.get("materiaalit_katto_valinta", "–")],
                40,
                MAT_ROW2_Y
            )
            
            draw_material_block(
                "Lämpöputket",
                lampoputket or ["–"],
                40 + COL_W + COL_GAP,
                MAT_ROW2_Y
            )

            draw_material_block(
                "Arvioitu pintarakenteiden ikä",
                [data.get("pintarakenteiden_ika", "–")],
                40 + (COL_W + COL_GAP) * 2,
                MAT_ROW2_Y
            )
            TABLE_START_Y = MAT_ROW2_Y - 40
            # ==================================================
            #  HUONEISTON TIEDOT (PTS TABLE)
            # ==================================================
          
            rows = [
                ["Tarkastuskohde", "KL", "Havainnot ja toimenpiteet"]
            ]
            col_widths = [
                float(TABLE_WIDTH) * 0.15,   # Tarkastuskohde
                float(TABLE_WIDTH) * 0.10,   # Kuntoluokka
                float(TABLE_WIDTH) * 0.75    # Havainnot ja toimenpiteet
            ]            
            
            for key, label in TARKASTUSKOHTEET:
                # Kuntoluokka (1, 2 jne.)
                kuntoluokka = data.get(f"kuntoluokka__{key}", "–")
            
                # Havainnot
                havainnot = (
                    data.get(f"{key}_havainnot_textarea", "") or
                    data.get(f"{key}_havainnot_select", "")
                ).strip()
            
                # Toimenpiteet
                toimenpiteet = (
                    data.get(f"{key}_toimenpiteet_textarea", "") or
                    data.get(f"{key}_toimenpiteet_select", "")
                ).strip()
            
                if not havainnot and not toimenpiteet:
                    teksti = "Havainnot: Ei havaittu puutteita"
                else:
                    osat = []
                    if havainnot:
                        osat.append(f"Havainnot: {havainnot}")
                    if toimenpiteet:
                        osat.append(f"Toimenpiteet: {toimenpiteet}")
                    teksti = " ".join(osat)
            
                rows.append([
                    label,
                    kuntoluokka,
                    teksti
                ])
            
            # ✅ PIIRRETÄÄN TAULUKKO VASTA TÄSSÄ
            
            from reportlab.lib.colors import red, green, orange
            
            def draw_pts_table_3col(pdf, x, y, rows, col_widths):
                cur_y = y
            
                for idx, row in enumerate(rows):
                    is_header = (idx == 0)
            
                    # ✅ Minimirivikorkeus
                    row_height = 22
            
                    # ✅ Taustaväri
                    if is_header:
                        pdf.setFillColor(COLOR_TABLE_HEADER)
                    else:
                        pdf.setFillColor(COLOR_ROW_ALT if idx % 2 == 1 else COLOR_ROW_WHITE)
            
                    # ✅ Piirrä taustan suorakulmio vasta lopullisella korkeudella
                    col_x = x
            
                    # --- ENSIN LASKETAAN RIVIN TARVITSEMA KORKEUS ---
                    _cells = []
                    FONT_SIZE = 9
                    LEADING = 12          # riviväli
                    CELL_PADDING = 4      # ylä- ja alamarginaali

                    for i, cell in enumerate(row):
                        if i == 2 and not is_header:
                            lines = wrap_text(
                                str(cell),
                                "Arial",
                                9,
                                col_widths[i] - 12
                            )
                            _cells.append(lines)                            
                            text_height = LEADING * len(lines)
                            row_height = max(row_height, text_height + CELL_PADDING * 2)
                        else:
                            _cells.append([str(cell)])
                    
                    if is_header:
                       row_height = max(row_height, 26)

                    # --- TAUSTA ---
                    pdf.rect(
                        x,
                        cur_y - row_height,
                        sum(col_widths),
                        row_height,
                        fill=1,
                        stroke=0
                    )
            
                    # --- TEKSTI ---
                    for i, lines in enumerate(_cells):
                        pdf.setFillColor(COLOR_TEXT)
                        pdf.setFont("Arial-Bold" if is_header else "Arial", FONT_SIZE)
               
                        text_y = cur_y - CELL_PADDING - FONT_SIZE
                        for line in lines:
                            pdf.drawString(col_x + 6, text_y, line)
                            text_y -= LEADING
            
                        col_x += col_widths[i]
            
                    # --- ALAVIIVA ---
                    pdf.setStrokeColor(COLOR_GRID)
                    pdf.setLineWidth(0.5)
                    pdf.line(
                        x,
                        cur_y - row_height,
                        x + sum(col_widths),
                        cur_y - row_height
                    )
            
                    # 👇 SIIRRY SEURAAVAAN RIVIIN
                    cur_y -= row_height
            
                return cur_y
              
            table3_y = draw_pts_table_3col(
                pdf,
                TABLE_X,
                TABLE_START_Y,
                rows,
                col_widths
            )
            
            # ✅ Hae käyttöikä
            kayttoika = data.get("kayttoika_jaljella", "–")
            kokonaiskunto = data.get("kokonaiskunto", "–")
            
            # ✅ Tekstin aloitus vähän taulukon alapuolelta
            text_y = table3_y - 20
            
            pdf.setFont("Arial", 11)
            pdf.setFillColor(COLOR_TEXT)
            
            if kayttoika in ["saneerattava", "saneerattava välittömästi"]:
                teksti = kayttoika
            else:
                teksti = f"Arvioitu jäljellä oleva käyttöikä on {kayttoika}"
            
            pdf.drawString(
                TABLE_X,
                text_y,
                teksti
            )
            
            pdf.drawRightString(
                TABLE_X + TABLE_WIDTH,
                text_y,
                f"Kokonaiskuntoluokka: {kokonaiskunto}"
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

    except Exception as e:
        import traceback
        print("🔥 PDF ERROR:")
        traceback.print_exc()
        raise

###############################################################################
# END OF FILE — main.py v7
###############################################################################
