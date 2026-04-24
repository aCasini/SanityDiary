import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
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
        password = st.text_input("Password:", type="password")
        if st.form_submit_button("Accedi"):
            if password == st.secrets.get("APP_PASSWORD"):
                st.session_state.authenticated = True
                st.rerun()
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
    except: return None

supabase = init_db()

if supabase:
    # --- 4. GESTIONE VISITE MEDICHE (BANNER IN ALTO) ---
    st.title("🩺 Sanity Diary")
    
    try:
        # Recuperiamo la visita non completata più vicina nel tempo
        res_visite = supabase.table("visite_mediche")\
            .select("*")\
            .eq("completata", False)\
            .order("data_visita", desc=False)\
            .execute()
        
        visite = res_visite.data
        if visite:
            prossima = visite[0]
            data_f = datetime.strptime(prossima['data_visita'], '%Y-%m-%d').strftime('%d/%m/%Y')
            
            # Creazione del Banner
            with st.container():
                col_txt, col_btn = st.columns([4, 1])
                col_txt.warning(f"🔔 **Promemoria:** {prossima['nome_visita']} il **{data_f}** presso **{prossima['luogo']}**")
                if col_btn.button("✅ Completata", key=f"v_{prossima['id']}"):
                    supabase.table("visite_mediche").update({"completata": True}).eq("id", prossima['id']).execute()
                    st.success("Visita completata!")
                    st.rerun()
    except Exception as e:
        st.error(f"Errore caricamento visite: {e}")

    # --- 5. LOGICA LOGS (Recupero dati esistente) ---
    try:
        res = supabase.table("health_logs").select("*").order("created_at", desc=False).execute()
        df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
        if not df.empty:
            df['created_at'] = pd.to_datetime(df['created_at'], format='ISO8601', utc=True)
            df['created_at'] = df['created_at'].dt.tz_localize(None).dt.floor('s')
    except: df = pd.DataFrame()

    # --- 6. SIDEBAR: AGGIUNTA MISURAZIONE & AGGIUNTA VISITA ---
    with st.sidebar:
        st.header("⚙️ Gestione")
        
        # Form Misurazioni (già presente)
        with st.expander("➕ Nuova Misurazione", expanded=False):
            with st.form("health_form", clear_on_submit=True):
                oxy = st.number_input("O2 %", 0, 100, 0)
                bpm = st.number_input("BPM", 0, 250, 0)
                temp = st.number_input("Temp °C", 0.0, 45.0, 0.0, 0.1)
                if st.form_submit_button("Salva Log"):
                    data = {"oxygen": oxy if oxy > 0 else None, "bpm": bpm if bpm > 0 else None, "temperature": temp if temp > 0 else None}
                    supabase.table("health_logs").insert(data).execute()
                    st.rerun()

        # NUOVO Form: Aggiunta Visita Medica
        with st.expander("📅 Programma Visita", expanded=False):
            with st.form("visita_form", clear_on_submit=True):
                n_visita = st.text_input("Nome Visita (es: Dentista)")
                d_visita = st.date_input("Data", value=datetime.now())
                l_visita = st.text_input("Luogo")
                if st.form_submit_button("Programma"):
                    if n_visita:
                        supabase.table("visite_mediche").insert({
                            "nome_visita": n_visita,
                            "data_visita": str(d_visita),
                            "luogo": l_visita
                        }).execute()
                        st.rerun()
                    else: st.warning("Inserisci il nome della visita")

        if st.button("Esci 🚪"):
            st.session_state.authenticated = False
            st.rerun()

    # --- 7. GRAFICI ---
    if not df.empty:
        st.subheader("📈 Andamento")
        cols_plot = [c for c in ['oxygen', 'bpm', 'temperature', 'systolic', 'diastolic', 'weight'] if c in df.columns]
        valid_cols = [c for c in cols_plot if not df[c].dropna().empty]
        if valid_cols:
            fig = px.line(df, x='created_at', y=valid_cols, markers=True)
            st.plotly_chart(fig, use_container_width=True)

    # --- 8. ARCHIVIO REFERTI ---
    st.divider()
    st.header("📂 Referti")
    with st.expander("📤 Carica PDF"):
        up_file = st.file_uploader("PDF", type="pdf")
        if st.button("Salva Referto") and up_file:
            b64 = base64.b64encode(up_file.read()).decode('utf-8')
            supabase.table("referti_medici").insert({"nome_referto": up_file.name, "data_esame": str(datetime.now().date()), "file_path": b64}).execute()
            st.rerun()

    # Visualizzazione lista referti (Base64)
    res_ref = supabase.table("referti_medici").select("*").order("data_esame", desc=True).execute()
    for ref in (res_ref.data or []):
        c1, c2 = st.columns([4, 1])
        c1.write(f"📄 **{ref['nome_referto']}** — {ref['data_esame']}")
        c2.download_button("Download", base64.b64decode(ref['file_path']), file_name=ref['nome_referto'], key=f"dl_{ref['id']}")

    # --- 9. TABELLA STORICA ---
    if not df.empty:
        st.divider()
        st.subheader("📋 Registro Storico")
        df_display = df.copy()
        df_display['created_at'] = df_display['created_at'].dt.strftime('%d/%m/%Y %H:%M')
        st.dataframe(df_display.sort_values(by='created_at', ascending=False), use_container_width=True, hide_index=True)
