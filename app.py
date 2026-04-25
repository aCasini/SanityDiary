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
st.set_page_config(page_title="Sanity Diary Intelligence", page_icon="🧬", layout="wide")

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

def get_ai_narrative_analysis(df, terapia_df=None):
    if not client_ai: return "Chiave API non configurata."
    if df.empty or len(df) < 2: return "Dati insufficienti per l'analisi."
    
    recent = df.sort_values(by='created_at', ascending=False).head(10)
    summary = recent.to_string(columns=['created_at', 'oxygen', 'bpm', 'systolic', 'diastolic', 'notes', 'temperature'])
    terapia_txt = terapia_df.tail(7).to_string() if (terapia_df is not None and not terapia_df.empty) else "Dati terapia non disponibili."
    
    prompt_paziente = f"""
    CONTESTO CLINICO: Il paziente è in fase post-dimissione dopo un ricovero per EMBOLIA POLMONARE ESTESA.
    OBIETTIVO: Analizza stabilità emodinamica (O2, BPM, Pressione) e aderenza alla terapia.
    DATI SALUTE:
    {summary}
    DATI TERAPIA RECENTE:
    {terapia_txt}
    Fornisci un commento professionale. Non usare emoji.
    """
    
    try:
        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Sei un medico specializzato in pneumologia e cardiologia."},
                {"role": "user", "content": prompt_paziente}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Errore API: {str(e)}"

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
    # Caricamento Health Logs
    res = supabase.table("health_logs").select("*").order("created_at").execute()
    df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
    if not df.empty:
        df['created_at'] = pd.to_datetime(df['created_at'], format='ISO8601', errors='coerce').dt.tz_localize(None)
        df = df.dropna(subset=['created_at'])

    # Caricamento Terapia Logs
    try:
        res_t = supabase.table("terapia_logs").select("*").order("data", desc=True).execute()
        terapia_df = pd.DataFrame(res_t.data) if res_t.data else pd.DataFrame()
    except: terapia_df = pd.DataFrame()

    st.title("🩺 Sanity Diary Intelligence")

    # Banner Visite
    try:
        res_v = supabase.table("visite_mediche").select("*").eq("completata", False).order("data_visita").execute()
        if res_v.data:
            v = res_v.data[0]
            st.warning(f"📅 **Prossima Visita:** {v['nome_visita']} il {v['data_visita']} ({v['luogo']})")
    except: pass

    if not df.empty:
        # METRICHE CON COLOR CODING
        m = st.columns(4)
        latest = df.iloc[-1]
        
        # O2: Rosso < 94, Arancio < 96, Verde >= 96
        o2_val = latest['oxygen']
        o2_col = "normal" if o2_val >= 96 else "off" if o2_val >= 94 else "inverse"
        m[0].metric("Saturazione O2", f"{o2_val}%", delta_color=o2_col)

        # BPM: Rosso > 100, Arancio > 90, Verde <= 90
        bpm_val = latest['bpm']
        bpm_col = "normal" if bpm_val <= 90 else "off" if bpm_val <= 100 else "inverse"
        m[1].metric("Battiti (BPM)", f"{bpm_val}", delta_color=bpm_col)

        m[2].metric("Pressione Max", f"{latest['systolic']}", delta_color="normal")
        m[3].metric("Peso", f"{latest['weight']}kg")

        st.divider()
        tabs = st.tabs(["📈 Trend", "💊 Terapia", "🧬 Pearson", "🤖 Assistente IA", "📅 Visite", "📂 Referti", "📋 Registro"])

        with tabs[0]:
            st.subheader("Andamento Temporale")
            all_params = ['oxygen', 'bpm', 'systolic', 'diastolic', 'weight', 'temperature']
            available_cols = [c for c in all_params if c in df.columns]
            st.plotly_chart(px.line(df.sort_values('created_at'), x='created_at', y=available_cols, markers=True, template="plotly_white"), use_container_width=True)

        with tabs[1]:
            st.subheader("💊 Gestione Terapia Anticoagulante")
            c1, c2 = st.columns([1, 2])
            with c1:
                with st.form("form_terapia", clear_on_submit=True):
                    farmaco = st.text_input("Farmaco", "Eliquis")
                    dose = st.text_input("Dose", "5mg")
                    preso = st.checkbox("Assunto oggi?")
                    if st.form_submit_button("Registra"):
                        supabase.table("terapia_logs").insert({"data": str(datetime.now().date()), "farmaco": farmaco, "dose": dose, "assunto": preso}).execute()
                        st.success("Registrato!"); st.rerun()
            with c2:
                if not terapia_df.empty:
                    st.dataframe(terapia_df.head(10), use_container_width=True, hide_index=True)

        with tabs[2]:
            st.subheader("🧬 Studio Correlazioni (Pearson)")
            if len(available_cols) > 1:
                st.plotly_chart(px.imshow(df[available_cols].corr(), text_auto=".2f", color_continuous_scale='RdBu_r'), use_container_width=True)

        with tabs[3]:
            st.subheader("🤖 Analisi Specialistica IA")
            st.info("Monitoraggio Post-Embolia Polmonare Estesa.")
            if st.button("Esegui Analisi Incrociata"):
                with st.spinner("L'IA sta analizzando salute e terapia..."):
                    st.session_state.ai_text = get_ai_narrative_analysis(df, terapia_df)
            st.markdown(st.session_state.get("ai_text", "Clicca per iniziare."))

        with tabs[4]:
            st.subheader("Appuntamenti Medici")
            cv1, cv2 = st.columns([1, 2])
            with cv1:
                with st.form("vis"):
                    nv, dv, lv = st.text_input("Visita"), st.date_input("Data"), st.text_input("Luogo")
                    if st.form_submit_button("Aggiungi"):
                        supabase.table("visite_mediche").insert({"nome_visita":nv, "data_visita":str(dv), "luogo":lv, "completata":False}).execute()
                        st.rerun()
            with cv2:
                v_data = supabase.table("visite_mediche").select("*").order("data_visita").execute().data or []
                for v in v_data:
                    ca, cb = st.columns([4, 1])
                    ca.write(f"{'✅' if v['completata'] else '⏳'} **{v['data_visita']}**: {v['nome_visita']}")
                    if not v['completata'] and cb.button("Fatto", key=f"v_{v['id']}"):
                        supabase.table("visite_mediche").update({"completata":True}).eq("id", v['id']).execute(); st.rerun()

        with tabs[5]:
            st.subheader("📂 Archivio Referti UX")
            with st.expander("➕ Carica Nuovo PDF", expanded=False):
                up_f = st.file_uploader("Seleziona file", type="pdf")
                n_c = st.text_input("Nome Referto (es. TAC Torace)")
                if st.button("Salva Documento") and up_f:
                    b64 = base64.b64encode(up_f.read()).decode('utf-8')
                    supabase.table("referti_medici").insert({"nome_referto": n_c if n_c else up_f.name, "data_esame": str(datetime.now().date()), "file_path": b64}).execute()
                    st.success("Salvato!"); st.rerun()
            
            ref_list = supabase.table("referti_medici").select("*").order("data_esame", desc=True).execute().data or []
            if ref_list:
                c_search = st.text_input("🔍 Cerca referto...")
                r_cols = st.columns(3)
                for i, r in enumerate(ref_list):
                    if not c_search or c_search.lower() in r['nome_referto'].lower():
                        with r_cols[i % 3]:
                            st.markdown(f'<div style="border:1px solid #ddd;padding:10px;border-radius:8px;background:#f9f9f9"><b>{r["nome_referto"]}</b><br><small>{r["data_esame"]}</small></div>', unsafe_allow_html=True)
                            st.download_button("Scarica", base64.b64decode(r['file_path']), file_name=f"{r['nome_referto']}.pdf", key=f"r_{r['id']}")

        with tabs[6]:
            st.subheader("Registro Storico")
            pdf_r = export_pdf(df, st.session_state.get("ai_text", "Nessuna analisi generata."))
            st.download_button("Scarica Report PDF", pdf_r, "report.pdf", "application/pdf")
            st.dataframe(df.sort_values(by='created_at', ascending=False), use_container_width=True, hide_index=True)

    with st.sidebar:
        st.header("⚙️ Nuova Misura")
        with st.form("h", clear_on_submit=True):
            o, b = st.number_input("O2%", 0), st.number_input("BPM", 0)
            s, d = st.number_input("Sist.", 0), st.number_input("Diast.", 0)
            w, t = st.number_input("Peso", 0.0), st.number_input("Temp", 0.0)
            n = st.text_area("Note")
            if st.form_submit_button("Salva"):
                supabase.table("health_logs").insert({"oxygen":o, "bpm":b, "systolic":s, "diastolic":d, "weight":w, "temperature":t, "notes":n}).execute()
                st.rerun()
        if st.button("Logout"): st.session_state.authenticated = False; st.rerun()
