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

# --- 5. LOGICA APPLICATIVA ---
if supabase:
    res = supabase.table("health_logs").select("*").order("created_at").execute()
    df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
    
    if not df.empty:
        df['created_at'] = pd.to_datetime(df['created_at'], format='ISO8601', errors='coerce').dt.tz_localize(None)
        df = df.dropna(subset=['created_at'])

    st.title("🩺 Sanity Diary Intelligence")

    if not df.empty:
        # Metriche compatte
        m = st.columns(4)
        def get_delta(col):
            vals = df[col].dropna()
            return round(float(vals.iloc[-1] - vals.iloc[-2]), 1) if len(vals) >= 2 else 0

        m[0].metric("O2", f"{df['oxygen'].iloc[-1]}%", get_delta('oxygen'))
        m[1].metric("BPM", f"{df['bpm'].iloc[-1]}", get_delta('bpm'), delta_color="inverse")
        m[2].metric("Press.", f"{df['systolic'].iloc[-1]}", get_delta('systolic'), delta_color="inverse")
        m[3].metric("Peso", f"{df['weight'].iloc[-1]}kg", get_delta('weight'))

        st.divider()
        tabs = st.tabs(["📈 Trend", "🧬 Pearson", "🤖 Assistente IA", "📅 Visite", "📂 Referti", "📋 Registro"])

        with tabs[0]:
            st.plotly_chart(px.line(df.sort_values('created_at'), x='created_at', y=['oxygen', 'bpm', 'systolic'], markers=True), use_container_width=True)

        with tabs[4]:
            st.subheader("📂 Archivio Documenti")
            
            with st.expander("➕ Carica nuovo referto"):
                up = st.file_uploader("Seleziona PDF", type="pdf")
                nome_ref = st.text_input("Titolo referto")
                if st.form_submit_button("Salva") and up:
                    b64 = base64.b64encode(up.read()).decode('utf-8')
                    supabase.table("referti_medici").insert({"nome_referto": nome_ref if nome_ref else up.name, "data_esame": str(datetime.now().date()), "file_path": b64}).execute()
                    st.rerun()

            st.write("") # Spaziatore
            
            # --- SEZIONE REFERTI COMPATTA ---
            res_r = supabase.table("referti_medici").select("*").order("data_esame", desc=True).execute()
            referti = res_r.data if res_r.data else []
            
            if not referti:
                st.info("Nessun referto presente.")
            else:
                # Header della "tabella" manuale per risparmiare spazio
                st.markdown("""<div style='display:flex; font-weight:bold; border-bottom:1px solid #ccc; padding-bottom:5px; margin-bottom:10px;'>
                    <div style='flex:3;'>Nome Referto</div>
                    <div style='flex:1;'>Data</div>
                    <div style='flex:2; text-align:right;'>Azioni</div>
                </div>""", unsafe_allow_html=True)

                for r in referti:
                    # Riga molto stretta
                    col_info, col_date, col_btns = st.columns([3, 1, 2])
                    
                    with col_info:
                        st.markdown(f"**{r['nome_referto']}**")
                    
                    with col_date:
                        st.markdown(f"<span style='color:gray'>{r['data_esame']}</span>", unsafe_allow_html=True)
                    
                    with col_btns:
                        # Layout orizzontale per i bottoni
                        sub_c1, sub_c2 = st.columns(2)
                        
                        # Download
                        file_bytes = base64.b64decode(r['file_path'])
                        sub_c1.download_button("💾", file_bytes, file_name=f"{r['nome_referto']}.pdf", key=f"dl_{r['id']}", help="Scarica PDF")
                        
                        # Anteprima (Apre in una nuova tab per evitare il blocco Chrome)
                        pdf_base64 = r['file_path']
                        preview_link = f'<a href="data:application/pdf;base64,{pdf_base64}" target="_blank" style="text-decoration:none;"><button style="border-radius:5px; border:1px solid #ccc; padding:3px 10px; cursor:pointer;">👁️ Visualizza</button></a>'
                        sub_c2.markdown(preview_link, unsafe_allow_html=True)
                    
                    st.markdown("<hr style='margin:2px 0; border:0.1px solid #eee;'>", unsafe_allow_html=True)

        with tabs[5]:
            st.dataframe(df.sort_values(by='created_at', ascending=False), use_container_width=True)

    with st.sidebar:
        st.header("⚙️ Nuova Misura")
        with st.form("h", clear_on_submit=True):
            o, b, s, d, w, t = st.number_input("O2%", 0), st.number_input("BPM", 0), st.number_input("Sist.", 0), st.number_input("Diast.", 0), st.number_input("Peso", 0.0), st.number_input("Temp", 0.0)
            n = st.text_area("Note")
            if st.form_submit_button("Salva"):
                supabase.table("health_logs").insert({"oxygen":o, "bpm":b, "systolic":s, "diastolic":d, "weight":w, "temperature":t, "notes":n}).execute()
                st.rerun()
        if st.button("Logout"): st.session_state.authenticated = False; st.rerun()
