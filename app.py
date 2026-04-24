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
        password = st.text_input("Inserisci la password di sicurezza:", type="password")
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
    except:
        return None

supabase = init_db()

if supabase:
    # --- 4. GESTIONE VISITE E PROMEMORIA (BANNER) ---
    st.title("🩺 Sanity Diary")
    
    try:
        res_visite = supabase.table("visite_mediche")\
            .select("*")\
            .eq("completata", False)\
            .order("data_visita", desc=False)\
            .execute()
        
        if res_visite.data:
            prossima = res_visite.data[0]
            data_f = datetime.strptime(prossima['data_visita'], '%Y-%m-%d').strftime('%d/%m/%Y')
            
            with st.container():
                col_txt, col_btn = st.columns([4, 1])
                col_txt.warning(f"🔔 **PROMEMORIA:** {prossima['nome_visita']} il **{data_f}** — Luogo: **{prossima['luogo']}**")
                if col_btn.button("✅ Segna come completata", key=f"vis_{prossima['id']}"):
                    supabase.table("visite_mediche").update({"completata": True}).eq("id", prossima['id']).execute()
                    st.success("Ottimo! Visita completata.")
                    st.rerun()
    except:
        pass

    # --- 5. RECUPERO DATI SALUTE ---
    try:
        res = supabase.table("health_logs").select("*").order("created_at", desc=False).execute()
        df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
        if not df.empty:
            # Fix definitivo per le date ISO8601
            df['created_at'] = pd.to_datetime(df['created_at'], format='ISO8601', utc=True)
            df['created_at'] = df['created_at'].dt.tz_localize(None).dt.floor('s')
    except:
        df = pd.DataFrame()

    # --- 6. SIDEBAR: GESTIONE INPUT ---
    with st.sidebar:
        st.header("⚙️ Pannello Controllo")
        
        # Inserimento Misurazioni
        with st.expander("➕ Nuova Misurazione", expanded=False):
            with st.form("health_form", clear_on_submit=True):
                oxy = st.number_input("Ossigeno %", 0, 100, 0)
                bpm = st.number_input("Battito (BPM)", 0, 250, 0)
                temp = st.number_input("Temperatura °C", 0.0, 45.0, 0.0, 0.1)
                sys = st.number_input("Pressione Max (Sistolica)", 0, 250, 0)
                dia = st.number_input("Pressione Min (Diastolica)", 0, 150, 0)
                weight = st.number_input("Peso (kg)", 0.0, 300.0, 0.0, 0.1)
                notes = st.text_area("Note/Sintomi")
                
                if st.form_submit_button("Salva Misurazione"):
                    data_to_insert = {
                        "oxygen": oxy if oxy > 0 else None,
                        "bpm": bpm if bpm > 0 else None,
                        "temperature": temp if temp > 0 else None,
                        "systolic": sys if sys > 0 else None,
                        "diastolic": dia if dia > 0 else None,
                        "weight": weight if weight > 0 else None,
                        "notes": notes if notes.strip() != "" else None
                    }
                    supabase.table("health_logs").insert(data_to_insert).execute()
                    st.rerun()

        # Inserimento Appuntamenti
        with st.expander("📅 Programma Visita", expanded=False):
            with st.form("visita_form", clear_on_submit=True):
                n_visita = st.text_input("Specialista / Tipo Visita")
                d_visita = st.date_input("Data", value=datetime.now())
                l_visita = st.text_input("Ospedale / Studio")
                if st.form_submit_button("Salva Appuntamento"):
                    if n_visita:
                        supabase.table("visite_mediche").insert({
                            "nome_visita": n_visita,
                            "data_visita": str(d_visita),
                            "luogo": l_visita
                        }).execute()
                        st.rerun()
                    else:
                        st.warning("Inserisci almeno il nome della visita.")

        st.divider()
        if st.button("Esci (Logout) 🚪", use_container_width=True):
            st.session_state.authenticated = False
            st.rerun()

    # --- 7. VISUALIZZAZIONE GRAFICI ---
    if not df.empty:
        st.subheader("📈 Andamento Parametri")
        cols_plot = ['oxygen', 'bpm', 'temperature', 'systolic', 'diastolic', 'weight']
        valid_cols = [c for c in cols_plot if c in df.columns and not df[c].dropna().empty]
        
        if valid_cols:
            fig = px.line(df, x='created_at', y=valid_cols, markers=True, 
                         labels={"value": "Valore", "created_at": "Data", "variable": "Parametro"})
            fig.update_layout(hovermode="x unified")
            st.plotly_chart(fig, use_container_width=True)

    # --- 8. ARCHIVIO E VISUALIZZATORE PDF ---
    st.divider()
    st.header("📂 Archivio Referti")
    
    with st.expander("📤 Carica nuovo PDF"):
        up_file = st.file_uploader("Seleziona il file referto", type="pdf")
        if st.button("Archivia PDF") and up_file:
            b64_pdf = base64.b64encode(up_file.read()).decode('utf-8')
            supabase.table("referti_medici").insert({
                "nome_referto": up_file.name,
                "data_esame": str(datetime.now().date()),
                "file_path": b64_pdf
            }).execute()
            st.success("File caricato correttamente!")
            st.rerun()

    # Lista Referti con opzione "Visualizza"
    try:
        res_ref = supabase.table("referti_medici").select("*").order("data_esame", desc=True).execute()
        if res_ref.data:
            for ref in res_ref.data:
                c1, c2, c3 = st.columns([3, 1, 1])
                c1.write(f"📄 **{ref['nome_referto']}** — del {ref['data_esame']}")
                
                # Download
                pdf_data = base64.b64decode(ref['file_path'])
                c2.download_button("Scarica ⬇️", pdf_data, file_name=ref['nome_referto'], key=f"dl_{ref['id']}")
                
                # Visualizza
                if c3.button("Visualizza 👁️", key=f"v_{ref['id']}"):
                    st.session_state.pdf_view = ref['file_path']
                    st.session_state.pdf_title = ref['nome_referto']

            # Area di visualizzazione PDF (appare solo se cliccato)
            if "pdf_view" in st.session_state:
                st.divider()
                st.subheader(f"Anteprima: {st.session_state.pdf_title}")
                pdf_display = f'<iframe src="data:application/pdf;base64,{st.session_state.pdf_view}" width="100%" height="800" type="application/pdf"></iframe>'
                st.markdown(pdf_display, unsafe_allow_html=True)
                if st.button("Chiudi Anteprima ❌"):
                    del st.session_state.pdf_view
                    st.rerun()
    except:
        st.info("Nessun referto presente.")

    # --- 9. TABELLA STORICA ---
    if not df.empty:
        st.divider()
        st.subheader("📋 Registro Storico")
        df_display = df.copy()
        df_display['created_at'] = df_display['created_at'].dt.strftime('%d/%m/%Y %H:%M')
        st.dataframe(df_display.sort_values(by='created_at', ascending=False), use_container_width=True, hide_index=True)

else:
    st.error("Connessione a Supabase non riuscita. Controlla i Secrets.")
