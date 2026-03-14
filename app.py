import pandas as pd
import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

# ── Senha ──────────────────────────────────────────────────────────────────
senha = st.text_input("Senha", type="password")
if senha != st.secrets["APP_PASSWORD"]:
    st.stop()

st.set_page_config(layout="wide")

# ── Sessão ─────────────────────────────────────────────────────────────────
if "arquivos" not in st.session_state:
    st.session_state.arquivos = {}
if "erros" not in st.session_state:
    st.session_state.erros = []

# ── Helpers ────────────────────────────────────────────────────────────────
def normalizar(texto):
    texto = str(texto).strip().lower()
    texto = unicodedata.normalize("NFKC", texto)
    return texto

def to_timestamp(data, hora):
    dt_str = f"{data} {hora}"
    dt_sp = datetime.strptime(dt_str, "%Y-%m-%d %H:%M").replace(
        tzinfo=ZoneInfo("America/Sao_Paulo")
    )
    return int(dt_sp.timestamp())

# ── Google Sheets via Service Account ─────────────────────────────────────
@st.cache_data(ttl=300)
def carregar_base():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(st.secrets["SHEET_ID"]).sheet1
    data = sheet.get_all_records()
    df = pd.DataFrame(data)
    df["Nome no chat"] = df["Nome no chat"].apply(normalizar)
    return df

# ── UI ─────────────────────────────────────────────────────────────────────
st.title("Freetickets Izão")

with st.expander("Problemas"):
    st.write("""
1. Só corrige letra maiuscula e minuscula, o resto tem q estar correto
2. Não separa as cartelas de 50 em 50 não sei pq caralhos, tem q separar na mão
3. As vezes o arquivo que gerou some, tem que baixar rapido
4. Se um user não tiver nickname não vai encontrar e também não atualiza automaticamente caso ele coloque. Então eu tenho que atualizar a 'base' de users na mão. Também tenho q colocar novos usuarios na mão
""")

col1, col2 = st.columns([3, 1])

with col1:
    data = st.date_input("Data")
    hora = st.text_input("Hora (HH:MM)")
    texto = st.text_area(
        "Lista de apelidos e cartelas",
        height=300,
        placeholder="exemplo:\njoao 10\nmaria 5\nJuriscleuza \nVamoperde: 5 \nVamoganha : 50 - 10"
    )

    if st.button("Gerar CSVs"):
        erros = []

        try:
            timestamp = to_timestamp(data.strftime("%Y-%m-%d"), hora)
        except Exception:
            erros.append("Data ou hora inválida")

        try:
            df = carregar_base()
        except Exception as e:
            st.exception(e)
            st.stop()

        linhas_input = [l.strip() for l in texto.splitlines() if l.strip()]
        grupos = {}

        if not erros:
            for linha in linhas_input:
                linha = normalizar(linha)
                match = re.match(r"([a-z0-9_çãõ]+)[\s:\-]*\s*(\d+)", linha)
                if not match:
                    erros.append(f"Linha inválida: {linha}")
                    continue
                apelido, qtd = match.group(1), int(match.group(2))
                linha_base = df[df["Nome no chat"] == apelido]
                if linha_base.empty:
                    erros.append(f"Apelido '{apelido}' não encontrado")
                    continue
                userid = str(int(linha_base["Id Externo"].values[0]))
                grupo = linha_base["grupo"].values[0]
                if grupo not in grupos:
                    grupos[grupo] = []
                grupos[grupo].append([userid, qtd, timestamp, 0.50, 98])

        if erros:
            st.session_state.erros = erros
            st.session_state.arquivos = {}
        else:
            st.session_state.erros = []
            arquivos = {}
            for grupo, linhas in grupos.items():
                csv_data = "\n".join(
                    ",".join(map(str, linha)) for linha in linhas
                )
                arquivos[f"{grupo}.csv"] = csv_data
            st.session_state.arquivos = arquivos

with col2:
    st.subheader("Status")
    if st.session_state.erros:
        st.error("Erros encontrados:")
        for e in st.session_state.erros:
            st.write(e)
    else:
        st.success("Sistema pronto")

# ── Downloads ──────────────────────────────────────────────────────────────
if st.session_state.arquivos:
    st.subheader("Arquivos gerados")
    for nome, conteudo in st.session_state.arquivos.items():
        st.download_button(
            f"Baixar {nome}",
            conteudo,
            nome,
            "text/csv"
        )
