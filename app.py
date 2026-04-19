import hmac
import pandas as pd
import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from difflib import SequenceMatcher
from datetime import date, timedelta

# ── Config ─────────────────────────────────────────────────────────────────
st.set_page_config(layout="wide", page_title="Freetickets Izão")

# ── Senha ──────────────────────────────────────────────────────────────────
senha = st.text_input("Senha", type="password")
if not hmac.compare_digest(senha, st.secrets["APP_PASSWORD"]):
    st.stop()

# ── Sessão ─────────────────────────────────────────────────────────────────
if "arquivos" not in st.session_state:
    st.session_state.arquivos = {}
if "erros" not in st.session_state:
    st.session_state.erros = []
if "preview" not in st.session_state:
    st.session_state.preview = []

# ── Helpers ────────────────────────────────────────────────────────────────
def normalizar(texto):
    texto = str(texto).strip().lower()
    texto = unicodedata.normalize("NFKC", texto)
    # Remove acentos
    texto = "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )
    # Mantém letras, números e underscore
    texto = re.sub(r"[^\w]", "", texto)
    texto = re.sub(r"_+", "_", texto).strip("_")
    return texto

def similaridade(a, b):
    return SequenceMatcher(None, a, b).ratio()

def sugerir_apelido(apelido_errado, lista_apelidos, threshold=0.6):
    melhor = None
    melhor_score = 0
    for ap in lista_apelidos:
        score = similaridade(apelido_errado, ap)
        if score > melhor_score:
            melhor_score = score
            melhor = ap
    if melhor_score >= threshold:
        return melhor, melhor_score
    return None, 0

def to_timestamp(data, hora_obj) -> int:
    dt_str = f"{data} {hora_obj.strftime('%H:%M')}"
    dt_sp = datetime.strptime(dt_str, "%Y-%m-%d %H:%M").replace(
        tzinfo=ZoneInfo("America/Sao_Paulo")
    )
    return int(dt_sp.timestamp())

def parse_linha(linha_raw: str):
    """
    Aceita formatos como:
      joao 10
      maria: 5
      marcotavares41 10
      brancams : 10 cartelas
      Vamoganha : 50 - 10
    """
    linha = linha_raw.strip()
    match = re.match(r"^(.+?)[\s:,\-]+(\d+)", linha)
    if match:
        return match.group(1).strip(), int(match.group(2))
    # Só apelido sem número
    match_nome = re.match(r"^([\w]+)\s*$", linha)
    if match_nome:
        return match_nome.group(1).strip(), None
    return None, None

# ── Google Sheets ──────────────────────────────────────────────────────────
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
GRUPOS = ["Playbonds Gpas", "Playbonds Generic", "Colonial"]

@st.cache_resource
def get_client():
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
    df["Nome original"] = df["Nome no chat"].astype(str)
    df["Nome no chat"] = df["Nome no chat"].apply(normalizar)
    return df

def salvar_novo_usuario(id_externo, nome_no_chat, grupo):
    client = get_client()
    sheet = client.open_by_key(st.secrets["SHEET_ID"]).sheet1
    # Pega só a coluna B (Id Externo) pra achar a última linha com dado
    col_b = sheet.col_values(2)  # coluna B = índice 2
    proxima_linha = len(col_b) + 1
    nova_linha = ["", id_externo, "", normalizar(nome_no_chat), "", "", "", grupo, ""]
    sheet.update(f"A{proxima_linha}", [nova_linha])
    carregar_base.clear()

def atualizar_nome_chat(id_externo, grupo, novo_nome):
    sheet = get_sheet()
    all_records = sheet.get_all_records()
    headers = sheet.row_values(1)
    ocorrencias = [
        i + 2
        for i, row in enumerate(all_records)
        if str(row.get("Id Externo", "")) == str(id_externo)
        and row.get("grupo", "") == grupo
    ]
    if not ocorrencias:
        return False, f"Nenhum usuário com Id Externo '{id_externo}' no grupo '{grupo}'."
    if len(ocorrencias) > 1:
        return False, f"Encontradas {len(ocorrencias)} linhas com mesmo Id e grupo. Corrija manualmente."
    try:
        col_index = headers.index("Nome no chat") + 1
    except ValueError:
        return False, "Coluna 'Nome no chat' não encontrada no cabeçalho."
    sheet.update_cell(ocorrencias[0], col_index, normalizar(novo_nome))
    carregar_base.clear()
    return True, ""

# ── Lógica de processamento ────────────────────────────────────────────────
def processar_lista(texto, df):
    erros = []
    preview = []
    todos_nicks = df["Nome no chat"].tolist()
    linhas_input = [l.strip() for l in texto.splitlines() if l.strip()]

    for linha_raw in linhas_input:
        apelido_raw, qtd = parse_linha(linha_raw)

        if apelido_raw is None:
            erros.append(f"❌ Linha não reconhecida: `{linha_raw}`")
            continue

        apelido_norm = normalizar(apelido_raw)
        linha_base = df[df["Nome no chat"] == apelido_norm]

        if linha_base.empty:
            sugestao, score = sugerir_apelido(apelido_norm, todos_nicks)
            if sugestao:
                pct = int(score * 100)
                erros.append(
                    f"⚠️ `{apelido_raw}` não encontrado. "
                    f"Você quis dizer **{sugestao}**? ({pct}% similar)"
                )
            else:
                erros.append(f"❌ `{apelido_raw}` não encontrado e nenhum nome parecido na base.")
            continue

        if qtd is None:
            erros.append(f"❌ `{apelido_raw}` — quantidade não informada.")
            continue

        userid = str(int(linha_base["Id Externo"].values[0]))
        grupo = linha_base["grupo"].values[0]
        nome_display = linha_base["Nome original"].values[0]
        preview.append({"apelido": nome_display, "userid": userid, "grupo": grupo, "qtd": qtd})

    return preview, erros

# ── UI Principal ───────────────────────────────────────────────────────────
st.title("🎟️ Freetickets Izão v2.1 Turbo")

with st.expander("ℹ️ Como usar / Problemas conhecidos"):
    st.markdown("""
- O sistema sugere o mais parecido quando não encontra exato.
- Formatos aceitos: `joao 10`, `maria: 5`, `brancams : 10 cartelas`, `Vamoganha : 50 fts`
- Use **Verificar lista** para checar erros antes de gerar o arquivo se precisar.
""")

col1, col2 = st.columns([3, 1])

with col1:
    col_data, col_hora, col_min = st.columns([2, 1, 1])
    with col_data:
        data = st.date_input("📅 Data", value=date.today() + timedelta(days=1))
    with col_hora:
        hora_h = st.number_input("🕐 Hora", min_value=0, max_value=23, value=12, step=1)
    with col_min:
        hora_m = st.number_input("Minuto", min_value=0, max_value=59, value=0, step=1)
    hora_obj = datetime.strptime(f"{hora_h:02d}:{hora_m:02d}", "%H:%M").time()

    texto = st.text_area(
        "Lista de apelidos e cartelas",
        height=300,
        placeholder="Exemplos:\njoao 10\nmaria 5 fts\nJuriscleuza 3\nVamoperde: 5\nVamoganha : 50"
    )

    col_btn1, col_btn2 = st.columns(2)
    verificar = col_btn1.button("🔍 Verificar lista", use_container_width=True)
    gerar_csv = col_btn2.button("✅ Gerar CSVs", use_container_width=True)

    # ── Verificar ──────────────────────────────────────────────────────────
    if verificar:
        with st.spinner("Buscando base de usuários..."):
            try:
                df = carregar_base()
            except Exception as e:
                st.exception(e)
                st.stop()
        preview, erros = processar_lista(texto, df)
        st.session_state.erros = erros
        st.session_state.preview = preview
        st.session_state.arquivos = {}

    # ── Gerar CSVs ─────────────────────────────────────────────────────────
    if gerar_csv:
        with st.spinner("Buscando base de usuários..."):
            try:
                df = carregar_base()
            except Exception as e:
                st.exception(e)
                st.stop()

        preview, erros = processar_lista(texto, df)
        st.session_state.erros = erros
        st.session_state.preview = preview
        st.session_state.arquivos = {}

        if erros:
            st.warning("Há erros na lista — corrija e tente novamente.")
        else:
            timestamp = to_timestamp(data.strftime("%Y-%m-%d"), hora_obj)
            grupos = {}
            for row in preview:
                qtd = row["qtd"]
                grupo = row["grupo"]
                userid = row["userid"]
                if grupo not in grupos:
                    grupos[grupo] = []
                while qtd > 0:
                    lote = min(qtd, 50)
                    grupos[grupo].append([userid, lote, timestamp, 0.50, 98])
                    qtd -= lote

            arquivos = {}
            for grupo, linhas in grupos.items():
                csv_data = "\n".join(",".join(map(str, l)) for l in linhas)
                arquivos[f"{grupo}.csv"] = csv_data
            st.session_state.arquivos = arquivos
            st.success("✅ CSVs gerados! Baixe abaixo.")

    # ── Preview ────────────────────────────────────────────────────────────
    if st.session_state.preview:
        st.subheader("📋 Preview")
        prev_df = pd.DataFrame(st.session_state.preview)[["apelido", "grupo", "qtd", "userid"]]
        prev_df.columns = ["Nome no chat", "Grupo", "Cartelas", "User ID"]
        st.dataframe(prev_df, use_container_width=True, hide_index=True)
        total = sum(r["qtd"] for r in st.session_state.preview)
        st.caption(f"Total: **{len(st.session_state.preview)} usuários** · **{total} cartelas**")

with col2:
    st.subheader("Status")
    if st.session_state.erros:
        st.error(f"{len(st.session_state.erros)} problema(s):")
        for e in st.session_state.erros:
            st.markdown(e)
    elif st.session_state.arquivos:
        st.success("CSVs prontos para download!")
    elif st.session_state.preview:
        st.success("Lista ok! Clique em Gerar CSVs.")
    else:
        st.info("Sistema pronto")

# ── Downloads ──────────────────────────────────────────────────────────────
if st.session_state.arquivos:
    st.subheader("📥 Arquivos gerados")
    cols = st.columns(len(st.session_state.arquivos))
    for i, (nome, conteudo) in enumerate(st.session_state.arquivos.items()):
        cols[i].download_button(
            f"⬇️ {nome}", conteudo, nome, "text/csv",
            key=f"dl_{nome}", use_container_width=True,
        )

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
                duplicado_id_grupo = not df_atual[
                    (df_atual["Id Externo"].astype(str) == str(novo_id)) &
                    (df_atual["grupo"] == novo_grupo)
                ].empty
                duplicado_nick = normalizar(novo_nick) in df_atual["Nome no chat"].values
                if duplicado_id_grupo:
                    st.error(f"Id Externo '{novo_id}' já existe no grupo '{novo_grupo}'.")
                elif duplicado_nick:
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
        edit_grupo = st.selectbox("Grupo", GRUPOS)
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
                    ~(
                        (df_atual["Id Externo"].astype(str) == str(edit_id)) &
                        (df_atual["grupo"] == edit_grupo)
                    )
                ]
                if not linha_conflito.empty:
                    st.error(f"Nome '{edit_nick}' já está em uso por outro usuário.")
                else:
                    try:
                        with st.spinner("Atualizando..."):
                            ok, msg = atualizar_nome_chat(edit_id, edit_grupo, edit_nick)
                        if ok:
                            st.success(f"Nome atualizado para '{edit_nick}'!")
                        else:
                            st.error(msg)
                    except Exception as e:
                        st.exception(e)

with st.expander("🔍 Buscar usuário na base"):
    busca = st.text_input("Digite nome ou parte do nome")
    if busca:
        with st.spinner("Buscando..."):
            df_atual = carregar_base()
        busca_norm = normalizar(busca)
        resultado = df_atual[df_atual["Nome no chat"].str.contains(busca_norm, na=False)]
        if resultado.empty:
            sugestao, score = sugerir_apelido(busca_norm, df_atual["Nome no chat"].tolist())
            if sugestao:
                st.warning(f"Nenhum resultado exato. Mais parecido: **{sugestao}** ({int(score*100)}% similar)")
            else:
                st.warning("Nenhum usuário encontrado.")
        else:
            cols_exibir = [c for c in ["Nome original", "Id Externo", "grupo"] if c in resultado.columns]
            st.dataframe(resultado[cols_exibir], use_container_width=True, hide_index=True)
