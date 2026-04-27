import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
from datetime import datetime
import base64
from fpdf import FPDF
import streamlit.components.v1 as components
from openai import OpenAI

# --- 1. CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Sanity Diary AI", page_icon="🧬", layout="wide")

def inject_pwa():
    pwa_html = """<link rel="manifest" href="./manifest.json"><script>if('serviceWorker' in navigator){navigator.serviceWorker.register('./sw.js');}</script>"""
    components.html(pwa_html, height=0)

inject_pwa()

# --- 2. AUTHENTICATION ---
if "authenticated" not in st.session_state: st.session_state.authenticated = False
if not st.session_state.authenticated:
    st.title("🔐 Accesso Riservato")
    with st.form("login"):
        password = st.text_input("Password:", type="password")
        if st.form_submit_button("Accedi"):
            if password == st.secrets.get("APP_PASSWORD"):
                st.session_state.authenticated = True
                st.rerun()
            else: st.error("Password errata")
    st.stop()

# --- 3. CONNESSIONE ---
@st.cache_resource
def init_db():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

supabase = init_db()
client_ai = OpenAI(api_key=st.secrets.get("OPENAI_API_KEY"))

# --- 4. FUNZIONI CORE ---
def clean_text(text):
    if not text: return ""
    return text.encode('latin-1', 'replace').decode('latin-1').replace('?', ' ')

def get_ai_analysis(df, profile, context="", is_report=False):
    recent = df.sort_values(by='created_at', ascending=False).head(15)
    data_summary = recent.to_string(columns=['created_at', 'oxygen', 'bpm', 'systolic', 'diastolic', 'weight', 'temperature', 'notes'])
    
    sys_prompt = f"""Sei un medico specialista. Analizza i dati di {profile['nome_paziente']}.
    QUADRO CLINICO: {profile['quadro_clinico']}
    TERAPIA: {profile['terapia_attuale']}
    SOGLIA O2 MIN: {profile['soglia_ossigeno_min']}%
    Fornisci un'analisi clinica basata su questi parametri e sui dati recenti."""

    prompt = f"DATI RECENTI:\n{data_summary}\n\nCONTESTO AGGIUNTIVO: {context}"
    
    try:
        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e: return f"Errore AI: {e}"

def export_pdf(df, profile, ai_comment):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, clean_text(f"REPORT CLINICO: {profile['nome_paziente']}"), ln=True, align="C")
    
    # Sezione Profilo nel PDF
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(0, 8, " INFORMAZIONI PAZIENTE", ln=True, fill=True)
    pdf.set_font("Arial", "", 9)
    pdf.multi_cell(0, 5, clean_text(f"Quadro: {profile['quadro_clinico']}\nTerapia: {profile['terapia_attuale']}"))
    pdf.ln(5)

    # Tabella Dati
    pdf.set_fill_color(230, 240, 255)
    pdf.set_font("Arial", "B", 8)
    cols = [("Data Ora", 35), ("O2", 12), ("BPM", 12), ("T C", 12), ("Press", 20), ("Peso", 15)]
    for h, w in cols: pdf.cell(w, 8, h, 1, 0, "C", True)
    pdf.ln()
    pdf.set_font("Arial", "", 8)
    for _, r in df.sort_values(by='created_at', ascending=False).head(30).iterrows():
        pdf.cell(35, 7, r['created_at'].strftime('%d/%m/%y %H:%M'), 1)
        pdf.cell(12, 7, f"{r.get('oxygen','-')}%", 1, 0, "C")
        pdf.cell(12, 7, str(r.get('bpm','-')), 1, 0, "C")
        pdf.cell(12, 7, str(r.get('temperature','-')), 1, 0, "C")
        pdf.cell(20, 7, f"{r.get('systolic','-')}/{r.get('diastolic','-')}", 1, 0, "C")
        pdf.cell(15, 7, str(r.get('weight','-')), 1, 0, "C")
        pdf.ln()

    # Note Separate
    pdf.add_page()
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "DIARIO NOTE", ln=True)
    pdf.set_font("Arial", "", 10)
    for _, r in df.sort_values(by='created_at', ascending=False).iterrows():
        if r['notes']:
            pdf.set_font("Arial", "B", 9)
            pdf.cell(0, 6, r['created_at'].strftime('%d/%m/%Y %H:%M'), ln=True)
            pdf.set_font("Arial", "", 10)
            pdf.multi_cell(0, 6, clean_text(str(r['notes'])))
            pdf.ln(2)

    return pdf.output(dest='S').encode('latin-1')

# --- 5. RECUPERO DATI ---
# Profilo
p_res = supabase.table("user_profile").select("*").eq("id", 1).execute()
profile = p_res.data[0] if p_res.data else {"nome_paziente": "Alessio", "quadro_clinico": "", "terapia_attuale": "", "soglia_ossigeno_min": 94}

# Health Logs
res = supabase.table("health_logs").select("*").order("created_at").execute()
df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
if not df.empty:
    df['created_at'] = pd.to_datetime(df['created_at'], format='mixed', errors='coerce').dt.tz_localize(None)
    df = df.dropna(subset=['created_at']).sort_values('created_at')

# --- 6. INTERFACCIA ---
st.title(f"🧬 Sanity Diary: {profile['nome_paziente']}")

# Banner Visite
try:
    v_res = supabase.table("visite_mediche").select("*").eq("completata", False).order("data_visita").execute()
    if v_res.data:
        vn = v_res.data[0]
        st.warning(f"📅 **Prossima Visita:** {vn['nome_visita']} il {vn['data_visita']}")
except: pass

tabs = st.tabs(["📈 Dashboard", "👤 Profilo", "📅 Visite", "📂 Referti", "📋 Registro"])

with tabs[0]: # Dashboard
    if not df.empty:
        m = st.columns(4)
        m[0].metric("O2%", f"{df['oxygen'].iloc[-1]}%")
        m[1].metric("BPM", df['bpm'].iloc[-1])
        m[2].metric("Pressione", f"{df['systolic'].iloc[-1]}/{df['diastolic'].iloc[-1]}")
        m[3].metric("Peso", f"{df['weight'].iloc[-1]}kg")
        st.plotly_chart(px.line(df, x='created_at', y=['oxygen', 'bpm', 'systolic', 'diastolic', 'weight', 'temperature'], markers=True), use_container_width=True)
        
        if st.button("✨ Genera Analisi IA Personalizzata"):
            with st.spinner("L'IA sta studiando il tuo profilo clinico..."):
                st.session_state.ai_text = get_ai_analysis(df, profile)
        if "ai_text" in st.session_state:
            st.info(st.session_state.ai_text)

with tabs[1]: # Profilo
    st.subheader("👤 Profilo Clinico Personalizzato")
    with st.form("edit_profile"):
        c1, c2 = st.columns(2)
        nome = c1.text_input("Nome", profile['nome_paziente'])
        soglia = c2.number_input("Soglia Minima O2 Allarme", 80, 100, profile['soglia_ossigeno_min'])
        quadro = st.text_area("Quadro Clinico (Patologie, interventi recenti)", profile['quadro_clinico'])
        terapia = st.text_area("Terapia Farmacologica Attuale", profile['terapia_attuale'])
        if st.form_submit_button("Aggiorna Profilo"):
            supabase.table("user_profile").update({
                "nome_paziente": nome, "quadro_clinico": quadro, 
                "terapia_attuale": terapia, "soglia_ossigeno_min": soglia
            }).eq("id", 1).execute()
            st.success("Profilo aggiornato!")
            st.rerun()

with tabs[2]: # Visite
    v1, v2 = st.columns([1, 2])
    with v1:
        with st.form("av"):
            nv, dv = st.text_input("Visita"), st.date_input("Data")
            if st.form_submit_button("Aggiungi"):
                supabase.table("visite_mediche").insert({"nome_visita":nv, "data_visita":str(dv), "completata":False}).execute()
                st.rerun()
    with v2:
        vd = supabase.table("visite_mediche").select("*").order("data_visita").execute().data
        for v in (vd or []):
            st.write(f"{'✅' if v['completata'] else '⏳'} {v['data_visita']}: {v['nome_visita']}")

with tabs[4]: # Registro
    if not df.empty:
        pdf_rep = export_pdf(df, profile, st.session_state.get("ai_text", "Nessuna analisi generata."))
        st.download_button("📥 Scarica Report Clinico PDF", pdf_rep, "report.pdf", "application/pdf")
        st.dataframe(df.sort_values('created_at', ascending=False))

# Sidebar Misura
with st.sidebar:
    st.header("⚙️ Nuova Misura")
    with st.form("h", clear_on_submit=True):
        o, b = st.number_input("O2%", 0, 100, 98), st.number_input("BPM", 0, 200, 70)
        s, d = st.number_input("Sistolica", 0, 200, 120), st.number_input("Diastolica", 0, 150, 80)
        w, t = st.number_input("Peso", 0.0, 200.0, 80.0), st.number_input("Temp", 30.0, 45.0, 36.5)
        n = st.text_area("Note")
        if st.form_submit_button("Salva"):
            supabase.table("health_logs").insert({"oxygen":o, "bpm":b, "systolic":s, "diastolic":d, "weight":w, "temperature":t, "notes":n}).execute()
            st.rerun()
