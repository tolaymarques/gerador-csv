# pages/tradutor.py
import streamlit as st
from deep_translator import GoogleTranslator
from concurrent.futures import ThreadPoolExecutor

st.set_page_config(page_title="Tradutor HTML", layout="wide")
st.title("Tradutor HTML EN → PT & ES")
st.caption("Cole um texto em inglês e gere versões em português e espanhol com formatação HTML.")

def formatar_html(texto: str) -> str:
    paragrafos = texto.strip().split("\n\n")
    return "\n".join(f"<p>{p.strip().replace(chr(10), '<br>')}</p>" for p in paragrafos)

def traduzir_para(target: str, texto: str) -> str:
    return GoogleTranslator(source='en', target=target).translate(texto)

texto = st.text_area("Texto em inglês", height=200, placeholder="Cole o texto aqui...")

col_info, col_btn = st.columns([3, 1])
with col_info:
    if texto:
        st.caption(f"{len(texto)} caracteres · {len(texto.split())} palavras")

with col_btn:
    traduzir = st.button("Traduzir", type="primary", use_container_width=True)

if traduzir:
    if not texto.strip():
        st.warning("Insira um texto em inglês antes de traduzir.")
    else:
        with st.spinner("Traduzindo..."):
            try:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    fut_pt = executor.submit(traduzir_para, 'pt', texto)
                    fut_es = executor.submit(traduzir_para, 'es', texto)
                    trad_pt = fut_pt.result()
                    trad_es = fut_es.result()

                resultados = {
                    "🇺🇸 Inglês (original)": texto,
                    "🇧🇷 Português": trad_pt,
                    "🇪🇸 Espanhol": trad_es,
                }

                for label, conteudo in resultados.items():
                    st.subheader(label)
                    col_html, col_preview = st.tabs(["HTML formatado", "Preview"])
                    html = formatar_html(conteudo)
                    with col_html:
                        st.code(html, language="html")
                    with col_preview:
                        st.markdown(conteudo)

            except Exception as e:
                st.error(f"Erro na tradução: {e}")
