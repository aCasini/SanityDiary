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
st.set_page_config(page_title="Sanity Diary AI - Controllo Attivo", page_icon="🧬", layout="wide")

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

# --- 4. FUNZIONI IA E UTILITY ---
def clean_text(text):
    if not text: return ""
    return text.encode('latin-1', 'replace').decode('latin-1').replace('?', ' ')

def get_ai_narrative_analysis(df, terapia_df=None):
    if not client_ai: return "Chiave API non configurata."
    if df.empty: return "Dati insufficienti."
    
    recent = df.sort_values(by='created_at', ascending=False).head(10)
    terapia_info = terapia_df.tail(7).to_string() if terapia_df is not None else "Non pervenuta"
    
    prompt = f"""
    PAZIENTE: Post-Embolia Polmonare Estesa.
    DATI RECENTI: {recent.to_string(columns=['created_at', 'oxygen', 'bpm', 'systolic', 'diastolic', 'notes'])}
    TERAPIA ULTIMI 7 GG: {terapia_info}
    
    Analizza la stabilità. Se l'O2 è < 95% o i BPM > 100 a riposo, evidenzia il rischio. 
    Controlla se la terapia anticoagulante è stata assunta regolarmente.
    """
    
    try:
        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Sei un cardiologo esperto."},
                      {"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Errore API: {str(e)}"

# --- 5. CARICAMENTO DATI ---
if supabase:
    # Log Salute
    res = supabase.table("health_logs").select("*").order("created_at").execute()
    df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
    if not df.empty:
        df['created_at'] = pd.to_datetime(df['created_at'], format='ISO8601', errors='coerce').dt.tz_localize(None)
        df = df.dropna(subset=['created_at'])

    # Log Terapia (Assumendo esista tabella 'terapia_logs', altrimenti la gestiamo in locale per ora)
    try:
        res_t = supabase.table("terapia_logs").select("*").order("data").execute()
        terapia_df = pd.DataFrame(res_t.data) if res_t.data else pd.DataFrame()
    except:
        terapia_df = pd.DataFrame()

    st.title("🩺 Controllo Attivo Post-Embolia")

    # Banner Visite
    try:
        res_v = supabase.table("visite_mediche").select("*").eq("completata", False).order("data_visita").execute()
        if res_v.data:
            st.warning(f"📅 Prossima Visita: {res_v.data[0]['nome_visita']} il {res_v.data[0]['data_visita']}")
    except: pass

    if not df.empty:
        # --- DASHBOARD CON COLOR CODING ---
        m = st.columns(4)
        latest = df.iloc[-1]
        
        # Logica Colori Ossigeno
        o2 = latest['oxygen']
        o2_color = "normal" if o2 >= 96 else "off" if o2 >= 94 else "inverse"
        m[0].metric("Saturazione O2", f"{o2}%", f"{o2-df.iloc[-2]['oxygen'] if len(df)>1 else 0}%", delta_color=o2_color)

        # Logica Colori BPM
        bpm = latest['bpm']
        bpm_color = "normal" if bpm <= 90 else "off" if bpm <= 100 else "inverse"
        m[1].metric("Battiti (BPM)", f"{bpm}", f"{bpm-df.iloc[-2]['bpm'] if len(df)>1 else 0}", delta_color=bpm_color)

        m[2].metric("Pressione Max", f"{latest['systolic']}", delta_color="normal")
        m[3].metric("Peso", f"{latest['weight']} kg")

        st.divider()
        tabs = st.tabs(["📈 Trend", "💊 Terapia", "🧬 Pearson", "🤖 IA Specialist", "📅 Visite", "📂 Referti", "📋 Registro"])

        with tabs[0]:
            params = ['oxygen', 'bpm', 'systolic', 'diastolic', 'weight', 'temperature']
            st.plotly_chart(px.line(df.sort_values('created_at'), x='created_at', y=[c for c in params if c in df.columns], markers=True), use_container_width=True)

        with tabs[1]:
            st.subheader("Gestione Terapia Anticoagulante")
            col_t1, col_t2 = st.columns([1, 2])
            with col_t1:
                with st.form("terapia_form"):
                    farmaco = st.text_input("Farmaco (es. Eliquis)", "Anticoagulante")
                    dose = st.text_input("Dose", "5mg")
                    preso = st.checkbox("Assunto oggi?")
                    if st.form_submit_button("Registra Assunzione"):
                        try:
                            supabase.table("terapia_logs").insert({"data": str(datetime.now().date()), "farmaco": farmaco, "dose": dose, "assunto": preso}).execute()
                            st.success("Terapia registrata!"); st.rerun()
                        except: st.error("Tabella 'terapia_logs' non trovata su DB.")
            with col_t2:
                if not terapia_df.empty:
                    st.dataframe(terapia_df.sort_values('data', ascending=False).head(10), use_container_width=True)
                else: st.info("Nessun dato di terapia registrato.")

        with tabs[2]: # Pearson
            if len(df) > 2:
                st.plotly_chart(px.imshow(df[[c for c in params if c in df.columns]].corr(), text_auto=".2f", color_continuous_scale='RdBu_r'), use_container_width=True)

        with tabs[3]: # IA
            if st.button("Analisi Incrociata Dati/Terapia"):
                with st.spinner("Analisi in corso..."):
                    st.session_state.ai_text = get_ai_narrative_analysis(df, terapia_df)
            st.markdown(st.session_state.get("ai_text", "Clicca per iniziare."))

        with tabs[4]: # Visite (Logica esistente)
            v_data = supabase.table("visite_mediche").select("*").order("data_visita").execute().data or []
            for v in v_data:
                ca, cb = st.columns([4, 1])
                ca.write(f"{'✅' if v['completata'] else '⏳'} **{v['data_visita']}**: {v['nome_visita']}")
                if not v['completata'] and cb.button("Fatto", key=f"v_{v['id']}"):
                    supabase.table("visite_mediche").update({"completata":True}).eq("id", v['id']).execute(); st.rerun()

        with tabs[5]: # Referti
            up = st.file_uploader("Carica PDF", type="pdf")
            if st.button("Salva") and up:
                b64 = base64.b64encode(up.read()).decode('utf-8')
                supabase.table("referti_medici").insert({"nome_referto":up.name, "file_path":b64}).execute(); st.rerun()
            for r in (supabase.table("referti_medici").select("*").execute().data or []):
                st.download_button(f"📄 {r['nome_referto']}", base64.b64decode(r['file_path']), key=f"r_{r['id']}")

        with tabs[6]: # Registro
            st.dataframe(df.sort_values('created_at', ascending=False), use_container_width=True)

    with st.sidebar:
        st.header("⚙️ Nuova Misura")
        with st.form("h", clear_on_submit=True):
            o, b = st.number_input("O2%", 0), st.number_input("BPM", 0)
            s, d = st.number_input("Sist.", 0), st.number_input("Diast.", 0)
            w, t = st.number_input("Peso", 0.0), st.number_input("Temp", 0.0)
            n = st.text_area("Note (es. muco, dolore)")
            if st.form_submit_button("Salva"):
                supabase.table("health_logs").insert({"oxygen":o, "bpm":b, "systolic":s, "diastolic":d, "weight":w, "temperature":t, "notes":n}).execute()
                st.rerun()
        if st.button("Logout"): st.session_state.authenticated = False; st.rerun()
