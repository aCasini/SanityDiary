import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import base64

# --- 1. CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Sanity Diary Intelligence", page_icon="🩺", layout="wide")

# --- 2. AUTH ---
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if st.session_state.authenticated: return True
    st.title("🔐 Accesso Riservato")
    with st.form("login_form"):
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
    try: return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    except: return None

supabase = init_db()

# --- FUNZIONI DI ANALISI ---
def analyze_trends(df):
    if len(df) < 2: return None, []
    insights = []
    last, prev = df.iloc[-1], df.iloc[-2]
    if last['systolic'] and last['systolic'] > 140:
        insights.append("⚠️ **Pressione Sistolica Alta**: Valore sopra 140 mmHg.")
    if last['oxygen'] and last['oxygen'] < 94:
        insights.append("🚩 **Ossigeno Critico**: Rilevato valore sotto il 94%.")
    return last, insights

if supabase:
    # --- RECUPERO DATI ---
    try:
        res = supabase.table("health_logs").select("*").order("created_at", desc=False).execute()
        df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
        if not df.empty:
            df['created_at'] = pd.to_datetime(df['created_at'], format='ISO8601', utc=True).dt.tz_localize(None).dt.floor('s')
    except: df = pd.DataFrame()

    st.title("🩺 Sanity Diary Intelligence")

    # --- DASHBOARD INTELLIGENTE ---
    if not df.empty:
        # Metriche in alto
        m1, m2, m3, m4 = st.columns(4)
        def get_delta(col):
            if len(df) > 1 and pd.notnull(df[col].iloc[-1]) and pd.notnull(df[col].iloc[-2]):
                return f"{df[col].iloc[-1] - df[col].iloc[-2]:.1f}"
            return None

        m1.metric("Ossigeno", f"{df['oxygen'].iloc[-1] if pd.notnull(df['oxygen'].iloc[-1]) else 0:.0f}%", get_delta('oxygen'))
        m2.metric("BPM", f"{df['bpm'].iloc[-1] if pd.notnull(df['bpm'].iloc[-1]) else 0:.0f}", get_delta('bpm'), delta_color="inverse")
        m3.metric("Press. Max", f"{df['systolic'].iloc[-1] if pd.notnull(df['systolic'].iloc[-1]) else 0:.0f}", get_delta('systolic'), delta_color="inverse")
        m4.metric("Peso", f"{df['weight'].iloc[-1] if pd.notnull(df['weight'].iloc[-1]) else 0:.1f}kg", get_delta('weight'), delta_color="inverse")

        # Insights testuali
        _, alerts = analyze_trends(df)
        for a in alerts: st.info(a)

        # --- SEZIONE CORRELAZIONE DI PEARSON ---
        st.divider()
        col_graph, col_corr = st.columns([2, 1])

        with col_graph:
            st.subheader("📈 Grafico Temporale")
            cols_plot = ['oxygen', 'bpm', 'temperature', 'systolic', 'diastolic', 'weight']
            valid_cols = [c for c in cols_plot if c in df.columns and not df[c].dropna().empty]
            fig = px.line(df, x='created_at', y=valid_cols, markers=True)
            st.plotly_chart(fig, use_container_width=True)

        with col_corr:
            st.subheader("🧬 Analisi Correlazioni")
            # Calcolo correlazione di Pearson
            corr_df = df[valid_cols].corr(method='pearson')
            
            # Heatmap con Plotly
            fig_corr = px.imshow(corr_df, 
                                text_auto=".2f", 
                                aspect="auto",
                                color_continuous_scale='RdBu_r', 
                                range_color=[-1, 1],
                                labels=dict(color="Pearson r"))
            fig_corr.update_layout(margin=dict(l=20, r=20, t=20, b=20))
            st.plotly_chart(fig_corr, use_container_width=True)
            
            # Messaggio interpretativo
            if len(valid_cols) > 1:
                strong_corr = corr_df.unstack().sort_values(ascending=False)
                # Filtriamo i duplicati (r=1.0) e prendiamo la più alta
                strongest = strong_corr[strong_corr < 0.99].head(1)
                if not strongest.empty:
                    v1, v2 = strongest.index[0]
                    st.write(f"💡 **Nota:** C'è un legame tra **{v1}** e **{v2}** ($r={strongest.values[0]:.2f}$).")

    # --- SIDEBAR & ALTRI ---
    with st.sidebar:
        st.header("⚙️ Inserimento")
        with st.expander("➕ Misura"):
            with st.form("h_form", clear_on_submit=True):
                o, b, t = st.number_input("O2%", 0, 100, 0), st.number_input("BPM", 0, 250, 0), st.number_input("Temp°C", 0.0, 45.0, 0.0, 0.1)
                s, d, w = st.number_input("Sistolica", 0, 250, 0), st.number_input("Diastolica", 0, 150, 0), st.number_input("Peso kg", 0.0, 300.0, 0.0, 0.1)
                n = st.text_area("Note")
                if st.form_submit_button("Salva"):
                    data = {"oxygen":o if o>0 else None, "bpm":b if b>0 else None, "temperature":t if t>0 else None,
                            "systolic":s if s>0 else None, "diastolic":d if d>0 else None, "weight":w if w>0 else None, "notes":n if n.strip() else None}
                    supabase.table("health_logs").insert(data).execute()
                    st.rerun()
        
        with st.expander("📅 Visita"):
            with st.form("v_form", clear_on_submit=True):
                nv, dv, lv = st.text_input("Visita"), st.date_input("Data"), st.text_input("Luogo")
                if st.form_submit_button("Ok"):
                    if nv: supabase.table("visite_mediche").insert({"nome_visita":nv, "data_visita":str(dv), "luogo":lv}).execute()
                    st.rerun()

        if st.button("Logout 🚪", use_container_width=True):
            st.session_state.authenticated = False
            st.rerun()

    # --- REFERTI E TABELLA (In fondo) ---
    st.divider()
    t1, t2 = st.tabs(["📂 Archivio Referti", "📋 Registro Storico"])
    with t1:
        up = st.file_uploader("Carica PDF", type="pdf")
        if st.button("Archivia") and up:
            b64 = base64.b64encode(up.read()).decode('utf-8')
            supabase.table("referti_medici").insert({"nome_referto":up.name, "data_esame":str(datetime.now().date()), "file_path":b64}).execute()
            st.rerun()
        res_r = supabase.table("referti_medici").select("*").order("data_esame", desc=True).execute()
        for r in (res_r.data or []):
            st.download_button(f"📄 {r['nome_referto']}", base64.b64decode(r['file_path']), file_name=r['nome_referto'], key=f"d_{r['id']}")

    with t2:
        if not df.empty:
            df_disp = df.copy()
            df_disp['Data'] = df_disp['created_at'].dt.strftime('%d/%m %H:%M')
            cols_order = ["Data", "oxygen", "bpm", "temperature", "weight", "systolic", "diastolic", "notes"]
            st.dataframe(df_disp[[c for c in cols_order if c in df_disp.columns]].sort_values(by='Data', ascending=False), hide_index=True)
