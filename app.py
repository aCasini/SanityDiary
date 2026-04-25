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
    prompt_paziente = f"""
    CONTESTO CLINICO: Il paziente è in fase post-dimissione dopo un ricovero per EMBOLIA POLMONARE ESTESA.
    OBIETTIVO: Analizza i dati recenti per stabilità.
    DATI: {summary}
    """
    try:
        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Sei un medico specialista."}, {"role": "user", "content": prompt_paziente}]
        )
        return response.choices[0].message.content
    except Exception as e: return f"Errore: {e}"

def get_ai_report_analysis(report_name, report_content):
    """Analizza il contenuto testuale di un referto inserito dall'utente."""
    if not client_ai: return "AI non configurata."
    prompt = f"Referto: {report_name}\nContenuto: {report_content}\nAnalizza questo esame per un paziente post-embolia."
    try:
        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Sei un medico che spiega referti."}, {"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e: return f"Errore: {e}"

def export_pdf(df, ai_comment):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, clean_text("Report Clinico - Monitoraggio Post-Embolia"), ln=True, align="C")
    pdf.ln(5)
    pdf.set_fill_color(245, 245, 245)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, " Analisi Assistente IA", ln=True, fill=True)
    pdf.set_font("Arial", "", 10)
    pdf.multi_cell(0, 7, clean_text(ai_comment))
    pdf.ln(5)
    pdf.set_fill_color(230, 240, 255)
    pdf.set_font("Arial", "B", 9)
    cols = [("Data Ora", 35), ("O2", 15), ("BPM", 15), ("T C", 15), ("Press", 25), ("Peso", 20), ("Note", 65)]
    for h, w in cols: pdf.cell(w, 10, h, 1, 0, "C", True)
    pdf.ln()
    pdf.set_font("Arial", "", 8)
    for _, row in df.sort_values(by='created_at', ascending=False).head(50).iterrows():
        date_str = row['created_at'].strftime('%d/%m/%y %H:%M')
        pdf.cell(35, 8, date_str, 1)
        pdf.cell(15, 8, str(row.get('oxygen','-')), 1, 0, "C")
        pdf.cell(15, 8, str(row.get('bpm','-')), 1, 0, "C")
        pdf.cell(15, 8, str(row.get('temperature','-')), 1, 0, "C")
        p = f"{row.get('systolic','-')}/{row.get('diastolic','-')}"
        pdf.cell(25, 8, p, 1, 0, "C")
        pdf.cell(20, 8, str(row.get('weight','-')), 1, 0, "C")
        pdf.cell(65, 8, clean_text(str(row.get('notes','-'))[:40]), 1)
        pdf.ln()
    return bytes(pdf.output())

# --- 5. LOGICA APPLICATIVA ---
if supabase:
    res = supabase.table("health_logs").select("*").order("created_at").execute()
    df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
    if not df.empty:
        df['created_at'] = pd.to_datetime(df['created_at'], format='ISO8601', errors='coerce').dt.tz_localize(None)
        df = df.dropna(subset=['created_at'])

    st.title("🩺 Sanity Diary Intelligence")

    # Banner Visite (Dal tuo file originale)
    try:
        res_v = supabase.table("visite_mediche").select("*").eq("completata", False).order("data_visita").execute()
        if res_v.data:
            v = res_v.data[0]
            st.warning(f"📅 **Prossima Visita:** {v['nome_visita']} il {v['data_visita']} ({v['luogo']})")
    except: pass

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
            st.subheader("🧬 Studio Correlazioni (Pearson)")
            if not df.empty:
                st.plotly_chart(px.imshow(df[[c for c in all_params if c in df.columns]].corr(), text_auto=".2f",
