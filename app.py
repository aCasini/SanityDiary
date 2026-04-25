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

# --- 4. FUNZIONI IA E PDF ---
def clean_text(text):
    if not text: return ""
    return text.encode('latin-1', 'replace').decode('latin-1').replace('?', ' ')

def get_ai_narrative_analysis(df):
    if not client_ai: return "Chiave API non configurata."
    if df.empty or len(df) < 2: return "Dati insufficienti per l'analisi."
    recent = df.sort_values(by='created_at', ascending=False).head(10)
    summary = recent.to_string(columns=['created_at', 'oxygen', 'bpm', 'systolic', 'diastolic', 'notes', 'temperature'])
    prompt = f"Contesto: Post-Embolia Polmonare Estesa. Analizza trend: {summary}. Solo testo, no emoji."
    try:
        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Sei un medico."}, {"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e: return f"Errore API: {str(e)}"

# --- 5. LOGICA APPLICATIVA ---
if supabase:
    res = supabase.table("health_logs").select("*").order("created_at").execute()
    df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
    
    if not df.empty:
        df['created_at'] = pd.to_datetime(df['created_at'], format='ISO8601', errors='coerce').dt.tz_localize(None)
        df = df.dropna(subset=['created_at'])

    st.title("🩺 Sanity Diary Intelligence")

    if not df.empty:
        # Metriche
        m = st.columns(4)
        def get_delta(col):
            vals = df[col].dropna()
            return round(float(vals.iloc[-1] - vals.iloc[-2]), 1) if len(vals) >= 2 else None

        m[0].metric("Ossigeno", f"{df['oxygen'].iloc[-1]}%", get_delta('oxygen'))
        m[1].metric("BPM", f"{df['bpm'].iloc[-1]}", get_delta('bpm'), delta_color="inverse")
        m[2].metric("Press. Max", f"{df['systolic'].iloc[-1]}", get_delta('systolic'), delta_color="inverse")
        m[3].metric("Peso", f"{df['weight'].iloc[-1]}kg", get_delta('weight'))

        st.divider()
        tabs = st.tabs(["📈 Trend", "🧬 Pearson", "🤖 Assistente IA", "📅 Visite", "📂 Referti", "📋 Registro"])

        with tabs[0]:
            all_params = ['oxygen', 'bpm', 'systolic', 'diastolic', 'weight', 'temperature']
            st.plotly_chart(px.line(df.sort_values('created_at'), x='created_at', y=[c for c in all_params if c in df.columns], markers=True, template="plotly_white"), use_container_width=True)

        with tabs[1]:
            if len(df) > 2:
                st.plotly_chart(px.imshow(df[[c for c in all_params if c in df.columns]].corr(), text_auto=".2f", color_continuous_scale='RdBu_r'), use_container_width=True)

        with tabs[2]:
            if st.button("Esegui Analisi"):
                with st.spinner("Analizzando..."): st.session_state.ai_text = get_ai_narrative_analysis(df)
            if "ai_text" in st.session_state: st.info(st.session_state.ai_text)

        with tabs[3]:
            # Visite (Codice GitHub stabile)
            v_data = supabase.table("visite_mediche").select("*").order("data_visita").execute().data or []
            for v in v_data:
                st.write(f"{'✅' if v['completata'] else '⏳'} {v['data_visita']}: {v['nome_visita']}")

        # --- SEZIONE REFERTI UX FRIENDLY ---
        with tabs[4]:
            st.subheader("📂 Gestione Documenti")
            
            # Upload migliorato
            with st.expander("➕ Carica nuovo referto"):
                up = st.file_uploader("Seleziona PDF", type="pdf")
                nome_ref = st.text_input("Titolo del documento (es. Esami del sangue)")
                if st.button("Salva nel cloud") and up:
                    b64 = base64.b64encode(up.read()).decode('utf-8')
                    supabase.table("referti_medici").insert({
                        "nome_referto": nome_ref if nome_ref else up.name, 
                        "data_esame": str(datetime.now().date()), 
                        "file_path": b64
                    }).execute()
                    st.success("Referto salvato!"); st.rerun()

            st.divider()
            
            # Visualizzazione a Card con Preview
            res_r = supabase.table("referti_medici").select("*").order("data_esame", desc=True).execute()
            referti = res_r.data if res_r.data else []
            
            if not referti:
                st.info("Nessun referto presente.")
            else:
                for r in referti:
                    with st.container():
                        c1, c2, c3 = st.columns([3, 1, 1])
                        c1.markdown(f"**{r['nome_referto']}** \n<small>Data caricamento: {r['data_esame']}</small>", unsafe_allow_html=True)
                        
                        # Bottone Download
                        file_bytes = base64.b64decode(r['file_path'])
                        c2.download_button("💾 Scarica", file_bytes, file_name=f"{r['nome_referto']}.pdf", key=f"dl_{r['id']}")
                        
                        # Bottone Preview (espande un'area sotto la card)
                        if c3.button("👁️ Anteprima", key=f"pre_{r['id']}"):
                            st.session_state[f"show_{r['id']}"] = not st.session_state.get(f"show_{r['id']}", False)
                        
                        if st.session_state.get(f"show_{r['id']}", False):
                            # Embedding del PDF
                            base64_pdf = r['file_path']
                            pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="600" type="application/pdf"></iframe>'
                            st.markdown(pdf_display, unsafe_allow_html=True)
                        st.divider()

        with tabs[5]:
            st.dataframe(df.sort_values(by='created_at', ascending=False), use_container_width=True)

    with st.sidebar:
        st.header("⚙️ Nuova Misura")
        with st.form("h", clear_on_submit=True):
            o, b = st.number_input("O2%", 0), st.number_input("BPM", 0)
            s, d = st.number_input("Sist.", 0), st.number_input("Diast.", 0)
            w, t = st.number_input("Peso", 0.0), st.number_input("Temp", 0.0)
            n = st.text_area("Note")
            if st.form_submit_button("Salva"):
                supabase.table("health_logs").insert({"oxygen":o, "bpm":b, "systolic":s, "diastolic":d, "weight":w, "temperature":t, "notes":n}).execute()
                st.rerun()
        if st.button("Logout"): st.session_state.authenticated = False; st.rerun()
