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
    if df.empty or len(df) < 2: return "Dati insufficienti per l'analisi."
    recent = df.sort_values(by='created_at', ascending=False).head(10)
    summary = recent.to_string(columns=['created_at', 'oxygen', 'bpm', 'systolic', 'diastolic', 'notes', 'temperature'])
    prompt_paziente = f"CONTESTO CLINICO: Post-Embolia Polmonare. Analizza stabilità: {summary}"
    try:
        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Sei un assistente medico esperto."},
                {"role": "user", "content": prompt_paziente}
            ]
        )
        return response.choices[0].message.content
    except Exception as e: return f"Errore API: {str(e)}"

# NUOVA FUNZIONE: Analisi IA specifica per il Referto
def get_ai_document_analysis(doc_name, context=""):
    if not client_ai: return "AI non configurata."
    prompt = f"Analizza sinteticamente questo referto medico: '{doc_name}'. Contestualizzalo per un paziente post-embolia polmonare. Note aggiuntive: {context}"
    try:
        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Sei un medico che spiega referti in modo semplice ma rigoroso."},
                {"role": "user", "content": prompt}
            ]
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

    # Banner Visite (Invariato)
    try:
        res_v = supabase.table("visite_mediche").select("*").eq("completata", False).order("data_visita").execute()
        if res_v.data:
            v = res_v.data[0]
            st.warning(f"📅 **Prossima Visita:** {v['nome_visita']} il {v['data_visita']} ({v['luogo']})")
    except: pass

    if not df.empty:
        # Metriche (Invariate)
        m = st.columns(4)
        def get_delta(col):
            vals = df[col].dropna()
            return round(float(vals.iloc[-1] - vals.iloc[-2]), 1) if len(vals) >= 2 else None
        m[0].metric("Ossigeno", f"{df['oxygen'].iloc[-1]}%", get_delta('oxygen'))
        m[1].metric("BPM", f"{df['bpm'].iloc[-1]}", get_delta('bpm'), delta_color="inverse")
        m[2].metric("Press. Max", f"{df['systolic'].iloc[-1]}", get_delta('systolic'), delta_color="inverse")
        m[3].metric("Peso", f"{df['weight'].iloc[-1]}kg", get_delta('weight'))

        st.divider()
        tabs = st.tabs(["📈 Trend", "🧬 Pearson", "🤖 Assistente IA", "📅 Visite", "📂 Referti", "📋 Registro"])

        with tabs[0]:
            st.subheader("Andamento Temporale")
            all_params = ['oxygen', 'bpm', 'systolic', 'diastolic', 'weight', 'temperature']
            available_cols = [c for c in all_params if c in df.columns]
            st.plotly_chart(px.line(df.sort_values('created_at'), x='created_at', y=available_cols, markers=True, template="plotly_white"), use_container_width=True)

        with tabs[1]:
            st.subheader("🧬 Studio Correlazioni (Pearson)")
            if len(available_cols) > 1:
                st.plotly_chart(px.imshow(df[available_cols].corr(), text_auto=".2f", color_continuous_scale='RdBu_r'), use_container_width=True)

        with tabs[2]:
            st.subheader("🤖 Analisi Specialistica IA")
            if st.button("Esegui Analisi Generale"):
                with st.spinner("Analizzando..."): st.session_state.ai_text = get_ai_narrative_analysis(df)
            if "ai_text" in st.session_state: st.markdown(st.session_state.ai_text)

        with tabs[3]:
            # Gestione Visite (Invariata)
            cv1, cv2 = st.columns([1, 2])
            with cv1:
                with st.form("vis"):
                    nv, dv, lv = st.text_input("Visita"), st.date_input("Data"), st.text_input("Luogo")
                    if st.form_submit_button("Aggiungi"):
                        supabase.table("visite_mediche").insert({"nome_visita":nv, "data_visita":str(dv), "luogo":lv, "completata":False}).execute()
                        st.rerun()
            with cv2:
                for v in (supabase.table("visite_mediche").select("*").order("data_visita").execute().data or []):
                    st.write(f"{'✅' if v['completata'] else '⏳'} **{v['data_visita']}**: {v['nome_visita']} ({v['luogo']})")

        # --- SEZIONE REFERTI AGGIORNATA ---
        with tabs[4]:
            st.subheader("📂 Archivio Documenti & Analisi")
            
            with st.expander("➕ Carica nuovo referto"):
                up = st.file_uploader("Seleziona PDF", type="pdf")
                notes_doc = st.text_area("Note sul referto (opzionale)")
                if st.button("Salva Documento") and up:
                    b64 = base64.b64encode(up.read()).decode('utf-8')
                    supabase.table("referti_medici").insert({
                        "nome_referto": up.name, 
                        "data_esame": str(datetime.now().date()), 
                        "file_path": b64,
                        "note": notes_doc
                    }).execute()
                    st.success("Referto caricato correttamente!"); st.rerun()

            # Elenco Referti con Preview e Analisi IA
            res_r = supabase.table("referti_medici").select("*").order("data_esame", desc=True).execute()
            for r in (res_r.data or []):
                with st.expander(f"📄 {r['data_esame']} - {r['nome_referto']}"):
                    col_file, col_ai = st.columns([1, 1])
                    
                    with col_file:
                        f_bytes = base64.b64decode(r['file_path'])
                        st.download_button("💾 Scarica PDF", f_bytes, file_name=r['nome_referto'], key=f"dl_{r['id']}")
                        # Preview PDF
                        pdf_display = f'<iframe src="data:application/pdf;base64,{r["file_path"]}" width="100%" height="400" type="application/pdf"></iframe>'
                        st.markdown(pdf_display, unsafe_allow_html=True)
                    
                    with col_ai:
                        st.write("**🤖 Analisi IA Referto:**")
                        if st.button(f"Analizza questo referto", key=f"btn_ai_{r['id']}"):
                            with st.spinner("L'IA sta leggendo il referto..."):
                                analysis = get_ai_document_analysis(r['nome_referto'], r.get('note', ''))
                                st.session_state[f"ai_doc_{r['id']}"] = analysis
                        
                        current_analysis = st.session_state.get(f"ai_doc_{r['id']}", "")
                        if current_analysis:
                            st.info(current_analysis)
                        if r.get('note'):
                            st.caption(f"Note utente: {r['note']}")

        with tabs[5]:
            # Registro Storico (Invariato)
            st.subheader("Registro Storico")
            df_display = df.sort_values(by='created_at', ascending=False).copy()
            df_display['Data'] = df_display['created_at'].dt.strftime('%d/%m/%Y %H:%M')
            pdf_report = export_pdf(df, st.session_state.get("ai_text", "Nessuna analisi generata."))
            st.download_button("Scarica Report PDF per il Medico", pdf_report, "report_clinico.pdf", "application/pdf")
            st.dataframe(df_display[['Data', 'oxygen', 'bpm', 'systolic', 'diastolic', 'weight', 'temperature', 'notes']], use_container_width=True, hide_index=True)

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
