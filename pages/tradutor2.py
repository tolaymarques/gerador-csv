```python
import streamlit as st
import requests
import html

st.set_page_config(page_title="Tradutor HTML", layout="wide")

st.title("Tradutor HTML EN → PT & ES")
st.caption(
    "Cole um texto em inglês e gere versões em português e espanhol "
    "com formatação HTML."
)


def formatar_html(texto: str) -> str:
    paragrafos = texto.strip().split("\n\n")

    return "\n".join(
        f"<p>{p.strip().replace(chr(10), '<br>')}</p>"
        for p in paragrafos
    )


def traduzir_para(target: str, texto: str) -> str:
    url = "https://api.mymemory.translated.net/get"

    params = {
        "q": texto,
        "langpair": f"en|{target}"
    }

    resposta = requests.get(
        url,
        params=params,
        timeout=30
    )

    resposta.raise_for_status()

    dados = resposta.json()

    if dados.get("responseStatus") != 200:
        mensagem = dados.get(
            "responseDetails",
            "Erro desconhecido na tradução."
        )
        raise Exception(mensagem)

    traducao = dados["responseData"]["translatedText"]

    # O MyMemory pode devolver HTML escapado
    return html.unescape(traducao)


texto = st.text_area(
    "Texto em inglês",
    height=200,
    placeholder="Cole o texto aqui..."
)


col_info, col_btn = st.columns([3, 1])

with col_info:
    if texto:
        st.caption(
            f"{len(texto)} caracteres · "
            f"{len(texto.split())} palavras"
        )

with col_btn:
    traduzir = st.button(
        "Traduzir",
        type="primary",
        use_container_width=True
    )


if traduzir:

    if not texto.strip():
        st.warning(
            "Insira um texto em inglês antes de traduzir."
        )

    else:

        with st.spinner("Traduzindo..."):

            try:

                # Inglês → Português
                trad_pt = traduzir_para("pt", texto)

                # Inglês → Espanhol
                trad_es = traduzir_para("es", texto)

                resultados = {
                    "🇺🇸 Inglês (original)": texto,
                    "🇧🇷 Português": trad_pt,
                    "🇪🇸 Espanhol": trad_es,
                }

                for label, conteudo in resultados.items():

                    st.subheader(label)

                    col_html, col_preview = st.tabs(
                        ["HTML formatado", "Preview"]
                    )

                    html_formatado = formatar_html(conteudo)

                    with col_html:
                        st.code(
                            html_formatado,
                            language="html"
                        )

                    with col_preview:
                        st.markdown(conteudo)

            except Exception as e:

                st.error(
                    f"Erro na tradução: {e}"
                )
```
