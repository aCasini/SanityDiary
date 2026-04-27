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
import re

# Import per OCR
try:
    import pdfplumber
except ImportError:
    st.error("Aggiungi 'pdfplumber' al file requirements.txt")

# --- 1. CONFIGURAZIONE PAGINA & PWA ---
st.set_page_config(page_title="Sanity Diary AI", page_icon="🧬", layout="wide")

def inject_pwa():
    pwa_html = """
    <link rel="manifest" href="./manifest.json">
    <link rel="apple-touch-icon" href="./icon-192.png">
    <meta name="theme-color" content="#31333F">
    <script>if('serviceWorker' in navigator){navigator.serviceWorker.register('./sw.js');}</script>
    """
    components.html(pwa_html, height=0)

#def inject_pwa():
#    pwa_html = """<link rel="manifest" href="./manifest.json"><script>if('serviceWorker' in navigator){navigator.serviceWorker.register('./sw.js');}</script>"""
#    components.html(pwa_html, height=0)

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
def clean_text_for_pdf(text):
    if not text: return ""
    # Rimuove Markdown (asterischi, cancelletti) per compatibilità FPDF
    clean = re.sub(r'\*\*|__|#', '', text)
    return clean.encode('latin-1', 'replace').decode('latin-1').replace('?', ' ')

def extract_text_from_pdf(pdf_file):
    try:
        with pdfplumber.open(pdf_file) as pdf:
            return "\n".join([page.extract_text() for page in pdf.pages if page.extract_text()])
    except Exception as e:
        return f"Errore lettura PDF: {e}"

def get_standalone_report_analysis(report_text):
    """Analisi pura del referto senza interferenze dai dati storici del diario."""
    sys_prompt = """Sei un medico radiologo/specialista. 
    Analizza il seguente referto (es. ecografia, RX, esami sangue) in modo OGGETTIVO e PROFESSIONALE.
    
    ISTRUZIONI:
    1. Trascrivi i punti chiave.
    2. Spiega in termini medici semplici ma precisi cosa è stato riscontrato.
    3. Evidenzia eventuali anomalie che richiedono attenzione immediata.
    NON usare i dati delle misurazioni giornaliere (ossigeno, bpm), concentrati SOLO sul testo fornito."""

    try:
        response = client_ai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": sys_prompt}, 
                {"role": "user", "content": f"ANALIZZA QUESTO REFERTO:\n{report_text}"}
            ],
            temperature=0.2
        )
        return response.choices[0].message.content
    except Exception as e: return f"Errore: {e}"

def get_ai_vision_analysis(base64_image):
    try:
        response = client_ai.chat.completions.create(
            model="gpt-4o", # Modello con capacità visive
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Sei un assistente medico. Trascrivi in modo professionale e oggettivo tutti i dati clinici, i valori degli esami e le conclusioni presenti in questa immagine di referto. Non tralasciare i valori fuori norma."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ],
                }
            ],
            max_tokens=2000
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Errore Vision: {e}"

def get_ai_analysis(df, profile, context="", is_report=False):
    # Selezione dati per analisi di trend
    recent = df.sort_values(by='created_at', ascending=False).head(12)
    data_summary = recent.to_string(columns=['created_at', 'oxygen', 'bpm', 'systolic', 'diastolic', 'weight', 'temperature', 'notes'])
    
    sys_prompt = f"""Sei un Medico Specialista esperto in Diagnostica e Medicina Interna.
    Il tuo obiettivo è fornire un'analisi clinica oggettiva, professionale e basata su evidenze per il paziente {profile['nome_paziente']}.
    
    PROFILO CLINICO NOTO:
    - Quadro: {profile['quadro_clinico']}
    - Terapia: {profile['terapia_attuale']}
    - Soglia O2: {profile['soglia_ossigeno_min']}%

    LINEE GUIDA PER L'ANALISI:
    1. APPROCCIO ANALITICO: Valuta i dati numerici cercando correlazioni (es. rapporto tra BPM e Saturazione o Pressione Differenziale).
    2. DIAGNOSI DIFFERENZIALE: Se l'utente riporta sintomi nel 'CONTESTO', incrociali con i dati e cita possibili quadri clinici simili o patologie che presentano pattern analoghi, basandoti sulla letteratura medica.
    3. VALUTAZIONE DEI RISCHI: Identifica segnali precursori di instabilità clinica.
    4. LINGUAGGIO: Usa terminologia medica appropriata (es. 'tachicardia compensatoria', 'ipossia lieve', 'iperpiressia', etc.).
    5. OGGETTIVITÀ: Separa chiaramente i fatti (dati) dalle ipotesi cliniche."""

    prompt = f"""
    [INPUT UTENTE / SINTOMATOLOGIA]: 
    "{context if context else 'Nessun sintomo specifico riferito.'}"

    [TREND DATI RECENTI]:
    {data_summary}

    ISTRUZIONE: Elabora un'analisi strutturata in: 
    - Valutazione Parametrica (Oggettiva)
    - Correlazione Clinica e Diagnosi Differenziale (basata su sintomi e letteratura)
    - Piano di Monitoraggio Suggerito.
    """
    
    try:
        response = client_ai.chat.completions.create(
            model="gpt-4o", # Usiamo GPT-4o per una capacità di ragionamento medico superiore
            messages=[
                {"role": "system", "content": sys_prompt}, 
                {"role": "user", "content": prompt}
            ],
            temperature=0.3 # Bassa temperatura per massima oggettività e precisione
        )
        return response.choices[0].message.content
    except Exception as e: return f"Errore AI: {e}"

def export_pdf(df, profile, ai_comment):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, clean_text_for_pdf(f"REPORT CLINICO: {profile['nome_paziente']}"), ln=True, align="C")
    
    # Sezione Profilo
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(0, 8, " INFORMAZIONI PAZIENTE", ln=True, fill=True)
    pdf.set_font("Arial", "", 9)
    pdf.multi_cell(0, 5, clean_text_for_pdf(f"Quadro: {profile['quadro_clinico']}\nTerapia: {profile['terapia_attuale']}"))
    pdf.ln(5)

    # Sezione AI pulita
    pdf.set_fill_color(245, 245, 245)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(0, 8, " ANALISI ASSISTENTE IA", ln=True, fill=True)
    pdf.set_font("Arial", "", 9)
    pdf.multi_cell(0, 6, clean_text_for_pdf(ai_comment))
    pdf.ln(5)

    # Tabella Dati
    pdf.set_fill_color(230, 240, 255)
    pdf.set_font("Arial", "B", 8)
    cols = [("Data Ora", 35), ("O2", 12), ("BPM", 12), ("T C", 12), ("Press", 20), ("Peso", 15)]
    for h, w in cols: pdf.cell(w, 8, h, 1, 0, "C", True)
    pdf.ln()
    
    pdf.set_font("Arial", "", 8)
    df_sorted = df.sort_values(by='created_at', ascending=False)
    for _, r in df_sorted.head(40).iterrows():
        pdf.cell(35, 7, r['created_at'].strftime('%d/%m/%y %H:%M'), 1)
        pdf.cell(12, 7, f"{r.get('oxygen','-')}%", 1, 0, "C")
        pdf.cell(12, 7, str(r.get('bpm','-')), 1, 0, "C")
        pdf.cell(12, 7, str(r.get('temperature','-')), 1, 0, "C")
        pdf.cell(20, 7, f"{r.get('systolic','-')}/{r.get('diastolic','-')}", 1, 0, "C")
        pdf.cell(15, 7, str(r.get('weight','-')), 1, 0, "C")
        pdf.ln()

    # Note
    pdf.add_page()
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "DIARIO NOTE COMPLETO", ln=True)
    for _, r in df_sorted.iterrows():
        if r['notes']:
            pdf.set_font("Arial", "B", 9)
            pdf.cell(0, 6, r['created_at'].strftime('%d/%m/%Y %H:%M'), ln=True)
            pdf.set_font("Arial", "", 10)
            pdf.multi_cell(0, 6, clean_text_for_pdf(str(r['notes'])))
            pdf.ln(4)
    return pdf.output(dest='S').encode('latin-1')

# --- 5. RECUPERO DATI ---
try:
    p_res = supabase.table("user_profile").select("*").eq("id", 1).execute()
    profile = p_res.data[0] if p_res.data else {"nome_paziente": "Alessio", "quadro_clinico": "Non configurato", "terapia_attuale": "Non configurata", "soglia_ossigeno_min": 94}
except:
    profile = {"nome_paziente": "Alessio", "quadro_clinico": "Errore Tabella", "terapia_attuale": "Configura DB", "soglia_ossigeno_min": 94}

res = supabase.table("health_logs").select("*").order("created_at").execute()
df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
if not df.empty:
    df['created_at'] = pd.to_datetime(df['created_at'], format='mixed', errors='coerce').dt.tz_localize(None)
    df = df.dropna(subset=['created_at']).sort_values('created_at')

# --- 6. INTERFACCIA ---
st.title("🩺 Sanity Diary Intelligence")

# Banner Visite (Ripristinato)
try:
    v_res = supabase.table("visite_mediche").select("*").eq("completata", False).order("data_visita").execute()
    if v_res.data:
        vn = v_res.data[0]
        st.warning(f"📅 **Prossima Visita:** {vn['nome_visita']} il {vn['data_visita']}")
except: pass

if not df.empty:
    # DASHBOARD METRICS CON DELTA (Ripristinato)
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

    with tabs[0]: # Trend
        st.plotly_chart(px.line(df, x='created_at', y=['oxygen', 'bpm', 'systolic', 'diastolic', 'weight', 'temperature'], markers=True, template="plotly_white"), use_container_width=True)

    with tabs[1]: # Statistiche Pearson (Ripristinato)
        st.subheader("🧬 Studio Correlazioni (Pearson)")
        cd, cm = st.columns([1, 2])
        sc = ['oxygen', 'bpm', 'systolic', 'diastolic', 'weight', 'temperature']
        with cd:
            st.markdown("### 📊 Insight")
            if len(df) > 2:
                corr = df[sc].corr().unstack().sort_values(ascending=False)
                top = corr[corr < 0.99].head(1)
                if not top.empty: st.info(f"Relazione tra {top.index[0][0]} e {top.index[0][1]}: {top.values[0]:.2f}")
        with cm:
            st.plotly_chart(px.imshow(df[sc].corr(), text_auto=".2f", color_continuous_scale='RdBu_r'), use_container_width=True)

    with tabs[2]: # AI (Migliorato Esteticamente)
        st.subheader("🤖 Smart Medical Assistant")
        with st.expander("📝 Note per l'IA", expanded=False):
            exc = st.text_area("Aggiungi dettagli extra (es: sintomi del giorno)")
        if st.button("🚀 Avvia Analisi"):
            with st.spinner("Analisi in corso..."):
                st.session_state.ai_text = get_ai_analysis(df, profile, exc)
        if "ai_text" in st.session_state:
            st.container(border=True).markdown(st.session_state.ai_text)

    with tabs[3]: # Visite (Ripristinato)
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

    with tabs[4]: # OCR Referti
        st.subheader("📂 Analisi Specifica Referto")
        fup = st.file_uploader("Carica PDF o scatta foto", type=["pdf", "jpg", "jpeg", "png"], key="scanner_v4")
        
        if fup is not None:
            if st.button("🚀 Analizza e Salva Referto"):
                with st.spinner("L'IA sta analizzando il documento clinico..."):
                    try:
                        # 1. Estrazione testo (OCR o Vision)
                        if fup.type == "application/pdf":
                            raw_text = extract_text_from_pdf(fup)
                        else:
                            base64_img = base64.b64encode(fup.getvalue()).decode('utf-8')
                            raw_text = get_ai_vision_analysis(base64_img)
                        
                        # 2. Analisi ISOLATA del referto (solo medica/oggettiva)
                        analisi_specifica = get_standalone_report_analysis(raw_text)
                        st.session_state.rep_ai = analisi_specifica
                        
                        # 3. Salvataggio nel DB nelle nuove colonne
                        file_bytes = fup.getvalue()
                        supabase.table("referti_medici").insert({
                            "nome_referto": fup.name, 
                            "data_esame": str(datetime.now().date()), 
                            "file_path": base64.b64encode(file_bytes).decode('utf-8'), 
                            "note": raw_text,        # Testo grezzo estratto
                            "analisi_ia": analisi_specifica # Analisi medica prodotta
                        }).execute()
                        
                        st.success("Referto salvato e analizzato!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Errore nel salvataggio: {e}")

        # Visualizzazione Analisi in tempo reale
        if "rep_ai" in st.session_state:
            with st.container(border=True):
                st.markdown("### 📋 Esito Analisi Referto")
                st.write(st.session_state.rep_ai)
                if st.button("Chiudi e torna all'elenco"):
                    del st.session_state.rep_ai
                    st.rerun()

        st.divider()
        st.subheader("📜 Archivio Referti")
        # Visualizzazione della lista aggiornata
        docs = supabase.table("referti_medici").select("*").order("data_esame", desc=True).execute().data
        for d in (docs or []):
            with st.expander(f"📄 {d['data_esame']} - {d['nome_referto']}"):
                # Mostriamo l'analisi IA se presente, altrimenti le note
                testo_da_mostrare = d.get('analisi_ia') or d.get('note') or "Nessun dato"
                st.info(testo_da_mostrare)
                
                if d.get('file_path'):
                    st.download_button("📥 Scarica Originale", base64.b64decode(d['file_path']), file_name=d['nome_referto'], key=f"dl_{d['id']}")

    with tabs[5]: # Profilo (Nuovo)
        st.subheader("👤 Profilo Clinico")
        with st.form("up_p"):
            nome = st.text_input("Nome", profile['nome_paziente'])
            quadro = st.text_area("Quadro Clinico", profile['quadro_clinico'])
            terapia = st.text_area("Terapia", profile['terapia_attuale'])
            soglia = st.number_input("Soglia O2", 80, 100, profile['soglia_ossigeno_min'])
            if st.form_submit_button("Salva Profilo"):
                supabase.table("user_profile").update({"nome_paziente":nome, "quadro_clinico":quadro, "terapia_attuale":terapia, "soglia_ossigeno_min":soglia}).eq("id", 1).execute()
                st.rerun()

    with tabs[6]: # Registro & PDF
        st.subheader("📋 Registro")
        ai_rep = st.session_state.get("ai_text", "Analisi non generata.")
        pdf_rep = export_pdf(df, profile, ai_rep)
        st.download_button("📥 Scarica Report PDF", pdf_rep, "report.pdf", "application/pdf")
        st.dataframe(df.sort_values('created_at', ascending=False), use_container_width=True)
else:
    st.info("Inserisci una misura nella sidebar.")

# Sidebar Misura (Sempre Attiva)
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
