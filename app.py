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

def extract_text_from_pdf(pdf_file):
    try:
        with pdfplumber.open(pdf_file) as pdf:
            return "\n".join([page.extract_text() for page in pdf.pages if page.extract_text()])
    except Exception as e:
        return f"Errore lettura PDF: {e}"

def get_ai_analysis(df, profile, context="", is_report=False):
    recent = df.sort_values(by='created_at', ascending=False).head(15)
    data_summary = recent.to_string(columns=['created_at', 'oxygen', 'bpm', 'systolic', 'diastolic', 'weight', 'temperature', 'notes'])
    
    sys_prompt = f"""Sei un medico specialista. Analizza i dati di {profile['nome_paziente']}.
    QUADRO CLINICO: {profile['quadro_clinico']}
    TERAPIA: {profile['terapia_attuale']}
    SOGLIA O2 MIN: {profile['soglia_ossigeno_min']}%"""

    prompt = f"DATI RECENTI:\n{data_summary}\n\nCONTESTO AGGIUNTIVO: {context}"
    if is_report: prompt = f"ANALISI REFERTO:\n{context}\n\nCONFRONTO CON STORICO:\n{data_summary}"
    
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
    
    # Info Profilo
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(0, 8, " INFORMAZIONI PAZIENTE", ln=True, fill=True)
    pdf.set_font("Arial", "", 9)
    pdf.multi_cell(0, 5, clean_text(f"Quadro: {profile['quadro_clinico']}\nTerapia: {profile['terapia_attuale']}"))
    pdf.ln(5)

    # Analisi IA
    pdf.set_fill_color(245, 245, 245)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(0, 8, " ANALISI ASSISTENTE IA", ln=True, fill=True)
    pdf.set_font("Arial", "", 9)
    pdf.multi_cell(0, 6, clean_text(ai_comment))
    pdf.ln(5)

    # Tabella Dati
    pdf.set_fill_color(230, 240, 255)
    pdf.set_font("Arial", "B", 8)
    cols = [("Data Ora", 35), ("O2", 12), ("BPM", 12), ("T C", 12), ("Press", 20), ("Peso", 15)]
    for h, w in cols: pdf.cell(w, 8, h, 1, 0, "C", True)
    pdf.ln()
    pdf.set_font("Arial", "", 8)
    df_sorted = df.sort_values(by='created_at', ascending=False)
    for _, r in df_sorted.iterrows():
        pdf.cell(35, 7, r['created_at'].strftime('%d/%m/%y %H:%M'), 1)
        pdf.cell(12, 7, f"{r.get('oxygen','-')}%", 1, 0, "C")
        pdf.cell(12, 7, str(r.get('bpm','-')), 1, 0, "C")
        pdf.cell(12, 7, str(r.get('temperature','-')), 1, 0, "C")
        pdf.cell(20, 7, f"{r.get('systolic','-')}/{r.get('diastolic','-')}", 1, 0, "C")
        pdf.cell(15, 7, str(r.get('weight','-')), 1, 0, "C")
        pdf.ln()

    # Sezione Note dedicata (per non troncarle)
    pdf.add_page()
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "DIARIO NOTE E OSSERVAZIONI", ln=True)
    pdf.ln(2)
    for _, r in df_sorted.iterrows():
        if r['notes'] and str(r['notes']).strip() != "":
            pdf.set_font("Arial", "B", 9)
            pdf.cell(0, 6, r['created_at'].strftime('%d/%m/%Y %H:%M'), ln=True)
            pdf.set_font("Arial", "", 10)
            pdf.multi_cell(0, 6, clean_text(str(r['notes'])))
            pdf.ln(2)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(2)

    return pdf.output(dest='S').encode('latin-1')

# --- 5. RECUPERO DATI ---
p_res = supabase.table("user_profile").select("*").eq("id", 1).execute()
profile = p_res.data[0] if p_res.data else {"nome_paziente": "Alessio", "quadro_clinico": "", "terapia_attuale": "", "soglia_ossigeno_min": 94}

res = supabase.table("health_logs").select("*").order("created_at").execute()
df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
if not df.empty:
    df['created_at'] = pd.to_datetime(df['created_at'], format='mixed', errors='coerce').dt.tz_localize(None)
    df = df.dropna(subset=['created_at']).sort_values('created_at')

# --- 6. INTERFACCIA ---
st.title(f"🩺 Sanity Diary Intelligence")

# Banner Visite
try:
    v_res = supabase.table("visite_mediche").select("*").eq("completata", False).order("data_visita").execute()
    if v_res.data:
        vn = v_res.data[0]
        st.warning(f"📅 **Prossima Visita:** {vn['nome_visita']} il {vn['data_visita']}")
except: pass

if not df.empty:
    m = st.columns(4)
    def get_delta(col):
        v = df[col].dropna()
        if len(v) < 2: return None
        return round(float(v.iloc[-1] - v.iloc[-2]), 1)
    
    m[0].metric("Ossigeno", f"{df['oxygen'].iloc[-1]}%", get_delta('oxygen'))
    m[1].metric("BPM", df['bpm'].iloc[-1], get_delta('bpm'), delta_color="inverse")
    m[2].metric("Pressione", f"{df['systolic'].iloc[-1]}/{df['diastolic'].iloc[-1]}", get_delta('systolic'), delta_color="inverse")
    m[3].metric("Peso", f"{df['weight'].iloc[-1]}kg", get_delta('weight'))

    st.divider()
    tabs = st.tabs(["📈 Trend", "🧬 Statistiche", "🤖 Assistente IA", "📅 Visite", "📂 Referti (OCR)", "👤 Profilo", "📋 Registro"])

    with tabs[0]:
        st.plotly_chart(px.line(df, x='created_at', y=['oxygen', 'bpm', 'systolic', 'diastolic', 'weight', 'temperature'], markers=True, template="plotly_white"), use_container_width=True)

    with tabs[1]:
        st.subheader("🧬 Studio Correlazioni (Pearson)")
        cd, cm = st.columns([1, 2])
        sc = ['oxygen', 'bpm', 'systolic', 'diastolic', 'weight', 'temperature']
        with cd:
            st.markdown("### 📊 Insight")
            if len(df) > 2:
                corr = df[sc].corr().unstack().sort_values(ascending=False)
                top = corr[corr < 0.99].head(1)
                if not top.empty:
                    st.info(f"Relazione rilevata tra {top.index[0][0]} e {top.index[0][1]} ({top.values[0]:.2f})")
        with cm:
            st.plotly_chart(px.imshow(df[sc].corr(), text_auto=".2f", color_continuous_scale='RdBu_r'), use_container_width=True)

    with tabs[2]:
        st.subheader("🤖 Assistente IA Personalizzato")
        exc = st.text_area("Aggiungi note per l'analisi:")
        if st.button("Esegui Analisi Clinica"):
            st.session_state.ai_text = get_ai_analysis(df, profile, exc)
        if "ai_text" in st.session_state: st.markdown(st.session_state.ai_text)

    with tabs[3]:
        v1, v2 = st.columns([1, 2])
        with v1:
            with st.form("av"):
                nv, dv, lv = st.text_input("Visita"), st.date_input("Data"), st.text_input("Luogo")
                if st.form_submit_button("Salva"):
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
        st.subheader("📂 Archivio Referti & OCR")
        fup = st.file_uploader("Carica PDF", type="pdf")
        if fup and st.button("Analizza con IA"):
            with st.spinner("Lettura..."):
                txt = extract_text_from_pdf(fup)
                st.session_state.rep_ai = get_ai_analysis(df, profile, txt, is_report=True)
                b64 = base64.b64encode(fup.getvalue()).decode('utf-8')
                supabase.table("referti_medici").insert({"nome_referto":fup.name, "data_esame":str(datetime.now().date()), "file_path":b64, "note":txt}).execute()
                st.rerun()
        if "rep_ai" in st.session_state: st.success(st.session_state.rep_ai)
        st.divider()
        for d in (supabase.table("referti_medici").select("*").order("data_esame", desc=True).execute().data or []):
            with st.expander(f"📄 {d['data_esame']} - {d['nome_referto']}"):
                st.download_button("Scarica", base64.b64decode(d['file_path']), file_name=d['nome_referto'], key=f"dl_{d['id']}")

    with tabs[5]:
        st.subheader("👤 Profilo Clinico")
        with st.form("up_prof"):
            nome = st.text_input("Nome", profile['nome_paziente'])
            quadro = st.text_area("Quadro Clinico", profile['quadro_clinico'])
            terapia = st.text_area("Terapia", profile['terapia_attuale'])
            soglia = st.number_input("Soglia O2", 80, 100, profile['soglia_ossigeno_min'])
            if st.form_submit_button("Salva Profilo"):
                supabase.table("user_profile").update({"nome_paziente":nome, "quadro_clinico":quadro, "terapia_attuale":terapia, "soglia_ossigeno_min":soglia}).eq("id", 1).execute()
                st.rerun()

    with tabs[6]:
        pdf_rep = export_pdf(df, profile, st.session_state.get("ai_text", "Nessuna analisi."))
        st.download_button("📥 Scarica Report PDF", pdf_rep, "report.pdf", "application/pdf")
        st.dataframe(df.sort_values('created_at', ascending=False), use_container_width=True)
else:
    st.info("Inserisci una misura nella sidebar per iniziare.")

# Sidebar (sempre visibile)
with st.sidebar:
    st.header("⚙️ Nuova Misura")
    with st.form("h", clear_on_submit=True):
        o, b = st.number_input("O2%", 0, 100, 98), st.number_input("BPM", 0, 200, 70)
        s, d = st.number_input("Sist.", 0, 200, 120), st.number_input("Diast.", 0, 150, 80)
        w, t = st.number_input("Peso", 0.0, 200.0, 80.0), st.number_input("Temp", 30.0, 45.0, 36.5)
        n = st.text_area("Note")
        if st.form_submit_button("Salva"):
            supabase.table("health_logs").insert({"oxygen":o, "bpm":b, "systolic":s, "diastolic":d, "weight":w, "temperature":t, "notes":n}).execute()
            st.rerun()
