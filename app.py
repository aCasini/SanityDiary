import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
from datetime import datetime
import base64
from fpdf import FPDF
import streamlit.components.v1 as components
from openai import OpenAI  # Importiamo il client per l'IA

# --- 1. CONFIGURAZIONE PAGINA & PWA ---
st.set_page_config(page_title="Sanity Diary AI", page_icon="🩺", layout="wide")

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
client_ai = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

# --- 4. FUNZIONI IA AVANZATE ---
def get_ai_narrative_analysis(df):
    """Utilizza GPT-4 per analizzare i trend e le note."""
    if df.empty or len(df) < 3:
        return "Dati insufficienti per un'analisi testuale approfondita."
    
    # Prepariamo un riassunto testuale degli ultimi dati per l'IA
    recent_data = df.sort_values(by='created_at', ascending=False).head(7)
    summary_text = recent_data.to_string(columns=['created_at', 'oxygen', 'bpm', 'systolic', 'diastolic', 'notes'])
    
    prompt = f"""
    Agisci come un assistente medico esperto in monitoraggio domiciliare. 
    Analizza i seguenti dati di un paziente dell'ultima settimana:
    {summary_text}
    
    Identifica:
    1. Anomalie significative o trend preoccupanti.
    2. Correlazioni tra le note (es. sintomi riportati) e i valori numerici.
    3. Un breve suggerimento per il medico che leggerà questo report.
    
    Mantieni un tono professionale, conciso e diretto. Non fornire diagnosi definitive, usa un linguaggio cautelativo.
    """
    
    try:
        response = client_ai.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "system", "content": "Sei un assistente clinico digitale."},
                      {"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Analisi IA momentaneamente non disponibile: {str(e)}"

def export_pdf(df, ai_comment):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 18)
    pdf.cell(0, 10, "Sanity Diary - Report Clinico con Assistente IA", ln=True, align="C")
    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 10, f"Generato il: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align="C")
    pdf.ln(5)

    # SEZIONE IA NARRATIVA (Novità)
    pdf.set_fill_color(245, 245, 245)
    pdf.set_font("Arial", "B", 13)
    pdf.cell(0, 10, " Commento Clinico dell'Assistente IA", ln=True, fill=True)
    pdf.set_font("Arial", "", 10)
    pdf.multi_cell(0, 7, ai_comment)
    pdf.ln(5)

    # Tabella Dati (Layout Professionale)
    pdf.set_fill_color(230, 242, 255)
    pdf.set_font("Arial", "B", 10)
    headers = [("Data", 30), ("O2%", 15), ("BPM", 15), ("Temp", 15), ("Press", 30), ("Peso", 20), ("Note", 65)]
    for h, w in headers: pdf.cell(w, 10, h, 1, 0, "C", True)
    pdf.ln()
    pdf.set_font("Arial", "", 9)
    for _, row in df.sort_values(by='created_at', ascending=False).head(30).iterrows():
        pdf.cell(30, 8, row['created_at'].strftime('%d/%m/%y'), 1)
        pdf.cell(15, 8, str(row['oxygen']) if pd.notnull(row['oxygen']) else "-", 1, 0, "C")
        pdf.cell(15, 8, str(row['bpm']) if pd.notnull(row['bpm']) else "-", 1, 0, "C")
        pdf.cell(15, 8, str(row['temperature']) if pd.notnull(row['temperature']) else "-", 1, 0, "C")
        p_s = f"{int(row['systolic'])}/{int(row['diastolic'])}" if pd.notnull(row['systolic']) else "-"
        pdf.cell(30, 8, p_s, 1, 0, "C")
        pdf.cell(20, 8, f"{row['weight']:.1f}" if pd.notnull(row['weight']) else "-", 1, 0, "C")
        pdf.cell(65, 8, str(row['notes'])[:40] if pd.notnull(row['notes']) else "-", 1)
        pdf.ln()
    return bytes(pdf.output())

# --- 5. INTERFACCIA APP ---
if supabase:
    res = supabase.table("health_logs").select("*").order("created_at", desc=False).execute()
    df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
    if not df.empty:
        df['created_at'] = pd.to_datetime(df['created_at'], format='ISO8601', utc=True).dt.tz_localize(None).dt.floor('s')

    st.title("🩺 Sanity Diary Intelligence")

    if not df.empty:
        # Metriche con Delta
        m = st.columns(4)
        m[0].metric("Ossigeno", f"{df['oxygen'].iloc[-1]:.0f}%")
        m[1].metric("BPM", f"{df['bpm'].iloc[-1]:.0f}", delta_color="inverse")
        m[2].metric("Pressione Max", f"{df['systolic'].iloc[-1]:.0f}", delta_color="inverse")
        m[3].metric("Peso", f"{df['weight'].iloc[-1]:.1f}kg")

        st.divider()
        t_ia, t_visite, t_ref, t_reg = st.tabs(["🤖 Analisi Assistente IA", "📅 Visite", "📂 Referti", "📋 Registro & Report"])

        with t_ia:
            st.subheader("Commento Narrativo dell'IA")
            if st.button("Genera Nuova Analisi IA"):
                with st.spinner("L'IA sta leggendo i tuoi dati..."):
                    st.session_state.ai_analysis = get_ai_narrative_analysis(df)
            
            if "ai_analysis" in st.session_state:
                st.info(st.session_state.ai_analysis)
                st.caption("Nota: Questa analisi è generata automaticamente e non sostituisce il parere del medico.")

        with t_visite:
            st.subheader("Prossime Visite")
            # Logica visite già presente... (codice precedente mantenuto)

        with t_reg:
            c_tab, c_exp = st.columns([3, 1])
            with c_exp:
                st.write("🖨️ **Export Medico**")
                ai_text = st.session_state.get("ai_analysis", "Analisi IA non generata.")
                pdf_data = export_pdf(df, ai_text)
                st.download_button("Scarica Report PDF", pdf_data, "report_clinico.pdf", "application/pdf")
            with c_tab:
                st.dataframe(df.sort_values(by='created_at', ascending=False), use_container_width=True, hide_index=True)

    with st.sidebar:
        st.header("⚙️ Nuova Misura")
        with st.form("h_form", clear_on_submit=True):
            o, b, t = st.number_input("O2%", 0), st.number_input("BPM", 0), st.number_input("Temp °C", 0.0)
            s, d, w = st.number_input("Sistolica", 0), st.number_input("Diastolica", 0), st.number_input("Peso kg", 0.0)
            n = st.text_area("Note (sintomi, stress, attività)")
            if st.form_submit_button("Salva"):
                supabase.table("health_logs").insert({"oxygen":o, "bpm":b, "temperature":t, "systolic":s, "diastolic":d, "weight":w, "notes":n}).execute()
                st.rerun()
