import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
from datetime import datetime
import base64
from fpdf import FPDF
import streamlit.components.v1 as components
from openai import OpenAI
import io
import re

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Sanity Diary AI", page_icon="🧬", layout="wide")

# Init DB e AI
@st.cache_resource
def init_db():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

supabase = init_db()
client_ai = OpenAI(api_key=st.secrets.get("OPENAI_API_KEY"))

# --- FUNZIONI UTILI ---
def clean_text_for_pdf(text):
    if not text: return ""
    # Rimuove Markdown e caratteri speciali che rompono FPDF
    clean = re.sub(r'\*\*|__|#', '', text)
    return clean.encode('latin-1', 'replace').decode('latin-1').replace('?', ' ')

def get_ai_analysis(df, profile, context="", is_report=False):
    recent = df.sort_values(by='created_at', ascending=False).head(15)
    data_summary = recent.to_string(columns=['created_at', 'oxygen', 'bpm', 'systolic', 'diastolic', 'weight', 'temperature', 'notes'])
    sys_prompt = f"Sei un medico. Paziente: {profile['nome_paziente']}. Quadro: {profile['quadro_clinico']}. Terapia: {profile['terapia_attuale']}. Soglia O2: {profile['soglia_ossigeno_min']}%."
    prompt = f"DATI:\n{data_summary}\n\nEXTRA: {context}"
    try:
        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e: return f"Errore: {e}"

# --- LOGICA AUTH ---
if "authenticated" not in st.session_state: st.session_state.authenticated = False
if not st.session_state.authenticated:
    with st.form("login"):
        if st.text_input("Password", type="password") == st.secrets.get("APP_PASSWORD") and st.form_submit_button("Entra"):
            st.session_state.authenticated = True
            st.rerun()
    st.stop()

# --- RECUPERO DATI ---
p_res = supabase.table("user_profile").select("*").eq("id", 1).execute()
profile = p_res.data[0] if p_res.data else {"nome_paziente": "Alessio", "quadro_clinico": "", "terapia_attuale": "", "soglia_ossigeno_min": 94}

res = supabase.table("health_logs").select("*").order("created_at").execute()
df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
if not df.empty:
    df['created_at'] = pd.to_datetime(df['created_at'], format='mixed', errors='coerce').dt.tz_localize(None)
    df = df.dropna(subset=['created_at']).sort_values('created_at')

# --- UI ---
st.title(f"🧬 Sanity Diary: {profile['nome_paziente']}")

if not df.empty:
    # 1. Dashboard Metrics
    m = st.columns(4)
    def delta(c):
        v = df[c].dropna()
        return round(float(v.iloc[-1] - v.iloc[-2]), 1) if len(v) >= 2 else None

    m[0].metric("O2%", f"{df['oxygen'].iloc[-1]}%", delta('oxygen'))
    m[1].metric("BPM", df['bpm'].iloc[-1], delta('bpm'), delta_color="inverse")
    m[2].metric("Pressione", f"{df['systolic'].iloc[-1]}/{df['diastolic'].iloc[-1]}", delta('systolic'), delta_color="inverse")
    m[3].metric("Peso", f"{df['weight'].iloc[-1]}kg", delta('weight'))

    # 2. Tabs
    tabs = st.tabs(["📈 Trend", "🧬 Statistiche", "🤖 IA", "📅 Visite", "📂 Referti", "👤 Profilo", "📋 Registro"])
    
    with tabs[0]: st.plotly_chart(px.line(df, x='created_at', y=['oxygen', 'bpm', 'systolic', 'diastolic', 'weight', 'temperature'], markers=True))
    
    with tabs[1]: # Pearson
        st.plotly_chart(px.imshow(df[['oxygen', 'bpm', 'systolic', 'diastolic', 'weight', 'temperature']].corr(), text_auto=".2f"))
        
    with tabs[2]: # AI
        if st.button("🚀 Genera Analisi"):
            st.session_state.ai_text = get_ai_analysis(df, profile)
        if "ai_text" in st.session_state: st.info(st.session_state.ai_text)

    with tabs[5]: # Profilo
        with st.form("p"):
            n = st.text_input("Nome", profile['nome_paziente'])
            q = st.text_area("Quadro", profile['quadro_clinico'])
            t = st.text_area("Terapia", profile['terapia_attuale'])
            if st.form_submit_button("Salva"):
                supabase.table("user_profile").update({"nome_paziente":n, "quadro_clinico":q, "terapia_attuale":t}).eq("id", 1).execute()
                st.rerun()

    with tabs[6]: # Registro & PDF
        # Generazione PDF sicura
        report_text = st.session_state.get("ai_text", "Analisi non generata in questa sessione.")
        # [Qui inseriresti la funzione export_pdf già definita sopra con clean_text_for_pdf]
        st.dataframe(df.sort_values('created_at', ascending=False))
