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
# Serve l'installazione di: pip install PyPDF2
try:
    import PyPDF2
except ImportError:
    st.error("Per favore, aggiungi 'PyPDF2' al file requirements.txt")

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
def extract_text_from_pdf(pdf_file):
    """Estrae il testo dal file PDF caricato."""
    try:
        reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for page in reader.pages:
            text += page.extract_text()
        return text
    except Exception as e:
        return f"Errore estrazione testo: {e}"

def clean_text(text):
    if not text: return ""
    return text.encode('latin-1', 'replace').decode('latin-1').replace('?', ' ')

def get_ai_narrative_analysis(df, extra_context=""):
    if not client_ai: return "AI non configurata."
    if df.empty or len(df) < 2: return "Dati insufficienti."
    
    recent = df.sort_values(by='created_at', ascending=False).head(10)
    summary = recent.to_string(columns=['created_at', 'oxygen', 'bpm', 'systolic', 'diastolic', 'notes', 'temperature'])
    
    prompt = f"""
    PAZIENTE: Alessio Casini (Post-Embolia Polmonare Estesa).
    PARAMETRI VITALI: {summary}
    DOCUMENTO ALLEGATO ESTRATTO: {extra_context}
    
    Analizza i parametri e il contenuto del documento fornendo un commento clinico strutturato.
    """
    try:
        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Sei un medico specialista."}, {"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e: return f"Errore: {e}"

# (Le altre funzioni export_pdf rimangono invariate rispetto al tuo file originale)
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

    st.title("🩺 Sanity Diary Intelligence")

    if not df.empty:
        tabs = st.tabs(["📈 Trend", "🧬 Pearson", "🤖 Assistente IA", "📅 Visite", "📂 Referti", "📋 Registro"])

        with tabs[2]:
            st.subheader("🤖 Analisi Specialistica con Allegato")
            
            # Sezione Caricamento Documento per Analisi
            uploaded_file = st.file_uploader("Allega un referto per l'analisi IA (PDF)", type="pdf", key="ai_upload")
            
            if st.button("Esegui Analisi Completa"):
                extra_text = ""
                if uploaded_file:
                    with st.spinner("Lettura documento in corso..."):
                        extra_text = extract_text_from_pdf(uploaded_file)
                
                with st.spinner("L'IA sta elaborando i dati vitali e il documento..."):
                    st.session_state.ai_text = get_ai_narrative_analysis(df, extra_text)
            
            if "ai_text" in st.session_state:
                st.markdown(st.session_state.ai_text)

        # Tab 4 Referti: invariato per mantenere l'archivio storico
        with tabs[4]:
            st.subheader("Archivio Documenti")
            up = st.file_uploader("Carica Referto PDF", type="pdf", key="archive_upload")
            if st.button("Salva PDF in Archivio") and up:
                b64 = base64.b64encode(up.read()).decode('utf-8')
                supabase.table("referti_medici").insert({"nome_referto":up.name, "data_esame":str(datetime.now().date()), "file_path":b64}).execute()
                st.success("Referto archiviato!"); st.rerun()
            for r in (supabase.table("referti_medici").select("*").execute().data or []):
                st.download_button(f"📄 {r['nome_referto']}", base64.b64decode(r['file_path']), file_name=r['nome_referto'], key=f"r_{r['id']}")

        # (Tutte le altre sezioni e la Sidebar rimangono come nel tuo file originale)
