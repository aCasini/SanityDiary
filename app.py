import streamlit as st  # 1. IMPORT PRIMA DI TUTTO
import pandas as pd
from supabase import create_client
import plotly.express as px

# 2. CONFIGURAZIONE PAGINA (DEVE ESSERE IL PRIMO COMANDO ST)
st.set_page_config(page_title="Sanity Diary", page_icon="🩺", layout="wide")

# 3. CONFIGURAZIONE SUPABASE (SICURA) ---
# Streamlit cercherà queste chiavi nel file secrets.toml (in locale) 
# o nelle impostazioni della dashboard (in cloud)
try:
    URL = st.secrets["SUPABASE_URL"]
    KEY = st.secrets["SUPABASE_KEY"]
except KeyError:
    st.error("Configurazione non trovata! Assicurati di aver impostato i Secrets.")
    st.stop()

@st.cache_resource
def get_supabase():
    return create_client(URL, KEY)

supabase = get_supabase()

# 4. RESTO DEL CODICE (TITOLI, FORM, ECC.)
st.title("🩺 Sanity Diary: Diario Medico")
# ... tutto il resto del codice che ti ho dato prima ...
st.markdown("Registra e monitora i tuoi parametri vitali quotidianamente.")

# --- 3. SIDEBAR PER INSERIMENTO DATI ---
st.sidebar.header("➕ Nuova Misurazione")

with st.sidebar.form("medical_form", clear_on_submit=True):
    col1, col2 = st.columns(2)
    with col1:
        oxy = st.number_input("Ossigeno %", min_value=70, max_value=100, value=98)
        temp = st.number_input("Temp. °C", min_value=34.0, max_value=42.0, value=36.5, step=0.1)
    with col2:
        bpm = st.number_input("BPM (Battiti)", min_value=30, max_value=220, value=72)
        weight = st.number_input("Peso kg", min_value=30.0, max_value=250.0, value=70.0, step=0.1)
    
    notes = st.text_area("Note, sintomi o farmaci")
    
    submit = st.form_submit_button("Salva nel Diario")

if submit:
    new_data = {
        "oxygen": oxy,
        "bpm": bpm,
        "temperature": temp,
        "weight": weight,
        "notes": notes
    }
    try:
        supabase.table("health_logs").insert(new_data).execute()
        st.sidebar.success("✅ Misurazione registrata!")
        # Forza il refresh della pagina per aggiornare il grafico
        st.rerun()
    except Exception as e:
        st.sidebar.error(f"Errore nel salvataggio: {e}")

# --- 4. VISUALIZZAZIONE DATI E GRAFICI ---
st.subheader("📈 Andamento Parametri")

try:
    # Recupero dati da Supabase
    res = supabase.table("health_logs").select("*").order("created_at", desc=False).execute()
    
    if res.data and len(res.data) > 0:
        df = pd.DataFrame(res.data)
        
        # Gestione date: convertiamo in formato datetime di pandas
        df['created_at'] = pd.to_datetime(df['created_at'])
        
        # Creazione Grafico Multi-Linea
        fig = px.line(
            df, 
            x='created_at', 
            y=['oxygen', 'bpm', 'temperature'], 
            title="Analisi Storica: O2, BPM e Temperatura",
            labels={
                "created_at": "Data e Ora",
                "value": "Valore Misurato",
                "variable": "Parametro"
            },
            markers=True # Mostra i punti sulle linee
        )
        
        # Personalizzazione estetica del grafico
        fig.update_layout(hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)

        # Tabella Storica (mostrata con i dati più recenti in alto)
        st.subheader("📋 Storico Dati")
        df_display = df.sort_values(by='created_at', ascending=False).copy()
        # Formattiamo la data per la tabella
        df_display['created_at'] = df_display['created_at'].dt.strftime('%d/%m/%Y %H:%M')
        
        st.dataframe(
            df_display[['created_at', 'oxygen', 'bpm', 'temperature', 'weight', 'notes']], 
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("Nessun dato trovato. Inserisci la tua prima misurazione dalla barra laterale!")

except Exception as e:
    st.error(f"Errore nel caricamento dati: {e}")