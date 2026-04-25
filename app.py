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
    if df.empty or len(df) < 2: return "Dati insufficienti."
    recent = df.sort_values(by='created_at', ascending=False).head(10)
    summary = recent.to_string(columns=['created_at', 'oxygen', 'bpm', 'systolic', 'diastolic', 'notes', 'temperature'])
    prompt = f"Paziente: Alessio Casini. Post-Embolia Polmonare Estesa. Analizza questi parametri: {summary}"
    try:
        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Sei un cardiologo esperto."}, {"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e: return f"Errore: {e}"

# FUNZIONE AGGIORNATA: Analisi basata sul TESTO del referto
def analyze_report_text(doc_name, doc_content):
    if not client_ai: return "AI non configurata."
    if not doc_content or len(doc_content) < 5:
        return "⚠️ Per favore, inserisci i dati principali o il testo del referto nel campo 'Note' per permettermi di analizzarlo."
    
    prompt = f"""
    REFERTO: {doc_name}
    CONTENUTO/VALORI: {doc_content}
    
    CONTESTO PAZIENTE: Alessio Casini, monitoraggio post-embolia polmonare estesa (ventricolo destro affaticato).
    COMPITO: Spiega il significato di questi risultati nel contesto clinico del paziente. Sii sintetico e professionale.
    """
    try:
        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Sei un medico specialista che aiuta il paziente a capire i propri esami."},
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content
    except Exception as e: return f"Errore: {e}"

def export_pdf(df, ai_comment):
    pdf = FPDF()
    pdf.add_page(); pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, clean_text("Report Clinico - Sanity Diary"), ln=True, align="C")
    pdf.ln(5)
    pdf.set_fill_color(245, 245, 245); pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, " Analisi IA", ln=True, fill=True)
    pdf.set_font("Arial", "", 10); pdf.multi_cell(0, 7, clean_text(ai_comment))
    pdf.ln(5); return bytes(pdf.output())

# --- 5. LOGICA APPLICATIVA ---
if supabase:
    res = supabase.table("health_logs").select("*").order("created_at").execute()
    df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
    if not df.empty:
        df['created_at'] = pd.to_datetime(df['created_at'], format='ISO8601', errors='coerce').dt.tz_localize(None)

    st.title("🩺 Sanity Diary Intelligence")

    # Banner Visite
    try:
        res_v = supabase.table("visite_mediche").select("*").eq("completata", False).order("data_visita").execute()
        if res_v.data:
            v = res_v.data[0]
            st.warning(f"📅 **Prossima Visita:** {v['nome_visita']} il {v['data_visita']}")
    except: pass

    if not df.empty:
        tabs = st.tabs(["📈 Trend", "🧬 Pearson", "🤖 Assistente IA", "📅 Visite", "📂 Referti", "📋 Registro"])

        with tabs[2]:
            st.subheader("🤖 Analisi Generale Trend")
            if st.button("Analizza Parametri Vitali"):
                st.session_state.ai_text = get_ai_narrative_analysis(df)
            if "ai_text" in st.session_state: st.info(st.session_state.ai_text)

        with tabs[4]:
            st.subheader("📂 Archivio & Analisi Referti")
            
            with st.expander("➕ Carica ed Esponi Risultati"):
                up = st.file_uploader("Allega PDF", type="pdf")
                content_txt = st.text_area("Copia qui il testo del referto o i valori chiave (es. D-Dimero 250, Troponina ok...)", height=150)
                if st.button("Salva nel Diario") and up:
                    b64 = base64.b64encode(up.read()).decode('utf-8')
                    supabase.table("referti_medici").insert({
                        "nome_referto": up.name, 
                        "data_esame": str(datetime.now().date()), 
                        "file_path": b64,
                        "note": content_txt # Salviamo il testo per l'IA
                    }).execute()
                    st.success("Referto salvato!"); st.rerun()

            # Elenco Referti
            res_r = supabase.table("referti_medici").select("*").order("data_esame", desc=True).execute()
            for r in (res_r.data or []):
                with st.expander(f"📄 {r['data_esame']} - {r['nome_referto']}"):
                    c1, c2 = st.columns(2)
                    with c1:
                        st.download_button("💾 Scarica", base64.b64decode(r['file_path']), file_name=r['nome_referto'], key=f"r_{r['id']}")
                        pdf_view = f'<iframe src="data:application/pdf;base64,{r["file_path"]}" width="100%" height="300" type="application/pdf"></iframe>'
                        st.markdown(pdf_view, unsafe_allow_html=True)
                    with c2:
                        st.write("**🤖 Chiedi all'IA di questo esame:**")
                        if st.button(f"Analizza Dati Esame", key=f"ai_btn_{r['id']}"):
                            # Passiamo all'IA il testo salvato nel campo note
                            st.session_state[f"res_{r['id']}"] = analyze_report_text(r['nome_referto'], r.get('note', ''))
                        
                        if f"res_{r['id']}" in st.session_state:
                            st.markdown(st.session_state[f"res_{r['id']}"])

        with tabs[5]:
            # Registro (Invariato per evitare regressioni)
            st.subheader("Registro Storico")
            pdf_report = export_pdf(df, st.session_state.get("ai_text", "Nessuna analisi generale."))
            st.download_button("Scarica Report PDF", pdf_report, "report.pdf", "application/pdf")
            st.dataframe(df.sort_values(by='created_at', ascending=False), use_container_width=True)

    # Sidebar per inserimento dati
    with st.sidebar:
        st.header("⚙️ Nuova Misura")
        with st.form("h", clear_on_submit=True):
            o, b, s, d, w, t = st.number_input("O2%", 0), st.number_input("BPM", 0), st.number_input("Sist.", 0), st.number_input("Diast.", 0), st.number_input("Peso", 0.0), st.number_input("Temp", 0.0)
            n = st.text_area("Note")
            if st.form_submit_button("Salva"):
                supabase.table("health_logs").insert({"oxygen":o, "bpm":b, "systolic":s, "diastolic":d, "weight":w, "temperature":t, "notes":n}).execute()
                st.rerun()
