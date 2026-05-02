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
    # 1. Recupero dati numerici recenti
    recent = df.sort_values(by='created_at', ascending=False).head(12)
    data_summary = recent.to_string(columns=['created_at', 'oxygen', 'bpm', 'systolic', 'diastolic', 'weight', 'temperature', 'notes'])
    
    # 2. Recupero le ultime analisi dei referti salvate (Tabella referti_medici)
    try:
        ref_res = supabase.table("referti_medici").select("data_esame, nome_referto, analisi_ia").order("data_esame", desc=True).limit(3).execute()
        referti_context = ""
        if ref_res.data:
            for r in ref_res.data:
                referti_context += f"- DATA: {r['data_esame']} | TIPO: {r['nome_referto']} | ESITO IA: {r['analisi_ia']}\n"
        else:
            referti_context = "Nessun referto recente in archivio."
    except:
        referti_context = "Errore nel recupero storico referti."
    
    sys_prompt = f"""Sei un Medico Specialista in Medicina Interna e Diagnostica.
    I#l tuo compito è fornire un'analisi clinica oggettiva e completa per il paziente {profile['nome_paziente']}.
    
    PROFILO CLINICO FISSO: {profile['quadro_clinico']}
    TERAPIA IN CORSO: {profile['terapia_attuale']}
    
    DATI A TUA DISPOSIZIONE:
    1. TREND PARAMETRI (Ultimi giorni): 
    {data_summary}
    
    2. STORICO REFERTI (Ecografie, RX, Analisi):
    {referti_context}

    OBIETTIVO:
    - Analizza se i parametri numerici attuali sono coerenti con i referti medici.
    - Se l'utente segnala nuovi sintomi nel 'CONTESTO', verifica se possono essere collegati ai referti archiviati (es: un dolore addominale collegato a un'ecografia specifica).
    - Fornisci una valutazione professionale, oggettiva e strutturata in: 'Sintesi Clinica Integrata', 'Correlazione Parametri-Referti' e 'Suggerimenti di Monitoraggio'."""

    prompt = f"[CONTESTO ATTUALE RIFERITO DALL'UTENTE]: {context if context else 'Nessuna nota specifica oggi.'}"
    
    try:
        response = client_ai.chat.completions.create(
            model="gpt-4o", # GPT-4o è fondamentale qui per la capacità di sintesi medica
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": prompt}],
            temperature=0.3
        )
        return response.choices[0].message.content
    except Exception as e: return f"Errore AI: {e}"

def get_professional_ai_analysis(df, profile, user_context=""):
    # 1. Recupero Dati Numerici (ultimi 14 record per vedere i trend)
    recent_data = df.sort_values(by='created_at', ascending=False).head(14)
    data_summary = recent_data.to_string(columns=['created_at', 'oxygen', 'bpm', 'systolic', 'diastolic', 'weight', 'temperature', 'notes'])
    
    # 2. Recupero Referti (ultimi 3 per contesto clinico)
    try:
        ref_res = supabase.table("referti_medici").select("data_esame, nome_referto, analisi_ia").order("data_esame", desc=True).limit(3).execute()
        referti_context = "\n".join([f"- {r['data_esame']}: {r['nome_referto']} -> {r['analisi_ia']}" for r in ref_res.data]) if ref_res.data else "Nessun referto disponibile."
    except:
        referti_context = "Errore recupero referti."

    # 3. LOGICA DI RICERCA ONLINE (Simulata tramite capacità interna del modello 2026)
    # L'IA userà le informazioni per cercare linee guida (es. ESC, AHA, ERS)
    
    sys_prompt = f"""Sei un Senior Medical Consultant esperto in Diagnostica Integrata. 
    Il tuo obiettivo è fornire un'analisi clinica di alto livello per il paziente {profile['nome_paziente']}.

    QUADRO CLINICO DI BASE: {profile['quadro_clinico']}
    TERAPIA ATTUALE: {profile['terapia_attuale']}

    DATI DA ANALIZZARE:
    --- PARAMETRI RECENTI ---
    {data_summary}
    
    --- STORICO REFERTI SPECIALISTICI ---
    {referti_context}
    
    --- CONTESTO RIFERITO OGGI ---
    {user_context if user_context else "Nessuna nota aggiuntiva."}

    ISTRUZIONI PROFESSIONALI:
    1. CORRELAZIONE CLINICA: Incrocia i parametri numerici con i referti. (Esempio: se l'ecografia mostra ipertrofia, valuta con estrema attenzione i picchi di pressione).
    2. RICERCA EVIDENZE: Agisci come se avessi consultato le linee guida mediche aggiornate al 2026. Cita standard internazionali (es. 'Secondo i protocolli ESC...').
    3. ANALISI DEI TREND: Non guardare solo l'ultimo dato. Identifica se c'è un peggioramento o una stabilità.
    4. LINGUAGGIO: Usa terminologia medica corretta ma resta comprensibile.
    
    STRUTTURA REPORT:
    ## 🩺 Sintesi Diagnostica Integrata
    (Un riassunto che correla tutto il quadro)
    
    ## 📚 Evidenze e Linee Guida (Ricerca 2026)
    (Confronto dei dati del paziente con la letteratura medica attuale)
    
    ## ⚠️ Segnali di Attenzione e Monitoraggio
    (Cosa tenere d'occhio e perché)
    
    ## 📋 Nota per il Medico Curante
    (Una frase tecnica da riferire allo specialista)
    """

    try:
        # Nota: Usiamo GPT-4o per la massima capacità di ragionamento
        response = client_ai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": "Genera l'analisi professionale basata sui dati caricati."}
            ],
            temperature=0.3 # Bassa temperatura per massima precisione e rigore
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Errore nell'analisi professionale: {e}"

def OLD_get_ai_analysis(df, profile, context="", is_report=False):
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
    
    # Intestazione
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, clean_text_for_pdf(f"REPORT CLINICO: {profile['nome_paziente']}"), ln=True, align="C")
    
    # Sezione Profilo Paziente
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(0, 8, " INFORMAZIONI PAZIENTE E TERAPIA", ln=True, fill=True)
    pdf.set_font("Arial", "", 9)
    info_testo = f"Quadro Clinico: {profile['quadro_clinico']}\nTerapia Attuale: {profile['terapia_attuale']}"
    pdf.multi_cell(0, 5, clean_text_for_pdf(info_testo))
    pdf.ln(5)

    # Sezione Analisi Integrata IA
    pdf.set_fill_color(245, 245, 245)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(0, 8, " VALUTAZIONE CLINICA ASSISTENTE IA (Sintesi Dati + Referti)", ln=True, fill=True)
    pdf.set_font("Arial", "", 9)
    pdf.multi_cell(0, 5, clean_text_for_pdf(ai_comment))
    pdf.ln(5)

    # Tabella Dati con colonna NOTE ripristinata
    pdf.set_fill_color(230, 240, 255)
    pdf.set_font("Arial", "B", 8)
    
    # Larghezze colonne regolate per far stare le Note (totale ~190mm)
    # Data(30), O2(10), BPM(10), Press(18), Temp(10), Peso(12), Note(100)
    cols = [
        ("Data Ora", 30), ("O2", 10), ("BPM", 10), 
        ("Press", 18), ("T C", 10), ("Kg", 12), ("Note/Sintomi", 100)
    ]
    
    for h, w in cols: 
        pdf.cell(w, 8, h, 1, 0, "C", True)
    pdf.ln()
    
    pdf.set_font("Arial", "", 7) # Font leggermente più piccolo per le note lunghe
    df_sorted = df.sort_values(by='created_at', ascending=False)
    
    for _, r in df_sorted.head(50).iterrows():
        # Calcoliamo l'altezza della riga in base alla lunghezza della nota
        nota = str(r.get('notes', '-')) if r.get('notes') else "-"
        # Pulizia testo
        nota_clean = clean_text_for_pdf(nota)
        
        # Salviamo la posizione corrente
        x = pdf.get_x()
        y = pdf.get_y()
        
        # Stampiamo le celle fisse
        pdf.cell(30, 6, r['created_at'].strftime('%d/%m/%y %H:%M'), 1)
        pdf.cell(10, 6, f"{r.get('oxygen','-')}%", 1, 0, "C")
        pdf.cell(10, 6, str(r.get('bpm','-')), 1, 0, "C")
        pdf.cell(18, 6, f"{r.get('systolic','-')}/{r.get('diastolic','-')}", 1, 0, "C")
        pdf.cell(10, 6, str(r.get('temperature','-')), 1, 0, "C")
        pdf.cell(12, 6, str(r.get('weight','-')), 1, 0, "C")
        
        # Multi_cell per la colonna Note (permette il wrap del testo)
        pdf.multi_cell(100, 6, nota_clean, 1, "L")
        
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
    tabs = st.tabs([
        "📈 Trend", 
        "🧬 Statistiche", 
        "🤖 Assistente IA", 
        "📅 Visite", 
        "📂 Referti (OCR)", 
        "👤 Profilo", 
        "📋 Registro",
        "📞 Contatti"
    ])

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

    with tabs[2]: # AI (Tab Assistente AI)
        st.subheader("🤖 Assistente Medico Integrato (Dati + Referti)")
        with st.expander("📝 Descrivi come ti senti oggi", expanded=True):
            exc = st.text_area("Inserisci sintomi, sensazioni o domande per l'IA...")
        
        if st.button("🚀 Avvia Analisi Integrata"):
            with st.spinner("L'IA sta incrociando i tuoi parametri con lo storico dei referti..."):
                # Ora get_ai_analysis farà tutto il lavoro di recupero referti internamente
                #st.session_state.ai_text = get_professional_ai_analysis(df, profile, exc)
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

#    with tabs[6]: # Registro & PDF
#        st.subheader("📋 Registro")
#        ai_rep = st.session_state.get("ai_text", "Analisi non generata.")
#        pdf_rep = export_pdf(df, profile, ai_rep)
#        st.download_button("📥 Scarica Report PDF", pdf_rep, "report.pdf", "application/pdf")
#        st.dataframe(df.sort_values('created_at', ascending=False), use_container_width=True)
    with tabs[6]: # Registro & PDF
        st.subheader("📋 Registro Storico")
        
        # 1. Preparazione del PDF
        ai_rep = st.session_state.get("ai_text", "Analisi non generata.")
        pdf_rep = export_pdf(df, profile, ai_rep)
        st.download_button("📥 Scarica Report Medico PDF", pdf_rep, "report_clinico.pdf", "application/pdf")
        
        if not df.empty:
            # --- MODIFICA QUI PER LA VISUALIZZAZIONE TABELLA ---
            
            # Creiamo una copia per la visualizzazione senza toccare i dati originali
            df_display = df.copy()
            
            # Rimuoviamo la colonna 'id' (se esiste)
            if 'id' in df_display.columns:
                df_display = df_display.drop(columns=['id'])
            
            # Ordiniamo le colonne per mettere 'notes' come ultima
            # Recuperiamo tutte le colonne tranne 'notes'
            cols = [c for c in df_display.columns if c != 'notes']
            # Le riassembliamo mettendo 'notes' in fondo
            df_display = df_display[cols + ['notes']]
            
            # Rinominiamo le colonne per un aspetto più pulito (opzionale)
            df_display.columns = [c.replace('_', ' ').title() for c in df_display.columns]
            
            # Visualizzazione
            st.dataframe(
                df_display.sort_values(by=df_display.columns[0], ascending=False), 
                use_container_width=True,
                hide_index=True # Nasconde anche l'indice numerico di Streamlit per pulizia massima
            )
        else:
            st.info("Nessun dato registrato.")

    with tabs[7]: # Nuovo Tab: Contatti Medici
        st.subheader("📞 Rubrica Medica Specialistica")
        
        # Form per aggiungere un nuovo contatto
        with st.expander("➕ Aggiungi Nuovo Medico/Contatto"):
            with st.form("nuovo_contatto", clear_on_submit=True):
                c1, c2 = st.columns(2)
                nome_m = c1.text_input("Nome e Cognome")
                ruolo_m = c2.text_input("Specializzazione (es. Cardiologo)")
                mail_m = c1.text_input("Email")
                tel_m = c2.text_input("Telefono")
                note_m = st.text_area("Note (es. Orari studio, Indirizzo)")
                
                if st.form_submit_button("Salva Contatto"):
                    if nome_m:
                        supabase.table("contatti_medici").insert({
                            "nome_medico": nome_m,
                            "ruolo": ruolo_m,
                            "email": mail_m,
                            "telefono": tel_m,
                            "note": note_m
                        }).execute()
                        st.success(f"Contatto di {nome_m} salvato!")
                        st.rerun()
                    else:
                        st.error("Il nome è obbligatorio.")

        st.divider()

        # Visualizzazione Contatti
        contatti_res = supabase.table("contatti_medici").select("*").order("nome_medico").execute()
        contatti = contatti_res.data if contatti_res.data else []

        if not contatti:
            st.info("La rubrica è vuota.")
        else:
            for c in contatti:
                with st.container(border=True):
                    col_info, col_azioni = st.columns([3, 1])
                    with col_info:
                        st.markdown(f"### {c['nome_medico']}")
                        st.caption(f"🧬 {c['ruolo']}")
                        if c['email']: st.write(f"📧 {c['email']}")
                        if c['telefono']: st.write(f"📞 **{c['telefono']}**")
                        if c['note']: st.info(f"📝 {c['note']}")
                    
                    with col_azioni:
                        # Pulsante per eliminare (opzionale)
                        if st.button("Elimina", key=f"del_c_{c['id']}"):
                            supabase.table("contatti_medici").delete().eq("id", c['id']).execute()
                            st.rerun()
                        
                        # Link rapidi per smartphone
                        if c['telefono']:
                            st.markdown(f'''<a href="tel:{c['telefono']}"><button style="width:100%; border-radius:5px; background-color:#2e7d32; color:white; border:none; padding:5px;">Chiama ora</button></a>''', unsafe_allow_html=True)
                            
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
