import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
from datetime import datetime, timedelta
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
            else: st.error("Password errata 🚫")
    return False

if not check_password():
    st.stop()

# --- 3. CONNESSIONE SUPABASE ---
@st.cache_resource
def init_db():
    try: return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    except: return None

supabase = init_db()

# --- FUNZIONE LOGICA IA / TREND ---
def analyze_trends(df):
    if len(df) < 2:
        return None, []
    
    insights = []
    # Prendiamo l'ultima e la penultima misurazione
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    # Analisi Pressione
    if last['systolic'] and last['systolic'] > 140:
        insights.append("⚠️ **Pressione Sistolica Alta**: L'ultimo valore rilevato è sopra la norma (140 mmHg).")
    
    # Analisi Ossigeno
    if last['oxygen'] and last['oxygen'] < 94:
        insights.append("🚩 **Livello Ossigeno Critico**: Rilevato valore sotto il 94%. Consulta un medico se persiste.")

    # Analisi Trend Peso
    if last['weight'] and prev['weight']:
        diff_peso = last['weight'] - prev['weight']
        if abs(diff_peso) > 1.5:
            insights.append(f"⚖️ **Variazione Peso Rapida**: Hai avuto una variazione di {diff_peso:.1f}kg dall'ultima volta.")

    return last, insights

if supabase:
    # --- 4. BANNER VISITE ---
    st.title("🩺 Sanity Diary Intelligence")
    try:
        res_v = supabase.table("visite_mediche").select("*").eq("completata", False).order("data_visita").execute()
        if res_v.data:
            p = res_v.data[0]
            c_v1, c_v2 = st.columns([4, 1])
            c_v1.warning(f"🔔 **Prossima Visita:** {p['nome_visita']} - {p['data_visita']} ({p['luogo']})")
            if c_v2.button("✅ Fatto", key=f"v_{p['id']}"):
                supabase.table("visite_mediche").update({"completata": True}).eq("id", p['id']).execute()
                st.rerun()
    except: pass

    # --- 5. RECUPERO DATI ---
    try:
        res = supabase.table("health_logs").select("*").order("created_at", desc=False).execute()
        df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
        if not df.empty:
            df['created_at'] = pd.to_datetime(df['created_at'], format='ISO8601', utc=True).dt.tz_localize(None).dt.floor('s')
    except: df = pd.DataFrame()

    # --- 6. INTELLIGENCE DASHBOARD (KPI & TRENDS) ---
    if not df.empty:
        st.subheader("📊 Health Insights (IA)")
        last_val, alert_list = analyze_trends(df)
        
        # Righe di metriche per i trend
        m1, m2, m3, m4 = st.columns(4)
        
        def get_delta(col):
            if len(df) > 1:
                val = df[col].iloc[-1]
                old = df[col].iloc[-2]
                if pd.notnull(val) and pd.notnull(old):
                    return f"{val - old:.1f}"
            return None

        if 'oxygen' in df.columns:
            m1.metric("Ossigeno", f"{df['oxygen'].iloc[-1]:.0f}%", get_delta('oxygen'))
        if 'bpm' in df.columns:
            m2.metric("Battito (BPM)", f"{df['bpm'].iloc[-1]:.0f}", get_delta('bpm'), delta_color="inverse")
        if 'systolic' in df.columns:
            m3.metric("Press. Max", f"{df['systolic'].iloc[-1]:.0f}", get_delta('systolic'), delta_color="inverse")
        if 'weight' in df.columns:
            m4.metric("Peso", f"{df['weight'].iloc[-1]:.1f} kg", get_delta('weight'), delta_color="inverse")

        # Visualizzazione messaggi IA
        for alert in alert_list:
            st.info(alert)

    # --- 7. SIDEBAR INPUT ---
    with st.sidebar:
        st.header("⚙️ Gestione")
        with st.expander("➕ Nuova Misurazione"):
            with st.form("h_form", clear_on_submit=True):
                o, b, t = st.number_input("O2 %", 0, 100, 0), st.number_input("BPM", 0, 250, 0), st.number_input("Temp °C", 0.0, 45.0, 0.0, 0.1)
                s, d, w = st.number_input("Sistolica", 0, 250, 0), st.number_input("Diastolica", 0, 150, 0), st.number_input("Peso kg", 0.0, 300.0, 0.0, 0.1)
                n = st.text_area("Note")
                if st.form_submit_button("Salva"):
                    data = {"oxygen": o if o>0 else None, "bpm": b if b>0 else None, "temperature": t if t>0 else None,
                            "systolic": s if s>0 else None, "diastolic": d if d>0 else None, "weight": w if w>0 else None, "notes": n if n.strip() else None}
                    supabase.table("health_logs").insert(data).execute()
                    st.rerun()

        with st.expander("📅 Programma Visita"):
            with st.form("v_form", clear_on_submit=True):
                nv, dv, lv = st.text_input("Nome Visita"), st.date_input("Data"), st.text_input("Luogo")
                if st.form_submit_button("Programma"):
                    if nv: supabase.table("visite_mediche").insert({"nome_visita": nv, "data_visita": str(dv), "luogo": lv}).execute()
                    st.rerun()

        if st.button("Logout 🚪", use_container_width=True):
            st.session_state.authenticated = False
            st.rerun()

    # --- 8. GRAFICI ---
    if not df.empty:
        st.divider()
        cols_plot = ['oxygen', 'bpm', 'temperature', 'systolic', 'diastolic', 'weight']
        valid_cols = [c for c in cols_plot if c in df.columns and not df[c].dropna().empty]
        if valid_cols:
            fig = px.line(df, x='created_at', y=valid_cols, markers=True)
            st.plotly_chart(fig, use_container_width=True)

    # --- 9. REFERTI & TABELLA ---
    st.divider()
    c_ref, c_tab = st.columns([1, 1])
    
    with c_ref:
        st.header("📂 Referti")
        up_file = st.file_uploader("Carica PDF", type="pdf")
        if st.button("Salva PDF") and up_file:
            b64 = base64.b64encode(up_file.read()).decode('utf-8')
            supabase.table("referti_medici").insert({"nome_referto": up_file.name, "data_esame": str(datetime.now().date()), "file_path": b64}).execute()
            st.rerun()
        
        try:
            res_r = supabase.table("referti_medici").select("*").order("data_esame", desc=True).execute()
            for r in res_r.data:
                st.download_button(f"📄 {r['nome_referto']}", base64.b64decode(r['file_path']), file_name=r['nome_referto'], key=f"d_{r['id']}")
        except: pass

    with c_tab:
        st.header("📋 Registro")
        if not df.empty:
            df_disp = df.copy()
            df_disp['Data'] = df_disp['created_at'].dt.strftime('%d/%m %H:%M')
            cols_final = ["Data", "oxygen", "bpm", "temperature", "weight", "systolic", "diastolic", "notes"]
            st.dataframe(df_disp[[c for c in cols_final if c in df_disp.columns]].sort_values(by='Data', ascending=False), hide_index=True)
