import io
import re
import zipfile
from typing import Literal

import streamlit as st
from PIL import Image
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# ──────────────────────────────────────────────────────────────
# Configuração da página
# ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="Conversor de Assets", page_icon="🖼️", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap');

html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
h1,h2,h3,h4 { font-family: 'IBM Plex Mono', monospace; letter-spacing: -0.02em; }
.stApp { background: #111; }
.block-container { max-width: 1200px; padding-top: 2rem; }

.stTextInput>div>div>input {
    background:#1c1c1c; border:1px solid #2e2e2e; border-radius:6px;
    color:#f0f0f0; font-family:'IBM Plex Mono',monospace; font-size:.82rem;
}
.stButton>button {
    background:#c8ff57; color:#111; border:none; border-radius:6px;
    font-family:'IBM Plex Mono',monospace; font-weight:600; font-size:.8rem;
    padding:.5rem 1.2rem; transition:all .15s;
}
.stButton>button:hover { background:#b0e03c; transform:translateY(-1px); }
.stButton>button:disabled { background:#333; color:#666; }

.asset-card {
    background:#1a1a1a; border:2px solid #2a2a2a; border-radius:10px;
    padding:.8rem; text-align:center; transition: border-color .2s;
}
.asset-card.selected { border-color:#c8ff57; }
.asset-card.alt      { border-color:#2a2a2a; opacity:.8; }

.tag {
    display:inline-block; font-family:'IBM Plex Mono',monospace;
    font-size:.65rem; font-weight:600; padding:2px 8px;
    border-radius:20px; letter-spacing:.05em; margin-bottom:.4rem;
}
.tag-h   { background:#57b8ff; color:#111; }
.tag-v   { background:#ff8c57; color:#111; }
.tag-q   { background:#c8ff57; color:#111; }
.tag-alt { background:#333; color:#aaa; }

.dim   { font-family:'IBM Plex Mono',monospace; font-size:.7rem; color:#888; margin:.2rem 0; }
.fname { font-family:'IBM Plex Mono',monospace; font-size:.65rem; color:#555;
         word-break:break-all; margin-top:.3rem; }

.section-label {
    font-family:'IBM Plex Mono',monospace; font-size:.75rem; color:#888;
    text-transform:uppercase; letter-spacing:.1em;
    border-bottom:1px solid #222; padding-bottom:.4rem; margin:1.5rem 0 .8rem;
}
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────
# Constantes
# ──────────────────────────────────────────────────────────────
OUTPUT_SIZES: dict[str, list[tuple[int, int]]] = {
    "H": [(536, 302), (256, 144), (178, 104)],
    "V": [(156, 207), (130, 173), (98,  131)],
    "Q": [(302, 302), (144, 144), (104, 104)],
}
MIN_SIZE: dict[str, tuple[int, int]] = {
    "H": (536, 302),
    "V": (156, 207),
    "Q": (302, 302),
}
FORMAT_LABEL = {"H": "Horizontal", "V": "Vertical", "Q": "Quadrada"}
FORMAT_TAG   = {"H": "tag-h",      "V": "tag-v",    "Q": "tag-q"}

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# ──────────────────────────────────────────────────────────────
# Google Drive — mesma service account das outras páginas
# ──────────────────────────────────────────────────────────────
@st.cache_resource
def get_drive_service():
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]),
        scopes=SCOPES,
    )
    return build("drive", "v3", credentials=creds)


def extract_folder_id(url: str) -> str:
    for pat in [r"folders/([a-zA-Z0-9_-]+)", r"id=([a-zA-Z0-9_-]+)"]:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return url.strip()


@st.cache_data(show_spinner=False)
def list_drive_images(folder_id: str) -> list[dict]:
    """Lista todos os arquivos de imagem na pasta via Drive API."""
    service = get_drive_service()
    results = []
    page_token = None
    query = f"'{folder_id}' in parents and trashed=false and mimeType contains 'image/'"
    while True:
        resp = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, mimeType)",
            pageSize=200,
            pageToken=page_token,
        ).execute()
        results.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return results


@st.cache_data(show_spinner=False)
def download_drive_image(file_id: str) -> bytes | None:
    """Baixa o conteúdo binário de um arquivo do Drive."""
    service = get_drive_service()
    try:
        request = service.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue()
    except Exception:
        return None

# ──────────────────────────────────────────────────────────────
# Classificação por proporção + tamanho mínimo
# ──────────────────────────────────────────────────────────────
def detect_format(w: int, h: int) -> str | None:
    ratio = w / h
    if ratio > 1.15 and w >= MIN_SIZE["H"][0] and h >= MIN_SIZE["H"][1]:
        return "H"
    if ratio < 0.87 and w >= MIN_SIZE["V"][0] and h >= MIN_SIZE["V"][1]:
        return "V"
    if 0.87 <= ratio <= 1.15 and w >= MIN_SIZE["Q"][0] and h >= MIN_SIZE["Q"][1]:
        return "Q"
    return None

# ──────────────────────────────────────────────────────────────
# Processamento
# ──────────────────────────────────────────────────────────────
def resize_to_webp(img: Image.Image, w: int, h: int) -> bytes:
    out = img.resize((w, h), Image.LANCZOS)
    if out.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", (w, h), (255, 255, 255))
        bg.paste(out, mask=out.split()[-1])
        out = bg
    else:
        out = out.convert("RGB")
    buf = io.BytesIO()
    out.save(buf, format="WEBP", quality=90, method=6)
    return buf.getvalue()


def build_zip(outputs: list[dict]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for o in outputs:
            zf.writestr(o["filename"], o["webp_bytes"])
    return buf.getvalue()


def make_thumb(img: Image.Image, max_w=160, max_h=160) -> Image.Image:
    t = img.copy()
    t.thumbnail((max_w, max_h), Image.LANCZOS)
    return t

# ──────────────────────────────────────────────────────────────
# Session state
# ──────────────────────────────────────────────────────────────
def ss(key, default):
    if key not in st.session_state:
        st.session_state[key] = default

ss("candidates",    {"H": [], "V": [], "Q": []})
ss("selected_idx",  {"H": 0,  "V": 0,  "Q": 0})
ss("base_names",    {"H": "", "V": "", "Q": ""})
ss("outputs",       [])
ss("folder_loaded", False)

# ──────────────────────────────────────────────────────────────
# UI — cabeçalho
# ──────────────────────────────────────────────────────────────
st.markdown("## 🖼️ Conversor de Assets")
st.markdown(
    "Cole o link da pasta do jogo no Google Drive "
    "O app detecta automaticamente **Horizontal**, **Vertical** e **Quadrada** "
    "e gera os 9 arquivos WEBP."
)

# ──────────────────────────────────────────────────────────────
# Passo 1 — Carregar pasta
# ──────────────────────────────────────────────────────────────
with st.form("form_drive"):
    folder_url = st.text_input(
        "Link da pasta do jogo no Google Drive",
        placeholder="https://drive.google.com/drive/folders/XXXXXXXXXX",
    )
    load_btn = st.form_submit_button("🔍 Carregar imagens")

if load_btn and folder_url.strip():
    folder_id = extract_folder_id(folder_url)

    # Limpa cache ao trocar de pasta
    list_drive_images.clear()
    download_drive_image.clear()

    with st.spinner("Listando arquivos na pasta…"):
        try:
            files = list_drive_images(folder_id)
        except Exception as e:
            st.error(f"Erro ao acessar a pasta: {e}")
            st.stop()

    if not files:
        st.warning(
            "Nenhuma imagem encontrada. "
            "Verifique se a pasta foi compartilhada com a service account."
        )
        st.stop()

    candidates: dict[str, list[dict]] = {"H": [], "V": [], "Q": []}
    prog = st.progress(0, "Baixando e analisando imagens…")

    for i, f in enumerate(files):
        prog.progress((i + 1) / len(files), f"Analisando {f['name']}…")
        raw = download_drive_image(f["id"])
        if raw is None:
            continue
        try:
            img = Image.open(io.BytesIO(raw)).convert("RGBA")
        except Exception:
            continue
        w, h = img.size
        fmt = detect_format(w, h)
        if fmt:
            candidates[fmt].append({"name": f["name"], "id": f["id"], "image": img, "w": w, "h": h})

    prog.empty()

    st.session_state.candidates    = candidates
    st.session_state.selected_idx  = {"H": 0, "V": 0, "Q": 0}
    st.session_state.base_names    = {"H": "", "V": "", "Q": ""}
    st.session_state.outputs       = []
    st.session_state.folder_loaded = True

if not st.session_state.folder_loaded:
    st.stop()

candidates   = st.session_state.candidates
selected_idx = st.session_state.selected_idx

# ──────────────────────────────────────────────────────────────
# Passo 2 — Preview + seleção por formato
# ──────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### Passo 1 — Confirme as imagens base")

missing_formats = []

for fmt in ("H", "V", "Q"):
    label   = FORMAT_LABEL[fmt]
    tag     = FORMAT_TAG[fmt]
    cands   = candidates.get(fmt, [])
    min_w, min_h = MIN_SIZE[fmt]
    out_str = " · ".join(f"{w}×{h}" for w, h in OUTPUT_SIZES[fmt])

    st.markdown(
        f'<div class="section-label">'
        f'<span class="tag {tag}">{label}</span>'
        f'&nbsp; mínimo {min_w}×{min_h} &nbsp;→&nbsp; saídas: {out_str}'
        f'</div>',
        unsafe_allow_html=True,
    )

    if not cands:
        st.warning(f"Nenhuma imagem {label} compatível encontrada (mínimo {min_w}×{min_h}).")
        missing_formats.append(fmt)
        continue

    show = cands[:6]
    cols = st.columns(len(show))

    for ci, cand in enumerate(show):
        is_sel   = (ci == selected_idx[fmt])
        card_cls = "asset-card selected" if is_sel else "asset-card alt"

        with cols[ci]:
            st.markdown(f'<div class="{card_cls}">', unsafe_allow_html=True)
            st.image(make_thumb(cand["image"].copy()), use_container_width=True)
            badge_cls = tag if is_sel else "tag-alt"
            badge_txt = "Selecionada ✓" if is_sel else "Alternativa"
            st.markdown(
                f'<span class="tag {badge_cls}">{badge_txt}</span>'
                f'<div class="dim">{cand["w"]}×{cand["h"]}</div>'
                f'<div class="fname">{cand["name"]}</div>',
                unsafe_allow_html=True,
            )
            if not is_sel:
                if st.button("Usar esta", key=f"sel_{fmt}_{ci}"):
                    st.session_state.selected_idx[fmt] = ci
                    st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

    if len(cands) > 6:
        st.caption(f"+ {len(cands) - 6} outras imagens compatíveis não exibidas.")

# ──────────────────────────────────────────────────────────────
# Passo 3 — Nomes base
# ──────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### Passo 2 — Defina os nomes dos arquivos")
st.caption("Resultado: `{nome} 536x302.webp` — igual ao script do Photoshop.")

col1, col2, col3 = st.columns(3)
with col1:
    nh = st.text_input("Nome base — Horizontal", placeholder="Ex: Fonzo H",
                       value=st.session_state.base_names.get("H", ""))
with col2:
    nv = st.text_input("Nome base — Vertical",   placeholder="Ex: Fonzo V",
                       value=st.session_state.base_names.get("V", ""))
with col3:
    nq = st.text_input("Nome base — Quadrada",   placeholder="Ex: Fonzo Q",
                       value=st.session_state.base_names.get("Q", ""))

st.session_state.base_names = {"H": nh, "V": nv, "Q": nq}

can_generate = not missing_formats and all(n.strip() for n in [nh, nv, nq])

if not can_generate:
    if missing_formats:
        st.warning(f"Faltam imagens para: {', '.join(FORMAT_LABEL[f] for f in missing_formats)}")
    if not all(n.strip() for n in [nh, nv, nq]):
        st.warning("Preencha os 3 nomes base.")

gen_btn = st.button("⚡ Gerar 9 arquivos WEBP", disabled=not can_generate, use_container_width=True)

if gen_btn:
    outputs = []
    total   = sum(len(v) for v in OUTPUT_SIZES.values())
    done    = 0
    prog2   = st.progress(0, "Gerando arquivos…")
    names   = {"H": nh.strip(), "V": nv.strip(), "Q": nq.strip()}

    for fmt in ("H", "V", "Q"):
        cand = candidates[fmt][selected_idx[fmt]]
        img  = cand["image"]
        base = names[fmt]
        for (out_w, out_h) in OUTPUT_SIZES[fmt]:
            prog2.progress(done / total, f"Gerando {base} {out_w}×{out_h}…")
            wb    = resize_to_webp(img, out_w, out_h)
            fname = f"{base} {out_w}x{out_h}.webp"
            outputs.append({"fmt": fmt, "out_w": out_w, "out_h": out_h,
                             "webp_bytes": wb, "filename": fname})
            done += 1

    prog2.empty()
    st.session_state.outputs = outputs
    st.success(f"✅ {len(outputs)} arquivos gerados!")

# ──────────────────────────────────────────────────────────────
# Passo 4 — Downloads
# ──────────────────────────────────────────────────────────────
outputs: list[dict] = st.session_state.outputs
if not outputs:
    st.stop()

st.markdown("---")
st.markdown("### Passo 3 — Download")

st.download_button(
    label="⬇️ Baixar todos os 9 arquivos em ZIP",
    data=build_zip(outputs),
    file_name="assets_webp.zip",
    mime="application/zip",
    use_container_width=True,
)

st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)

for fmt in ("H", "V", "Q"):
    fmt_outputs = [o for o in outputs if o["fmt"] == fmt]
    st.markdown(
        f'<div class="section-label">'
        f'<span class="tag {FORMAT_TAG[fmt]}">{FORMAT_LABEL[fmt]}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    cols = st.columns(len(fmt_outputs))
    for ci, o in enumerate(fmt_outputs):
        with cols[ci]:
            st.image(Image.open(io.BytesIO(o["webp_bytes"])), use_container_width=True)
            st.markdown(
                f'<div class="dim">{o["out_w"]}×{o["out_h"]}</div>'
                f'<div class="fname">{o["filename"]}</div>',
                unsafe_allow_html=True,
            )
            st.download_button(
                label="⬇️ Baixar",
                data=o["webp_bytes"],
                file_name=o["filename"],
                mime="image/webp",
                key=f"dl_{fmt}_{ci}",
            )
