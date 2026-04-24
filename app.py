import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
from fpdf import FPDF
from datetime import datetime
import base64

# --- 1. CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Sanity Diary", page_icon="🩺", layout="wide")

# --- 2. SISTEMA DI AUTENTICAZIONE ---
def check_password():
    """Ritorna True se l'utente è autenticato."""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    
    if st.session_state.authenticated:
        return True

    st.title("🔐 Accesso Riservato")
    with st.form("login_form"):
        password = st.text_input("Inserisci la password:", type="password")
        submit = st.form_submit_button("Accedi")
        if submit:
            # Controlla la password nei Secrets di Streamlit
            if password == st.secrets.get("APP_PASSWORD"):
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Password errata 🚫")
    return False

# Blocca l'esecuzione se non loggato
if not check_password():
    st.stop()

# --- 3. CONNESSIONE SUPABASE ---
@st.cache_resource
def init_db():
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except Exception as e:
        st.error(f"Errore connessione database: {e}")
        return None

supabase = init_db()

# --- 4. LOGICA PRINCIPALE ---
col_title, col_logout = st.columns([5, 1])
with col_title:
    st.title("🩺 Sanity Diary: Area Personale")
with col_logout:
    if st.button("Esci 🚪"):
        st.session_state.authenticated = False
        st.rerun()

if supabase:
    # --- RECUPERO DATI VITALI ---
    try:
        res = supabase.table("health_logs").select("*").order("created_at", desc=False).execute()
        df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
        
        if not df.empty:
            # FIX DEFINITIVO DATA: Usiamo ISO8601 per gestire microsecondi e fuso orario (+00:00)
            df['created_at'] = pd.to_datetime(df['created_at'], format='ISO8601', utc=True)
            # Rimuoviamo il fuso orario per compatibilità con tabelle e grafici e arrotondiamo al secondo
            df['created_at'] = df['created_at'].dt.tz_localize(None).dt.floor('S')
    except Exception as e:
        st.error(f"Errore recupero dati: {e}")
        df = pd.DataFrame()

    # --- SIDEBAR: NUOVA MISURAZIONE (GESTIONE NULL) ---
    with st.sidebar.form("medical_form", clear_on_submit=True):
        st.header("➕ Nuova Misurazione")
        st.info("Lascia a 0 i valori che non hai misurato.")
        
        oxy = st.number_input("Ossigeno %", 0, 100, 0)
        bpm = st.number_input("Battito (BPM)", 0, 250, 0)
        temp = st.number_input("Temperatura °C", 0.0, 45.0, 0.0, 0.1)
        sys = st.number_input("Pressione Sistolica (Max)", 0, 250, 0)
        dia = st.number_input("Pressione Diastolica (Min)", 0, 150, 0)
        weight = st.number_input("Peso (kg)", 0.0, 300.0, 0.0, 0.1)
        notes = st.text_area("Note/Sintomi")
        
        if st.form_submit_button("Salva nel Diario"):
            # Se il valore è 0 o stringa vuota, inviamo None (NULL nel DB)
            data_to_insert = {
                "oxygen": oxy if oxy > 0 else None,
                "bpm": bpm if bpm > 0 else None,
                "temperature": temp if temp > 0 else None,
                "systolic": sys if sys > 0 else None,
                "diastolic": dia if dia > 0 else None,
                "weight": weight if weight > 0 else None,
                "notes": notes if notes.strip() != "" else None
            }
            
            try:
                supabase.table("health_logs").insert(data_to_insert).execute()
                st.success("Dati registrati!")
                st.rerun()
            except Exception as e:
                st.error(f"Errore salvataggio: {e}")

    # --- 5. GRAFICI ---
    if not df.empty:
        st.subheader("📈 Andamento Parametri")
        cols_plot = ['oxygen', 'bpm', 'temperature', 'systolic', 'diastolic', 'weight']
        df_chart = df.copy()
        
        # Pulizia forzata dei tipi per Plotly
        valid_cols = []
        for col in cols_plot:
            if col in df_chart.columns:
                df_chart[col] = pd.to_numeric(df_chart[col], errors='coerce')
                # Aggiungi al grafico solo se la colonna ha almeno un valore non nullo
                if not df_chart[col].dropna().empty:
                    valid_cols.append(col)
        
        if valid_cols:
            fig = px.line(df_chart, x='created_at', y=valid_cols, markers=True)
            fig.update_layout(hovermode="x unified", legend_title_text='Parametri')
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Nessun dato presente nel diario.")

    # --- 6. ARCHIVIO REFERTI (NOME FILE AUTOMATICO) ---
    st.divider()
    st.header("📂 Archivio Referti PDF")
    
    with st.expander("📤 Carica nuovo referto"):
        data_doc = st.date_input("Data del documento", value=datetime.now())
        uploaded_file = st.file_uploader("Allega referto (PDF)", type="pdf")
        
        if st.button("Archivia Documento"):
            if uploaded_file:
                try:
                    nome_originale = uploaded_file.name
                    bytes_data = uploaded_file.read()
                    base64_encoded = base64.b64encode(bytes_data).decode('utf-8')
                    
                    supabase.table("referti_medici").insert({
                        "nome_referto": nome_originale,
                        "data_esame": str(data_doc),
                        "file_path": base64_encoded
                    }).execute()
                    
                    st.success(f"Documento '{nome_originale}' salvato!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Errore caricamento: {e}")
            else:
                st.warning("Seleziona un file prima di salvare.")

    # Visualizzazione lista referti
    try:
        res_ref = supabase.table("referti_medici").select("id, nome_referto, data_esame, file_path").order("data_esame", desc=True).execute()
        if res_ref.data:
            for ref in res_ref.data:
                c1, c2 = st.columns([4, 1])
                c1.write(f"📄 **{ref['nome_referto']}** — del {ref['data_esame']}")
                
                try:
                    pdf_bytes = base64.b64decode(ref['file_path'])
                    c2.download_button(
                        label="Scarica",
                        data=pdf_bytes,
                        file_name=ref['nome_referto'],
                        mime="application/pdf",
                        key=f"dl_{ref['id']}"
                    )
                except:
                    c2.write("⚠️ Errore file")
    except Exception as e:
        st.error(f"Errore caricamento referti: {e}")

    # --- 7. TABELLA STORICA ---
    if not df.empty:
        st.divider()
        st.subheader("📋 Registro Storico")
        df_display = df.copy()
        
        # Formattazione data leggibile
        df_display['created_at'] = df_display['created_at'].dt.strftime('%d/%m/%Y %H:%M')
        
        st.dataframe(
            df_display.sort_values(by='created_at', ascending=False), 
            use_container_width=True, 
            hide_index=True
        )
else:
    st.error("Configurazione database non trovata.")
