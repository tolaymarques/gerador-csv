import hmac
import pandas as pd
import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

# ── Config (deve ser a PRIMEIRA chamada Streamlit) ─────────────────────────
st.set_page_config(layout="wide")

# ── Senha ──────────────────────────────────────────────────────────────────
senha = st.text_input("Senha", type="password")
if not hmac.compare_digest(senha, st.secrets["APP_PASSWORD"]):
    st.stop()

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

def validar_hora(hora: str) -> bool:
    return bool(re.match(r"^([01]\d|2[0-3]):[0-5]\d$", hora.strip()))

def to_timestamp(data, hora):
    if not validar_hora(hora):
        raise ValueError(f"Hora inválida: '{hora}'. Use o formato HH:MM (ex: 09:05).")
    dt_str = f"{data} {hora}"
    dt_sp = datetime.strptime(dt_str, "%Y-%m-%d %H:%M").replace(
        tzinfo=ZoneInfo("America/Sao_Paulo")
    )
    return int(dt_sp.timestamp())

# ── Google Sheets ──────────────────────────────────────────────────────────
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

GRUPOS = ["Playbonds Gpas", "Playbonds Generic", "Colonial"]

@st.cache_resource
def get_client():
    """Autentica uma única vez por sessão."""
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)

def get_sheet():
    return get_client().open_by_key(st.secrets["SHEET_ID"]).sheet1

@st.cache_data(ttl=300)
def carregar_base():
    sheet = get_sheet()
    data = sheet.get_all_records()
    df = pd.DataFrame(data)
    df["Nome no chat"] = df["Nome no chat"].apply(normalizar)
    return df

def salvar_novo_usuario(id_externo, nome_no_chat, grupo):
    """Adiciona uma nova linha na planilha."""
    sheet = get_sheet()
    # Ordem das colunas: Id do jogador | Id externo | nome do jogador | Nome no chat | e-mail | tipo | moeda | grupo | criado em
    nova_linha = ["", id_externo, "", normalizar(nome_no_chat), "", "", "", grupo, ""]
    sheet.append_row(nova_linha, value_input_option="USER_ENTERED")
    carregar_base.clear()

def atualizar_nome_chat(id_externo, novo_nome):
    """Atualiza a coluna 'Nome no chat' da linha com o Id Externo informado."""
    sheet = get_sheet()
    id_col = sheet.col_values(2)  # Coluna B = Id Externo
    headers = sheet.row_values(1)

    # Busca todas as ocorrências (evita editar linha errada se houver duplicata)
    ocorrencias = [i + 1 for i, val in enumerate(id_col) if val == str(id_externo)]

    if not ocorrencias:
        return False, "Id Externo não encontrado na planilha."
    if len(ocorrencias) > 1:
        return False, f"Id Externo '{id_externo}' aparece {len(ocorrencias)} vezes na planilha. Corrija manualmente."

    try:
        col_index = headers.index("Nome no chat") + 1
    except ValueError:
        return False, "Coluna 'Nome no chat' não encontrada no cabeçalho."

    sheet.update_cell(ocorrencias[0], col_index, normalizar(novo_nome))
    carregar_base.clear()
    return True, ""

# ── UI Principal ───────────────────────────────────────────────────────────
st.title("Freetickets Izão v2.0 turbo")

with st.expander("Problemas"):
    st.write("""
1. Só corrige letra maiuscula e minuscula, o resto tem q estar correto
2. As vezes o arquivo que gerou some, tem que baixar rapido
3. Não atualiza automaticamente novos users nem troca de apelidos. Por isso coloquei os campos de adicionar novo user e modificar nickname
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
        except ValueError as e:
            erros.append(str(e))

        if not erros:
            with st.spinner("Buscando base de usuários..."):
                try:
                    df = carregar_base()
                except Exception as e:
                    st.exception(e)
                    st.stop()

            linhas_input = [l.strip() for l in texto.splitlines() if l.strip()]
            grupos = {}

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
                while qtd > 0:
                    lote = min(qtd, 50)
                    grupos[grupo].append([userid, lote, timestamp, 0.50, 98])
                    qtd -= lote

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
# Usar form com clear_on_submit=False evita que os botões sumam ao clicar num deles
if st.session_state.arquivos:
    st.subheader("Arquivos gerados")
    with st.form("form_downloads", clear_on_submit=False):
        for nome, conteudo in st.session_state.arquivos.items():
            st.download_button(
                f"Baixar {nome}",
                conteudo,
                nome,
                "text/csv",
                key=f"dl_{nome}",
            )
        st.form_submit_button(".", disabled=True, help="Use os botões acima para baixar")

# ── Gerenciar Usuários ─────────────────────────────────────────────────────
st.divider()

with st.expander("➕ Adicionar novo usuário"):
    with st.form("form_adicionar"):
        novo_id = st.text_input("Id Externo")
        novo_nick = st.text_input("Nome no chat")
        novo_grupo = st.selectbox("Grupo", GRUPOS)
        submitted = st.form_submit_button("Adicionar")

        if submitted:
            if not novo_id or not novo_nick:
                st.error("Preencha todos os campos.")
            else:
                with st.spinner("Verificando base..."):
                    df_atual = carregar_base()

                if str(novo_id) in df_atual["Id Externo"].astype(str).values:
                    st.error(f"Id Externo '{novo_id}' já existe na base.")
                elif normalizar(novo_nick) in df_atual["Nome no chat"].values:
                    st.error(f"Nome no chat '{novo_nick}' já existe na base.")
                else:
                    try:
                        with st.spinner("Salvando..."):
                            salvar_novo_usuario(novo_id, novo_nick, novo_grupo)
                        st.success(f"Usuário '{novo_nick}' adicionado com sucesso!")
                    except Exception as e:
                        st.exception(e)

with st.expander("✏️ Editar nome no chat"):
    with st.form("form_editar"):
        edit_id = st.text_input("Id Externo do usuário")
        edit_nick = st.text_input("Novo nome no chat")
        submitted_edit = st.form_submit_button("Atualizar")

        if submitted_edit:
            if not edit_id or not edit_nick:
                st.error("Preencha o Id Externo e o novo nome.")
            else:
                with st.spinner("Verificando base..."):
                    df_atual = carregar_base()

                nick_normalizado = normalizar(edit_nick)
                linha_conflito = df_atual[
                    (df_atual["Nome no chat"] == nick_normalizado) &
                    (df_atual["Id Externo"].astype(str) != str(edit_id))
                ]
                if not linha_conflito.empty:
                    st.error(f"Nome '{edit_nick}' já está em uso por outro usuário.")
                else:
                    try:
                        with st.spinner("Atualizando..."):
                            ok, msg = atualizar_nome_chat(edit_id, edit_nick)
                        if ok:
                            st.success(f"Nome atualizado para '{edit_nick}'!")
                        else:
                            st.error(msg)
                    except Exception as e:
                        st.exception(e)
