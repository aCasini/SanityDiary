import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
from datetime import datetime
import base64
from fpdf import FPDF
import streamlit.components.v1 as components
from openai import OpenAI

# --- 1. CONFIGURAZIONE PAGINA & PWA ---
st.set_page_config(page_title="Sanity Diary AI", page_icon="🧬", layout="wide")

def inject_pwa():
    pwa_html = """<link rel="manifest" href="./manifest.json"><script>if('serviceWorker' in navigator){navigator.serviceWorker.register('./sw.js');}</script>"""
    components.html(pwa_html, height=0)

inject_pwa()

# --- 2. AUTHENTICATION ---
def check_password():
    if "authenticated" not in st.session_state: st.session_state.authenticated = False
    if st.session_state.authenticated: return True
    st.title("🔐 Accesso Riservato")
    with st.form("login"):
        password = st.text_input("Password:", type="password")
        if st.form_submit_button("Accedi"):
            if password == st.secrets.get("APP_PASSWORD"):
                st.session_state.authenticated = True
                st.rerun()
            else: st.error("Password errata")
    return False

if not check_password(): st.stop()

# --- 3. CONNESSIONE ---
@st.cache_resource
def init_db():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

supabase = init_db()

try:
    api_key = st.secrets.get("OPENAI_API_KEY")
    client_ai = OpenAI(api_key=api_key) if api_key else None
except:
    client_ai = None

# --- 4. FUNZIONI UTILITY ---
def clean_text(text):
    if not text: return ""
    return text.encode('latin-1', 'replace').decode('latin-1').replace('?', ' ')

def get_ai_narrative_analysis(df, terapia_df=None):
    if not client_ai: return "Chiave API non configurata."
    if df.empty: return "Dati insufficienti."
    recent = df.sort_values(by='created_at', ascending=False).head(10)
    terapia_info = terapia_df.tail(7).to_string() if (terapia_df is not None and not terapia_df.empty) else "Nessuna terapia registrata."
    prompt = f"PAZIENTE: Post-Embolia Polmonare. DATI: {recent.to_string()} TERAPIA: {terapia_info}. Analizza stabilità e rischi."
    try:
        response = client_ai.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}])
        return response.choices[0].message.content
    except Exception as e: return f"Errore: {e}"

# --- 5. LOGICA APPLICATIVA ---
if supabase:
    # Caricamento dati
    res = supabase.table("health_logs").select("*").order("created_at").execute()
    df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
    if not df.empty:
        df['created_at'] = pd.to_datetime(df['created_at'], format='ISO8601', errors='coerce').dt.tz_localize(None)
    
    try:
        res_t = supabase.table("terapia_logs").select("*").order("data").execute()
        terapia_df = pd.DataFrame(res_t.data) if res_t.data else pd.DataFrame()
    except: terapia_df = pd.DataFrame()

    st.title("🩺 Controllo Attivo Post-Embolia")

    if not df.empty:
        # Metriche con Color Coding
        m = st.columns(4)
        latest = df.iloc[-1]
        m[0].metric("Saturazione O2", f"{latest['oxygen']}%", delta_color="normal" if latest['oxygen']>=95 else "inverse")
        m[1].metric("BPM", f"{latest['bpm']}", delta_color="normal" if latest['bpm']<=90 else "inverse")
        m[2].metric("Pressione Max", f"{latest['systolic']}")
        m[3].metric("Peso", f"{latest['weight']} kg")

        st.divider()
        tabs = st.tabs(["📈 Trend", "💊 Terapia", "🤖 IA Specialist", "📅 Visite", "📂 Referti UX", "📋 Registro"])

        with tabs[0]:
            st.plotly_chart(px.line(df, x='created_at', y=['oxygen', 'bpm', 'systolic'], markers=True), use_container_width=True)

        with tabs[1]:
            with st.form("t_form"):
                f, d, p = st.text_input("Farmaco"), st.text_input("Dose"), st.checkbox("Preso")
                if st.form_submit_button("Salva Terapia"):
                    supabase.table("terapia_logs").insert({"data": str(datetime.now().date()), "farmaco": f, "dose": d, "assunto": p}).execute()
                    st.rerun()

        with tabs[2]:
            if st.button("Analizza"): st.write(get_ai_narrative_analysis(df, terapia_df))

        with tabs[3]:
            # Gestione Visite (Codice stabile)
            res_v = supabase.table("visite_mediche").select("*").order("data_visita").execute()
            for v in (res_v.data or []):
                st.write(f"{'✅' if v['completata'] else '⏳'} {v['data_visita']}: {v['nome_visita']}")

        # --- SEZIONE REFERTI UX MIGLIORATA ---
        with tabs[4]:
            st.subheader("📂 Archivio Digitale Referti")
            
            # Area Upload con stile
            with st.expander("➕ Carica Nuovo Documento", expanded=False):
                up_file = st.file_uploader("Trascina qui il PDF del referto", type="pdf")
                nome_custom = st.text_input("Nome mnemonico (es. Ecocardio Aprile)")
                if st.button("Conferma Caricamento") and up_file:
                    with st.spinner("Archiviazione in corso..."):
                        b64 = base64.b64encode(up_file.read()).decode('utf-8')
                        nome_finale = nome_custom if nome_custom else up_file.name
                        supabase.table("referti_medici").insert({
                            "nome_referto": nome_finale,
                            "data_esame": str(datetime.now().date()),
                            "file_path": b64
                        }).execute()
                        st.success("Documento salvato con successo!")
                        st.rerun()

            st.divider()

            # Ricerca e Visualizzazione
            res_r = supabase.table("referti_medici").select("*").order("data_esame", desc=True).execute()
            referti = res_r.data if res_r.data else []

            if not referti:
                st.info("Nessun referto ancora archiviato.")
            else:
                search = st.text_input("🔍 Cerca tra i referti...", "")
                
                # Visualizzazione a Card
                cols = st.columns(3)
                idx = 0
                for r in referti:
                    if search.lower() in r['nome_referto'].lower():
                        with cols[idx % 3]:
                            st.markdown(f"""
                            <div style="border: 1px solid #ddd; padding: 15px; border-radius: 10px; background-color: #f9f9f9; margin-bottom: 10px">
                                <h4 style="margin:0">📄 {r['nome_referto']}</h4>
                                <p style="color: gray; font-size: 0.8em;">Data: {r['data_esame']}</p>
                            </div>
                            """, unsafe_allow_html=True)
                            
                            # Bottone download posizionato sotto la card
                            st.download_button(
                                label="Download PDF",
                                data=base64.b64decode(r['file_path']),
                                file_name=f"{r['nome_referto']}.pdf",
                                mime="application/pdf",
                                key=f"dl_{r['id']}"
                            )
                        idx += 1

        with tabs[5]:
            st.dataframe(df.sort_values('created_at', ascending=False), use_container_width=True)

    with st.sidebar:
        st.header("⚙️ Inserimento")
        with st.form("h", clear_on_submit=True):
            o, b, s, d, w, t = st.number_input("O2%", 0), st.number_input("BPM", 0), st.number_input("Sist.", 0), st.number_input("Diast.", 0), st.number_input("Peso", 0.0), st.number_input("Temp", 0.0)
            n = st.text_area("Note")
            if st.form_submit_button("Salva"):
                supabase.table("health_logs").insert({"oxygen":o, "bpm":b, "systolic":s, "diastolic":d, "weight":w, "temperature":t, "notes":n}).execute()
                st.rerun()
