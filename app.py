import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
from datetime import datetime
import base64
from fpdf import FPDF
import streamlit.components.v1 as components

# --- 1. CONFIGURAZIONE PAGINA & PWA ---
st.set_page_config(page_title="Sanity Diary Intelligence", page_icon="🩺", layout="wide")

# Iniezione Meta tag per PWA (richiede i file manifest.json e sw.js nella stessa cartella)
def inject_pwa():
    pwa_html = """
    <link rel="manifest" href="./manifest.json">
    <script>
      if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('./sw.js');
      }
    </script>
    """
    components.html(pwa_html, height=0)

inject_pwa()

# --- 2. AUTHENTICATION ---
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if st.session_state.authenticated: return True
    st.title("🔐 Accesso Riservato")
    with st.form("login_form"):
        password = st.text_input("Inserisci la Password:", type="password")
        if st.form_submit_button("Accedi"):
            if password == st.secrets.get("APP_PASSWORD"):
                st.session_state.authenticated = True
                st.rerun()
            else: st.error("Password errata")
    return False

if not check_password(): st.stop()

# --- 3. CONNESSIONE DATABASE ---
@st.cache_resource
def init_db():
    try:
        return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    except Exception as e:
        st.error(f"Errore di connessione: {e}")
        return None

supabase = init_db()

# --- 4. FUNZIONI DI ANALISI E EXPORT PDF ---
def get_ai_insights(df):
    if df.empty: return [], ""
    recent = df.sort_values(by='created_at', ascending=True).tail(10)
    alerts = []
    if 'systolic' in recent.columns and (recent['systolic'] > 140).any():
        alerts.append("Episodi di pressione sistolica alta (>140) rilevati di recente.")
    if 'oxygen' in recent.columns and (recent['oxygen'] < 94).any():
        alerts.append("Cali di ossigenazione sotto il 94% rilevati di recente.")
    
    cols_stats = ['oxygen', 'bpm', 'temperature', 'systolic', 'diastolic', 'weight']
    valid_cols = [c for c in cols_stats if c in df.columns and not df[c].dropna().empty]
    correlation_str = ""
    if len(valid_cols) > 1:
        corr_matrix = df[valid_cols].corr()
        strong = corr_matrix.unstack().sort_values(ascending=False)
        top = strong[strong < 0.98].head(1)
        if not top.empty:
            v1, v2 = top.index[0]
            correlation_str = f"L'analisi IA indica un legame statistico (r={top.values[0]:.2f}) tra {v1.capitalize()} e {v2.capitalize()}."
    return alerts, correlation_str

def export_pdf(df):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 18)
    pdf.cell(0, 10, "Sanity Diary - Report Clinico Intelligente", ln=True, align="C")
    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 10, f"Generato il: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align="C")
    pdf.ln(5)

    # Analisi IA (Banner Azzurro)
    pdf.set_fill_color(230, 242, 255)
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, " Analisi Intelligente e Trend", ln=True, fill=True)
    pdf.set_font("Arial", "", 11)
    alerts, corr_text = get_ai_insights(df)
    if alerts:
        for a in alerts: pdf.multi_cell(0, 8, f"  - {a}")
    else: pdf.cell(0, 8, "  - Nessuna anomalia critica rilevata nei dati recenti.", ln=True)
    if corr_text:
        pdf.ln(2); pdf.set_font("Arial", "I", 11)
        pdf.multi_cell(0, 8, f"Insight IA: {corr_text}")

    # Medie Storiche
    pdf.ln(5); pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, "Medie Storiche di Periodo", ln=True)
    pdf.set_font("Arial", "", 12)
    for col in ['oxygen', 'bpm', 'temperature', 'systolic', 'weight']:
        if col in df.columns and pd.notnull(df[col].mean()):
            pdf.cell(0, 8, f"- {col.capitalize()}: {df[col].mean():.2f}", ln=True)

    # Tabella Dati
    pdf.ln(10); pdf.set_font("Arial", "B", 10); pdf.set_fill_color(240, 240, 240)
    headers = [("Data Ora", 35), ("O2%", 15), ("BPM", 15), ("Temp", 15), ("Press", 30), ("Peso", 20), ("Note", 60)]
    for h, w in headers: pdf.cell(w, 10, h, 1, 0, "C", True)
    pdf.ln()
    pdf.set_font("Arial", "", 9)
    for _, row in df.sort_values(by='created_at', ascending=False).head(40).iterrows():
        pdf.cell(35, 8, row['created_at'].strftime('%d/%m/%y %H:%M'), 1)
        pdf.cell(15, 8, str(row['oxygen']) if pd.notnull(row['oxygen']) else "-", 1, 0, "C")
        pdf.cell(15, 8, str(row['bpm']) if pd.notnull(row['bpm']) else "-", 1, 0, "C")
        pdf.cell(15, 8, str(row['temperature']) if pd.notnull(row['temperature']) else "-", 1, 0, "C")
        p_s = f"{int(row['systolic'])}/{int(row['diastolic'])}" if pd.notnull(row['systolic']) else "-"
        pdf.cell(30, 8, p_s, 1, 0, "C")
        pdf.cell(20, 8, f"{row['weight']:.1f}" if pd.notnull(row['weight']) else "-", 1, 0, "C")
        pdf.cell(60, 8, str(row['notes'])[:35] if pd.notnull(row['notes']) else "-", 1)
        pdf.ln()
    return bytes(pdf.output())

# --- 5. LOGICA APP ---
if supabase:
    # Fetch dati salute
    try:
        res = supabase.table("health_logs").select("*").order("created_at", desc=False).execute()
        df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
        if not df.empty:
            df['created_at'] = pd.to_datetime(df['created_at'], format='ISO8601', utc=True).dt.tz_localize(None).dt.floor('s')
    except: df = pd.DataFrame()

    st.title("🩺 Sanity Diary Intelligence")

    # Banner Visite Imminenti
    try:
        res_v = supabase.table("visite_mediche").select("*").eq("completata", False).order("data_visita").execute()
        if res_v.data:
            p = res_v.data[0]
            st.warning(f"📅 **Prossima Visita:** {p['nome_visita']} il {p['data_visita']} presso {p['luogo']}")
    except: pass

    if not df.empty:
        # Dashboard Metriche con Delta
        m1, m2, m3, m4 = st.columns(4)
        def calc_delta(col):
            if len(df) >= 2:
                l, prev = df[col].iloc[-1], df[col].iloc[-2]
                if pd.notnull(l) and pd.notnull(prev): return round(float(l - prev), 2)
            return None
        m1.metric("Ossigeno", f"{df['oxygen'].iloc[-1]:.0f}%", calc_delta('oxygen'))
        m2.metric("BPM", f"{df['bpm'].iloc[-1]:.0f}", calc_delta('bpm'), delta_color="inverse")
        m3.metric("Press. Max", f"{df['systolic'].iloc[-1]:.0f}", calc_delta('systolic'), delta_color="inverse")
        m4.metric("Peso", f"{df['weight'].iloc[-1]:.1f}kg", calc_delta('weight'))

        st.divider()
        t_graph, t_pearson, t_visite, t_ref, t_reg = st.tabs(["📈 Trend", "🧬 Pearson IA", "📅 Visite", "📂 Referti", "📋 Registro"])

        with t_graph:
            st.subheader("Visualizzazione Storica")
            valid_cols = [c for c in ['oxygen', 'bpm', 'temperature', 'systolic', 'diastolic', 'weight'] if c in df.columns]
            st.plotly_chart(px.line(df, x='created_at', y=valid_cols, markers=True, template="plotly_white"), use_container_width=True)

        with t_pearson:
            st.subheader("🧬 Studio delle Correlazioni Intelligenti")
            c_info, c_map = st.columns([1, 2])
            alerts, corr_text = get_ai_insights(df)
            with c_info:
                if corr_text: st.info(f"💡 {corr_text}")
                if alerts: st.warning("⚠️ Alert:\n" + "\n".join([f"- {a}" for a in alerts]))
            with c_map:
                if len(valid_cols) > 1:
                    st.plotly_chart(px.imshow(df[valid_cols].corr(), text_auto=".2f", color_continuous_scale='RdBu_r'), use_container_width=True)

        with t_visite:
            st.subheader("Gestione Appuntamenti")
            cv1, cv2 = st.columns([1, 2])
            with cv1:
                with st.form("v_form", clear_on_submit=True):
                    n_v = st.text_input("Tipo Visita")
                    d_v = st.date_input("Data")
                    l_v = st.text_input("Luogo")
                    if st.form_submit_button("Salva"):
                        supabase.table("visite_mediche").insert({"nome_visita":n_v, "data_visita":str(d_v), "luogo":l_v, "completata":False}).execute()
                        st.rerun()
            with cv2:
                res_v_all = supabase.table("visite_mediche").select("*").order("data_visita").execute()
                for v in (res_v_all.data or []):
                    col_a, col_b = st.columns([4, 1])
                    status = "✅" if v['completata'] else "⏳"
                    col_a.write(f"{status} **{v['data_visita']}**: {v['nome_visita']} ({v['luogo']})")
                    if not v['completata'] and col_b.button("Fatto", key=f"f_{v['id']}"):
                        supabase.table("visite_mediche").update({"completata":True}).eq("id", v['id']).execute()
                        st.rerun()

        with t_ref:
            up = st.file_uploader("Carica PDF", type="pdf")
            if st.button("Salva Referto") and up:
                b64 = base64.b64encode(up.read()).decode('utf-8')
                supabase.table("referti_medici").insert({"nome_referto":up.name, "data_esame":str(datetime.now().date()), "file_path":b64}).execute()
                st.rerun()
            res_r = supabase.table("referti_medici").select("*").order("data_esame", desc=True).execute()
            for r in (res_r.data or []):
                st.download_button(f"📄 {r['nome_referto']}", base64.b64decode(r['file_path']), file_name=r['nome_referto'], key=f"r_{r['id']}")

        with t_reg:
            c_tab, c_exp = st.columns([3, 1])
            with c_exp:
                st.write("🖨️ **Export Medico**")
                try:
                    pdf_data = export_pdf(df)
                    st.download_button("Genera Report PDF", data=pdf_data, file_name="report_clinico.pdf", mime="application/pdf", use_container_width=True)
                except Exception as e: st.error(f"Errore: {e}")
            with c_tab:
                df_s = df.sort_values(by='created_at', ascending=False).copy()
                df_s['Data'] = df_s['created_at'].dt.strftime('%d/%m/%Y %H:%M')
                st.dataframe(df_s[["Data", "oxygen", "bpm", "temperature", "weight", "systolic", "diastolic", "notes"]], use_container_width=True, hide_index=True)

    with st.sidebar:
        st.header("⚙️ Nuova Misura")
        with st.form("h_form", clear_on_submit=True):
            o, b, t = st.number_input("O2%", 0), st.number_input("BPM", 0), st.number_input("Temp °C", 0.0, format="%.1f")
            s, d, w = st.number_input("Sistolica", 0), st.number_input("Diastolica", 0), st.number_input("Peso kg", 0.0, format="%.1f")
            n = st.text_area("Note")
            if st.form_submit_button("Salva"):
                supabase.table("health_logs").insert({"oxygen":o if o>0 else None, "bpm":b if b>0 else None, "temperature":t if t>0 else None, "systolic":s if s>0 else None, "diastolic":d if d>0 else None, "weight":w if w>0 else None, "notes":n}).execute()
                st.rerun()
        if st.button("Logout 🚪", use_container_width=True):
            st.session_state.authenticated = False
            st.rerun()
