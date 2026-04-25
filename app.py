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
client_ai = OpenAI(api_key=st.secrets.get("OPENAI_API_KEY", "dummy_key"))

# --- 4. FUNZIONI IA E PDF ---
def get_ai_narrative_analysis(df):
    if df.empty or len(df) < 2: return "Dati insufficienti per l'analisi."
    recent = df.sort_values(by='created_at', ascending=False).head(10)
    summary = recent.to_string(columns=['created_at', 'oxygen', 'bpm', 'systolic', 'diastolic', 'notes'])
    try:
        response = client_ai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "system", "content": "Sei un assistente medico esperto. Analizza i trend senza fare diagnosi."},
                      {"role": "user", "content": f"Analizza questi dati pazienti:\n{summary}"}]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Nota: Analisi IA non disponibile (Verifica API Key o Quota). Errore: {e}"

def export_pdf(df, ai_comment):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "Report Clinico Sanity Diary Intelligence", ln=True, align="C")
    pdf.ln(5)
    
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, " Analisi Assistente IA", ln=True, fill=True)
    pdf.set_font("Arial", "", 10)
    pdf.multi_cell(0, 7, ai_comment)
    pdf.ln(5)

    pdf.set_fill_color(200, 220, 255)
    pdf.set_font("Arial", "B", 9)
    cols = [("Data", 30), ("O2", 15), ("BPM", 15), ("Temp", 15), ("Press", 25), ("Peso", 20), ("Note", 70)]
    for h, w in cols: pdf.cell(w, 10, h, 1, 0, "C", True)
    pdf.ln()
    pdf.set_font("Arial", "", 8)
    for _, row in df.sort_values(by='created_at', ascending=False).head(40).iterrows():
        date_str = row['created_at'].strftime('%d/%m/%y %H:%M') if hasattr(row['created_at'], 'strftime') else str(row['created_at'])
        pdf.cell(30, 8, date_str, 1)
        pdf.cell(15, 8, str(row.get('oxygen','-')), 1, 0, "C")
        pdf.cell(15, 8, str(row.get('bpm','-')), 1, 0, "C")
        pdf.cell(15, 8, str(row.get('temperature','-')), 1, 0, "C")
        p = f"{row.get('systolic','-')}/{row.get('diastolic','-')}"
        pdf.cell(25, 8, p, 1, 0, "C")
        pdf.cell(20, 8, str(row.get('weight','-')), 1, 0, "C")
        pdf.cell(70, 8, str(row.get('notes','-'))[:45], 1)
        pdf.ln()
    return bytes(pdf.output())

# --- 5. LOGICA APPLICATIVA ---
if supabase:
    # CARICAMENTO DATI (Gestione Errori Data Blindata)
    res = supabase.table("health_logs").select("*").order("created_at").execute()
    df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
    
    if not df.empty:
        # Correzione ValueError: utc=True e errors='coerce' per evitare crash
        df['created_at'] = pd.to_datetime(df['created_at'], utc=True, errors='coerce').dt.tz_localize(None)
        df = df.dropna(subset=['created_at']) # Rimuove eventuali righe con date corrotte

    st.title("🩺 Sanity Diary Intelligence")

    # Banner Promemoria Visite
    try:
        res_v = supabase.table("visite_mediche").select("*").eq("completata", False).order("data_visita").execute()
        if res_v.data:
            v = res_v.data[0]
            st.warning(f"🔔 **Prossima Visita:** {v['nome_visita']} il {v['data_visita']} ({v['luogo']})")
    except: pass

    if not df.empty:
        # Metriche Dashboard
        m = st.columns(4)
        def get_delta(col):
            if len(df) < 2: return None
            val = df[col].dropna()
            if len(val) < 2: return None
            return round(float(val.iloc[-1] - val.iloc[-2]), 1)

        m[0].metric("Ossigeno", f"{df['oxygen'].iloc[-1]}%", get_delta('oxygen'))
        m[1].metric("BPM", f"{df['bpm'].iloc[-1]}", get_delta('bpm'), delta_color="inverse")
        m[2].metric("Press. Max", f"{df['systolic'].iloc[-1]}", get_delta('systolic'), delta_color="inverse")
        m[3].metric("Peso", f"{df['weight'].iloc[-1]}kg", get_delta('weight'))

        st.divider()
        tabs = st.tabs(["📈 Trend", "🧬 Pearson", "🤖 Assistente IA", "📅 Visite", "📂 Referti", "📋 Registro"])

        with tabs[0]:
            st.subheader("Andamento Parametri")
            v_cols = [c for c in ['oxygen', 'bpm', 'systolic', 'diastolic', 'weight', 'temperature'] if c in df.columns]
            st.plotly_chart(px.line(df, x='created_at', y=v_cols, markers=True, template="plotly_white"), use_container_width=True)

        with tabs[1]:
            st.subheader("🧬 Studio delle Correlazioni (Pearson)")
            corr_cols = [c for c in ['oxygen', 'bpm', 'systolic', 'diastolic', 'weight', 'temperature'] if c in df.columns]
            if len(corr_cols) > 1:
                corr_matrix = df[corr_cols].corr()
                st.plotly_chart(px.imshow(corr_matrix, text_auto=".2f", color_continuous_scale='RdBu_r'), use_container_width=True)
            else: st.write("Dati insufficienti per la matrice.")

        with tabs[2]:
            st.subheader("🤖 Analisi Narrativa IA")
            if st.button("Genera Analisi con GPT"):
                with st.spinner("L'IA sta elaborando i dati..."):
                    st.session_state.ai_text = get_ai_narrative_analysis(df)
            st.info(st.session_state.get("ai_text", "Clicca il tasto sopra per generare l'analisi."))

        with tabs[3]:
            st.subheader("Gestione Visite")
            c1, c2 = st.columns([1, 2])
            with c1:
                with st.form("v_form"):
                    nv, dv, lv = st.text_input("Tipo Visita"), st.date_input("Data"), st.text_input("Luogo")
                    if st.form_submit_button("Salva"):
                        supabase.table("visite_mediche").insert({"nome_visita":nv, "data_visita":str(dv), "luogo":lv, "completata":False}).execute()
                        st.rerun()
            with c2:
                res_v_all = supabase.table("visite_mediche").select("*").order("data_visita").execute()
                for v in (res_v_all.data or []):
                    col_a, col_b = st.columns([4, 1])
                    status = "✅" if v['completata'] else "⏳"
                    col_a.write(f"{status} **{v['data_visita']}**: {v['nome_visita']} ({v['luogo']})")
                    if not v['completata'] and col_b.button("Fatto", key=f"v_{v['id']}"):
                        supabase.table("visite_mediche").update({"completata":True}).eq("id", v['id']).execute()
                        st.rerun()

        with tabs[4]:
            st.subheader("Archivio Referti")
            up = st.file_uploader("Carica PDF", type="pdf")
            if st.button("Salva PDF") and up:
                b64 = base64.b64encode(up.read()).decode('utf-8')
                supabase.table("referti_medici").insert({"nome_referto":up.name, "data_esame":str(datetime.now().date()), "file_path":b64}).execute()
                st.rerun()
            for r in (supabase.table("referti_medici").select("*").execute().data or []):
                st.download_button(f"📄 {r['nome_referto']}", base64.b64decode(r['file_path']), file_name=r['nome_referto'], key=f"r_{r['id']}")

        with tabs[5]:
            st.subheader("Registro Storico")
            st.download_button("Genera Report PDF", export_pdf(df, st.session_state.get("ai_text", "Analisi IA non generata.")), "report.pdf", "application/pdf")
            st.dataframe(df.sort_values(by='created_at', ascending=False), use_container_width=True, hide_index=True)

    with st.sidebar:
        st.header("⚙️ Inserimento")
        with st.form("h_form", clear_on_submit=True):
            o, b, s, d = st.number_input("O2%", 0), st.number_input("BPM", 0), st.number_input("Sistolica", 0), st.number_input("Diastolica", 0)
            w, t = st.number_input("Peso kg", 0.0), st.number_input("Temp °C", 0.0)
            n = st.text_area("Note")
            if st.form_submit_button("Salva"):
                supabase.table("health_logs").insert({"oxygen":o, "bpm":b, "systolic":s, "diastolic":d, "weight":w, "temperature":t, "notes":n}).execute()
                st.rerun()
        if st.button("Logout"):
            st.session_state.authenticated = False
            st.rerun()
