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

# --- 4. FUNZIONI UTILITY (PDF & AI) ---
def clean_text(text):
    if not text: return ""
    return text.encode('latin-1', 'replace').decode('latin-1').replace('?', ' ')

def get_ai_narrative_analysis(df):
    if not client_ai: return "Chiave API non configurata."
    if df.empty or len(df) < 2: return "Dati insufficienti per l'analisi."
    recent = df.sort_values(by='created_at', ascending=False).head(10)
    summary = recent.to_string(columns=['created_at', 'oxygen', 'bpm', 'systolic', 'diastolic', 'notes', 'temperature'])
    prompt = f"Contesto: Post-Embolia Polmonare. Analizza questi dati per il medico: {summary}"
    try:
        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Sei un medico specialista."}, {"role": "user", "content": prompt}]
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

    if not df.empty:
        # Metriche
        m = st.columns(4)
        def get_delta(col):
            vals = df[col].dropna()
            return round(float(vals.iloc[-1] - vals.iloc[-2]), 1) if len(vals) >= 2 else 0
        m[0].metric("Ossigeno", f"{df['oxygen'].iloc[-1]}%", get_delta('oxygen'))
        m[1].metric("BPM", f"{df['bpm'].iloc[-1]}", get_delta('bpm'), delta_color="inverse")
        m[2].metric("Press. Max", f"{df['systolic'].iloc[-1]}", get_delta('systolic'), delta_color="inverse")
        m[3].metric("Peso", f"{df['weight'].iloc[-1]}kg", get_delta('weight'))

        st.divider()
        tabs = st.tabs(["📈 Trend", "🧬 Pearson", "🤖 Assistente IA", "📅 Visite", "📂 Referti", "📋 Registro"])

        with tabs[0]:
            all_params = ['oxygen', 'bpm', 'systolic', 'diastolic', 'weight', 'temperature']
            available_cols = [c for c in all_params if c in df.columns]
            st.plotly_chart(px.line(df.sort_values('created_at'), x='created_at', y=available_cols, markers=True, template="plotly_white"), use_container_width=True)

        with tabs[1]:
            st.subheader("🧬 Studio Correlazioni (Pearson)")
            c_desc, c_map = st.columns([1, 2])
            with c_desc:
                st.markdown("**Legenda:**\n* **1.0**: Correlazione forte positiva.\n* **-1.0**: Correlazione forte negativa.\n* **0**: Nessuna relazione.")
                if len(available_cols) > 1:
                    c_mat = df[available_cols].corr()
                    strong = c_mat.unstack().sort_values(ascending=False)
                    top = strong[strong < 0.95].head(1)
                    if not top.empty:
                        st.info(f"💡 Legame: {top.index[0][0]} e {top.index[0][1]} ({top.values[0]:.2f})")
            with c_map:
                if len(available_cols) > 1:
                    st.plotly_chart(px.imshow(df[available_cols].corr(), text_auto=".2f", color_continuous_scale='RdBu_r'), use_container_width=True)

        with tabs[2]:
            if st.button("Esegui Analisi"):
                with st.spinner("Analizzando..."):
                    st.session_state.ai_text = get_ai_narrative_analysis(df)
            if "ai_text" in st.session_state: st.info(st.session_state.ai_text)

        with tabs[4]:
            st.subheader("📂 Archivio Documenti")
            with st.expander("➕ Carica nuovo referto"):
                with st.form("form_ref", clear_on_submit=True):
                    up = st.file_uploader("PDF", type="pdf")
                    n_ref = st.text_input("Titolo")
                    if st.form_submit_button("Salva"):
                        if up:
                            b64 = base64.b64encode(up.read()).decode('utf-8')
                            supabase.table("referti_medici").insert({"nome_referto": n_ref if n_ref else up.name, "data_esame": str(datetime.now().date()), "file_path": b64}).execute()
                            st.rerun()

            res_r = supabase.table("referti_medici").select("*").order("data_esame", desc=True).execute()
            for r in (res_r.data or []):
                with st.expander(f"📄 {r['data_esame']} - {r['nome_referto']}"):
                    f_bytes = base64.b64decode(r['file_path'])
                    st.download_button("💾 Scarica PDF", f_bytes, file_name=f"{r['nome_referto']}.pdf", key=f"d_{r['id']}")
                    pdf_view = f'<iframe src="data:application/pdf;base64,{r["file_path"]}" width="100%" height="500" type="application/pdf"></iframe>'
                    st.markdown(pdf_view, unsafe_allow_html=True)

        with tabs[5]:
            st.subheader("Registro Storico")
            df_display = df.sort_values(by='created_at', ascending=False).copy()
            df_display['Data'] = df_display['created_at'].dt.strftime('%d/%m/%Y %H:%M')
            pdf_report = export_pdf(df, st.session_state.get("ai_text", "Nessuna analisi generata."))
            st.download_button("Scarica Report PDF per il Medico", pdf_report, "report_clinico.pdf", "application/pdf")
            cols_to_show = ['Data', 'oxygen', 'bpm', 'systolic', 'diastolic', 'weight', 'temperature', 'notes']
            st.dataframe(df_display[[c for c in cols_to_show if c in df_display.columns]], use_container_width=True, hide_index=True)

    with st.sidebar:
        st.header("⚙️ Nuova Misura")
        with st.form("h", clear_on_submit=True):
            o, b, s, d, w, t = st.number_input("O2%", 0), st.number_input("BPM", 0), st.number_input("Sist.", 0), st.number_input("Diast.", 0), st.number_input("Peso", 0.0), st.number_input("Temp", 0.0)
            n = st.text_area("Note")
            if st.form_submit_button("Salva"):
                supabase.table("health_logs").insert({"oxygen":o, "bpm":b, "systolic":s, "diastolic":d, "weight":w, "temperature":t, "notes":n}).execute()
                st.rerun()
        if st.button("Logout"): st.session_state.authenticated = False; st.rerun()
