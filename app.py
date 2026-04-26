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

# Tenta l'import di pdfplumber per l'OCR dei referti
try:
    import pdfplumber
except ImportError:
    st.error("Per l'analisi automatica dei referti, aggiungi 'pdfplumber' al file requirements.txt")

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

# --- 4. FUNZIONI DI SUPPORTO (IA, PDF, OCR) ---
def clean_text(text):
    """Evita crash FPDF rimuovendo caratteri non latin-1."""
    if not text: return ""
    return text.encode('latin-1', 'replace').decode('latin-1').replace('?', ' ')

def extract_text_from_pdf(pdf_file):
    """Legge il testo dai PDF per l'analisi automatica."""
    try:
        with pdfplumber.open(pdf_file) as pdf:
            return "\n".join([page.extract_text() for page in pdf.pages if page.extract_text()])
    except Exception as e:
        return f"Errore OCR: {e}"

def get_ai_analysis(df, context="", is_report=False):
    if not client_ai: return "Chiave API non configurata."
    
    if is_report:
        prompt = f"Analizza questo referto per un paziente post-embolia (Alessio Casini):\n{context}"
    else:
        recent = df.sort_values(by='created_at', ascending=False).head(10)
        summary = recent.to_string(columns=['created_at', 'oxygen', 'bpm', 'systolic', 'diastolic', 'notes'])
        prompt = f"Paziente: Alessio Casini (Post-Embolia). Dati vitali:\n{summary}\nContesto extra: {context}"

    try:
        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Sei un medico specialista esperto."}, 
                      {"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Errore API: {e}"

def export_pdf(df, ai_comment):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, clean_text("Report Clinico - Monitoraggio Salute"), ln=True, align="C")
    pdf.ln(5)
    pdf.set_fill_color(245, 245, 245)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, " Analisi Assistente IA", ln=True, fill=True)
    pdf.set_font("Arial", "", 10)
    pdf.multi_cell(0, 7, clean_text(ai_comment))
    pdf.ln(10)
    
    # Tabella
    pdf.set_fill_color(230, 240, 255)
    pdf.set_font("Arial", "B", 8)
    cols = [("Data", 30), ("O2", 12), ("BPM", 12), ("Press", 20), ("Peso", 15), ("Note", 90)]
    for h, w in cols: pdf.cell(w, 8, h, 1, 0, "C", True)
    pdf.ln()
    
    pdf.set_font("Arial", "", 8)
    if not df.empty:
        for _, r in df.sort_values(by='created_at', ascending=False).head(40).iterrows():
            pdf.cell(30, 7, r['created_at'].strftime('%d/%m/%y %H:%M'), 1)
            pdf.cell(12, 7, str(r.get('oxygen','-')), 1, 0, "C")
            pdf.cell(12, 7, str(r.get('bpm','-')), 1, 0, "C")
            pdf.cell(20, 7, f"{r.get('systolic','-')}/{r.get('diastolic','-')}", 1, 0, "C")
            pdf.cell(15, 7, str(r.get('weight','-')), 1, 0, "C")
            pdf.cell(90, 7, clean_text(str(r.get('notes',''))[:55]), 1)
            pdf.ln()
    return pdf.output(dest='S').encode('latin-1')

# --- 5. LOGICA UI ---
with st.sidebar:
    st.header("⚙️ Nuova Misura")
    with st.form("h", clear_on_submit=True):
        o, b = st.number_input("O2%", 0, 100, 98), st.number_input("BPM", 0, 200, 70)
        s, d = st.number_input("Sist.", 0, 200, 120), st.number_input("Diast.", 0, 150, 80)
        w, t = st.number_input("Peso", 0.0, 200.0, 75.0), st.number_input("Temp", 30.0, 45.0, 36.5)
        n = st.text_area("Note")
        if st.form_submit_button("Salva"):
            supabase.table("health_logs").insert({"oxygen":o, "bpm":b, "systolic":s, "diastolic":d, "weight":w, "temperature":t, "notes":n}).execute()
            st.rerun()
    if st.button("Logout"):
        st.session_state.authenticated = False
        st.rerun()

# Recupero Dati
res = supabase.table("health_logs").select("*").order("created_at").execute()
df = pd.DataFrame(res.data) if res.data else pd.DataFrame()

if not df.empty:
    # --- FIX DATE: Gestione errori di conversione e fusi orari ---
    df['created_at'] = pd.to_datetime(df['created_at'], errors='coerce')
    df = df.dropna(subset=['created_at']) # Rimuove righe con date non valide
    df['created_at'] = df['created_at'].dt.tz_localize(None) # Rimuove fuso orario per compatibilità Plotly/FPDF

st.title("🩺 Sanity Diary Intelligence")

# Banner Visite
try:
    v_res = supabase.table("visite_mediche").select("*").eq("completata", False).order("data_visita").execute()
    if v_res.data:
        v = v_res.data[0]
        st.warning(f"📅 **Prossima Visita:** {v['nome_visita']} il {v['data_visita']} a {v['luogo']}")
except: pass

if not df.empty:
    tabs = st.tabs(["📈 Trend", "🧬 Pearson", "🤖 Assistente IA", "📅 Visite", "📂 Referti (OCR)", "📋 Registro"])

    with tabs[0]:
        st.plotly_chart(px.line(df.sort_values('created_at'), x='created_at', y=['oxygen', 'bpm', 'systolic', 'diastolic'], markers=True), use_container_width=True)

    with tabs[1]:
        st.subheader("🧬 Studio Correlazioni (Pearson)")
        col_desc, col_map = st.columns([1, 2])
        cols_stats = [c for c in ['oxygen', 'bpm', 'systolic', 'diastolic', 'weight', 'temperature'] if c in df.columns]
        with col_desc:
            st.markdown("### 📊 Analisi Statistica")
            st.write("La mappa a destra mostra come i tuoi parametri variano insieme.")
            if len(df) > 2:
                corr_matrix = df[cols_stats].corr()
                corr_unstacked = corr_matrix.unstack().sort_values(ascending=False)
                top = corr_unstacked[corr_unstacked < 0.99].head(1)
                if not top.empty:
                    st.info(f"**Insight:** Trovata relazione tra {top.index[0][0]} e {top.index[0][1]} ({top.values[0]:.2f})")
        with col_map:
            st.plotly_chart(px.imshow(df[cols_stats].corr(), text_auto=".2f", color_continuous_scale='RdBu_r'), use_container_width=True)

    with tabs[2]:
        st.subheader("🤖 Assistente IA")
        extra_c = st.text_area("Aggiungi contesto (es. Risultati eco addome o sintomi particolari):")
        if st.button("Genera Analisi"):
            with st.spinner("L'IA sta elaborando..."):
                st.session_state.ai_text = get_ai_analysis(df, extra_c)
        if "ai_text" in st.session_state:
            st.markdown(st.session_state.ai_text)

    with tabs[3]:
        st.subheader("Appuntamenti Medici")
        cv1, cv2 = st.columns([1, 2])
        with cv1:
            with st.form("vis"):
                nv, dv, lv = st.text_input("Visita"), st.date_input("Data"), st.text_input("Luogo")
                if st.form_submit_button("Aggiungi"):
                    supabase.table("visite_mediche").insert({"nome_visita":nv, "data_visita":str(dv), "luogo":lv, "completata":False}).execute()
                    st.rerun()
        with cv2:
            try:
                visite = supabase.table("visite_mediche").select("*").order("data_visita").execute().data
                for v in (visite or []):
                    ca, cb = st.columns([4, 1])
                    ca.write(f"{'✅' if v['completata'] else '⏳'} **{v['data_visita']}**: {v['nome_visita']}")
                    if not v['completata'] and cb.button("Fatto", key=f"v_{v['id']}"):
                        supabase.table("visite_mediche").update({"completata":True}).eq("id", v['id']).execute()
                        st.rerun()
            except: st.write("Nessuna visita salvata.")

    with tabs[4]:
        st.subheader("📂 Analisi Automatica Referti")
        file_up = st.file_uploader("Carica PDF per lettura OCR", type="pdf")
        if file_up and st.button("🚀 Leggi ed Estrai Dati"):
            with st.spinner("Lettura in corso..."):
                txt = extract_text_from_pdf(file_up)
                st.session_state.report_analysis = get_ai_analysis(df, txt, is_report=True)
                b64 = base64.b64encode(file_up.getvalue()).decode('utf-8')
                supabase.table("referti_medici").insert({"nome_referto":file_up.name, "data_esame":str(datetime.now().date()), "file_path":b64, "note":txt}).execute()
        if "report_analysis" in st.session_state:
            st.info(st.session_state.report_analysis)

    with tabs[5]:
        st.subheader("Registro Storico")
        pdf_out = export_pdf(df, st.session_state.get("ai_text", "Nessuna analisi generata."))
        st.download_button("📥 Scarica Report PDF", pdf_out, "report_clinico.pdf", "application/pdf")
        st.dataframe(df.sort_values('created_at', ascending=False), use_container_width=True)
else:
    st.info("Benvenuto Alessio! Inserisci la tua prima misurazione nel pannello laterale per iniziare.")
