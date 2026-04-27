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

# Import per OCR
try:
    import pdfplumber
except ImportError:
    st.error("Aggiungi 'pdfplumber' al file requirements.txt")

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

# --- 4. FUNZIONI CORE ---
def clean_text(text):
    if not text: return ""
    return text.encode('latin-1', 'replace').decode('latin-1').replace('?', ' ')

def extract_text_from_pdf(pdf_file):
    try:
        with pdfplumber.open(pdf_file) as pdf:
            return "\n".join([page.extract_text() for page in pdf.pages if page.extract_text()])
    except Exception as e:
        return f"Errore lettura PDF: {e}"

def get_ai_analysis(df, context="", is_report=False):
    if not client_ai: return "AI non configurata."
    if is_report:
        prompt = f"Analizza questo referto per Alessio Casini (post-embolia):\n{context}"
    else:
        recent = df.sort_values(by='created_at', ascending=False).head(10)
        summary = recent.to_string(columns=['created_at', 'oxygen', 'bpm', 'systolic', 'diastolic', 'weight', 'temperature', 'notes'])
        prompt = f"Paziente: Alessio Casini (Post-Embolia). Analisi dati:\n{summary}\nContesto extra: {context}"
    try:
        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Sei un medico specialista."}, {"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e: return f"Errore AI: {e}"

def export_pdf(df, ai_comment):
    pdf = FPDF()
    pdf.add_page()
    
    # Intestazione
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, clean_text("REPORT CLINICO - SANITY DIARY"), ln=True, align="C")
    pdf.set_font("Arial", "I", 10)
    pdf.cell(0, 10, f"Generato il: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align="C")
    pdf.ln(5)
    
    # 1. ANALISI IA
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, " 1. Analisi Specialistica (AI)", ln=True, fill=True)
    pdf.set_font("Arial", "", 10)
    pdf.multi_cell(0, 7, clean_text(ai_comment))
    pdf.ln(10)
    
    # 2. TABELLA DATI (COMPATTA)
    pdf.set_fill_color(230, 240, 255)
    pdf.set_font("Arial", "B", 11)
    pdf.cell(0, 10, " 2. Riepilogo Parametri Vitali", ln=True, fill=True)
    pdf.ln(2)
    
    pdf.set_font("Arial", "B", 9)
    w = [35, 20, 20, 20, 30, 25] 
    headers = ["Data Ora", "O2%", "BPM", "Temp", "Pressione", "Peso"]
    for i, h in enumerate(headers):
        pdf.cell(w[i], 8, h, 1, 0, "C", True)
    pdf.ln()
    
    pdf.set_font("Arial", "", 9)
    df_sorted = df.sort_values(by='created_at', ascending=False)
    for _, r in df_sorted.iterrows():
        pdf.cell(w[0], 7, r['created_at'].strftime('%d/%m/%y %H:%M'), 1, 0, "C")
        pdf.cell(w[1], 7, f"{r.get('oxygen','-')}%", 1, 0, "C")
        pdf.cell(w[2], 7, str(r.get('bpm','-')), 1, 0, "C")
        pdf.cell(w[3], 7, f"{r.get('temperature','-')}C", 1, 0, "C")
        pdf.cell(w[4], 7, f"{r.get('systolic','-')}/{r.get('diastolic','-')}", 1, 0, "C")
        pdf.cell(w[5], 7, f"{r.get('weight','-')}kg", 1, 0, "C")
        pdf.ln()

    # 3. SEZIONE NOTE SEPARATA
    pdf.add_page()
    pdf.set_fill_color(230, 255, 230)
    pdf.set_font("Arial", "B", 11)
    pdf.cell(0, 10, " 3. Diario delle Note e Osservazioni", ln=True, fill=True)
    pdf.ln(4)

    for _, r in df_sorted.iterrows():
        nota = r.get('notes', '')
        if nota and str(nota).strip() != "" and str(nota).lower() != "nan":
            pdf.set_font("Arial", "B", 9)
            pdf.set_text_color(50, 50, 50)
            pdf.cell(0, 6, f"Data: {r['created_at'].strftime('%d/%m/%Y %H:%M')}", ln=True)
            pdf.set_font("Arial", "", 10)
            pdf.set_text_color(0, 0, 0)
            pdf.multi_cell(0, 6, clean_text(str(nota)))
            pdf.ln(2)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(3)
            
    return pdf.output(dest='S').encode('latin-1')

# --- 5. LOGICA APPLICATIVA ---
with st.sidebar:
    st.header("⚙️ Nuova Misura")
    with st.form("h", clear_on_submit=True):
        o, b = st.number_input("O2%", 0, 100, 98), st.number_input("BPM", 0, 200, 70)
        s, d = st.number_input("Sistolica", 0, 200, 120), st.number_input("Diastolica", 0, 150, 80)
        w, t = st.number_input("Peso", 0.0, 200.0, 80.0), st.number_input("Temp", 30.0, 45.0, 36.5)
        n = st.text_area("Note")
        if st.form_submit_button("Salva Misura"):
            supabase.table("health_logs").insert({"oxygen":o, "bpm":b, "systolic":s, "diastolic":d, "weight":w, "temperature":t, "notes":n}).execute()
            st.rerun()

res = supabase.table("health_logs").select("*").order("created_at").execute()
df = pd.DataFrame(res.data) if res.data else pd.DataFrame()

if not df.empty:
    # FIX DATE UNIVERSALE
    df['created_at'] = pd.to_datetime(df['created_at'], format='mixed', errors='coerce').dt.tz_localize(None)
    df = df.dropna(subset=['created_at']).sort_values('created_at')

st.title("🩺 Sanity Diary Intelligence")

# Banner Visite
try:
    v_res = supabase.table("visite_mediche").select("*").eq("completata", False).order("data_visita").execute()
    if v_res.data:
        vn = v_res.data[0]
        st.warning(f"📅 **Prossima Visita:** {vn['nome_visita']} il {vn['data_visita']} a {vn['luogo']}")
except: pass

if not df.empty:
    # DASHBOARD
    m = st.columns(4)
    def get_d(c):
        v = df[c].dropna()
        return round(float(v.iloc[-1] - v.iloc[-2]), 1) if len(v) >= 2 else None
    m[0].metric("Ossigeno", f"{df['oxygen'].iloc[-1]}%", get_d('oxygen'))
    m[1].metric("BPM", f"{df['bpm'].iloc[-1]}", get_d('bpm'), delta_color="inverse")
    m[2].metric("Press. Max", f"{df['systolic'].iloc[-1]}", get_d('systolic'), delta_color="inverse")
    m[3].metric("Peso", f"{df['weight'].iloc[-1]} kg", get_d('weight'))

    st.divider()
    tabs = st.tabs(["📈 Trend", "🧬 Pearson", "🤖 Assistente IA", "📅 Visite", "📂 Referti (OCR)", "📋 Registro"])

    with tabs[0]:
        st.plotly_chart(px.line(df, x='created_at', y=['oxygen', 'bpm', 'systolic', 'diastolic', 'weight', 'temperature'], markers=True, template="plotly_white"), use_container_width=True)

    with tabs[1]:
        st.subheader("🧬 Studio Correlazioni")
        cd, cm = st.columns([1, 2])
        sc = ['oxygen', 'bpm', 'systolic', 'diastolic', 'weight', 'temperature']
        with cd:
            st.markdown("### 📊 Analisi Statistica")
            if len(df) > 2:
                corr = df[sc].corr().unstack().sort_values(ascending=False)
                top = corr[corr < 0.99].head(1)
                if not top.empty:
                    st.info(f"**Insight:** Relazione tra {top.index[0][0]} e {top.index[0][1]} ({top.values[0]:.2f})")
        with cm:
            st.plotly_chart(px.imshow(df[sc].corr(), text_auto=".2f", color_continuous_scale='RdBu_r'), use_container_width=True)

    with tabs[2]:
        st.subheader("🤖 Assistente IA")
        exc = st.text_area("Aggiungi contesto:")
        if st.button("Analizza"):
            st.session_state.ai_text = get_ai_analysis(df, exc)
        if "ai_text" in st.session_state: st.markdown(st.session_state.ai_text)

    with tabs[3]:
        st.subheader("📅 Visite")
        v1, v2 = st.columns([1, 2])
        with v1:
            with st.form("av"):
                nv, dv, lv = st.text_input("Visita"), st.date_input("Data"), st.text_input("Luogo")
                if st.form_submit_button("Aggiungi"):
                    supabase.table("visite_mediche").insert({"nome_visita":nv, "data_visita":str(dv), "luogo":lv, "completata":False}).execute()
                    st.rerun()
        with v2:
            vd = supabase.table("visite_mediche").select("*").order("data_visita").execute().data
            for v in (vd or []):
                ca, cb = st.columns([4, 1])
                ca.write(f"{'✅' if v['completata'] else '⏳'} **{v['data_visita']}**: {v['nome_visita']}")
                if not v['completata'] and cb.button("Fatto", key=f"v_{v['id']}"):
                    supabase.table("visite_mediche").update({"completata":True}).eq("id", v['id']).execute()
                    st.rerun()

    with tabs[4]:
        st.subheader("📂 Referti & OCR")
        fup = st.file_uploader("Carica PDF", type="pdf")
        if fup and st.button("Leggi Referto"):
            with st.spinner("OCR in corso..."):
                txt = extract_text_from_pdf(fup)
                st.session_state.rep_ai = get_ai_analysis(df, txt, is_report=True)
                b64 = base64.b64encode(fup.getvalue()).decode('utf-8')
                supabase.table("referti_medici").insert({"nome_referto":fup.name, "data_esame":str(datetime.now().date()), "file_path":b64, "note":txt}).execute()
                st.rerun()
        if "rep_ai" in st.session_state: st.info(st.session_state.rep_ai)
        st.divider()
        docs = supabase.table("referti_medici").select("*").order("data_esame", desc=True).execute().data
        for d in (docs or []):
            with st.expander(f"📄 {d['data_esame']} - {d['nome_referto']}"):
                st.download_button("Scarica", base64.b64decode(d['file_path']), file_name=d['nome_referto'], key=f"dl_{d['id']}")

    with tabs[5]:
        st.subheader("📋 Registro")
        pdf_rep = export_pdf(df, st.session_state.get("ai_text", "Generare analisi."))
        st.download_button("📥 Scarica Report PDF per il Medico", pdf_rep, "report_clinico.pdf", "application/pdf")
        st.dataframe(df.sort_values('created_at', ascending=False), use_container_width=True)
else:
    st.info("Inserisci una misura nella sidebar.")
