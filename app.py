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
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if st.session_state.authenticated:
        return True

    st.title("🔐 Accesso Riservato")
    with st.form("login_form"):
        password = st.text_input("Inserisci la password:", type="password")
        submit = st.form_submit_button("Accedi")
        if submit:
            if password == st.secrets["APP_PASSWORD"]:
                st.session_state.authenticated = True
                st.experimental_rerun()
            else:
                st.error("Password errata 🚫")
    return False

if not check_password():
    st.stop()

# --- 3. CONNESSIONE SUPABASE ---
@st.cache_resource
def init_db():
    try:
        return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    except Exception as e:
        st.error(f"Errore connessione: {e}")
        return None

supabase = init_db()

# --- 4. LOGICA PRINCIPALE ---
col_title, col_logout = st.columns([5, 1])
with col_title:
    st.title("🩺 Sanity Diary")
with col_logout:
    if st.button("Esci 🚪"):
        st.session_state.authenticated = False
        st.experimental_rerun()

if supabase:
    # Recupero dati
    res = supabase.table("health_logs").select("*").order("created_at", desc=False).execute()
    df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
    if not df.empty:
        df['created_at'] = pd.to_datetime(df['created_at'], errors='coerce', utc=True)

    # --- SIDEBAR: NUOVA MISURAZIONE (CON GESTIONE NULL) ---
    with st.sidebar.form("medical_form", clear_on_submit=True):
        st.header("➕ Nuova Misurazione")
        st.write("Lascia a 0 i valori che non vuoi registrare.")
        
        # Usiamo 0.0 o 0 come valore "vuoto"
        oxy = st.number_input("Ossigeno %", 0, 100, 0)
        bpm = st.number_input("BPM", 0, 200, 0)
        temp = st.number_input("Temperatura °C", 0.0, 45.0, 0.0, 0.1)
        sys = st.number_input("Pressione Max", 0, 250, 0)
        dia = st.number_input("Pressione Min", 0, 150, 0)
        weight = st.number_input("Peso kg", 0.0, 300.0, 0.0, 0.1)
        notes = st.text_area("Note")
        
        if st.form_submit_button("Salva nel Diario"):
            # FIX: Se il valore è 0, lo trasformiamo in None (NULL nel DB)
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
                st.success("Dati salvati!")
                st.experimental_rerun()
            except Exception as e:
                st.error(f"Errore: {e}")

    # --- 5. GRAFICI ---
    if not df.empty:
        st.subheader("📈 Andamento Parametri")
        cols_plot = ['oxygen', 'bpm', 'temperature', 'systolic', 'diastolic', 'weight']
        df_chart = df.copy()
        valid_cols = []
        for col in cols_plot:
            if col in df_chart.columns:
                # Plotly ignorerà automaticamente i valori None (punti mancanti nel grafico)
                df_chart[col] = pd.to_numeric(df_chart[col], errors='coerce')
                if not df_chart[col].dropna().empty:
                    valid_cols.append(col)
        
        if valid_cols:
            fig = px.line(df_chart, x='created_at', y=valid_cols, markers=True)
            fig.update_layout(hovermode="x unified")
            st.plotly_chart(fig, use_container_width=True)

    # --- 6. ARCHIVIO REFERTI ---
    st.divider()
    st.header("📂 Archivio Referti PDF")
    with st.expander("📤 Carica nuovo referto"):
        data_doc = st.date_input("Data esame", value=datetime.now())
        uploaded_file = st.file_uploader("Seleziona PDF", type="pdf")
        if st.button("Salva Referto"):
            if uploaded_file:
                bytes_data = uploaded_file.read()
                base64_encoded = base64.b64encode(bytes_data).decode('utf-8')
                supabase.table("referti_medici").insert({
                    "nome_referto": uploaded_file.name,
                    "data_esame": str(data_doc),
                    "file_path": base64_encoded
                }).execute()
                st.success("Referto salvato!")
                st.experimental_rerun()

    # Lista Referti
    try:
        res_ref = supabase.table("referti_medici").select("id, nome_referto, data_esame, file_path").order("data_esame", desc=True).execute()
        if res_ref.data:
            for ref in res_ref.data:
                c1, c2 = st.columns([4, 1])
                c1.write(f"📄 **{ref['nome_referto']}** — {ref['data_esame']}")
                pdf_content = base64.b64decode(ref['file_path'])
                c2.download_button("Scarica", data=pdf_content, file_name=ref['nome_referto'], key=f"btn_{ref['id']}")
    except:
        pass

    # --- 7. TABELLA STORICA ---
    if not df.empty:
        st.divider()
        st.subheader("📋 Registro Storico")
        df_display = df.copy()
        df_display['created_at'] = df_display['created_at'].dt.strftime('%d/%m/%Y %H:%M')
        # La tabella mostrerà 'None' o vuoto per i valori NULL
        st.dataframe(df_display.sort_values(by='created_at', ascending=False), use_container_width=True, hide_index=True)
