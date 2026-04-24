import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
from datetime import datetime
import base64
from fpdf import FPDF

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

# --- 4. FUNZIONI DI ANALISI E PDF ---
def analyze_trends(df):
    if len(df) < 1: return None, []
    insights = []
    last = df.iloc[-1]
    if last.get('systolic') and last['systolic'] > 140:
        insights.append("⚠️ **Pressione Sistolica Alta**: Valore sopra 140 mmHg.")
    if last.get('oxygen') and last['oxygen'] < 94:
        insights.append("🚩 **Ossigeno Critico**: Rilevato valore sotto il 94%.")
    return last, insights

def export_pdf(df):
    pdf = FPDF()
    pdf.add_page()
    
    # Intestazione Professionale
    pdf.set_font("Arial", "B", 18)
    pdf.cell(0, 10, "Sanity Diary - Report Clinico Intelligente", ln=True, align="C")
    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 10, f"Generato il: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align="C")
    pdf.ln(5)

    # --- 1. ANALISI INTELLIGENTE & STATISTICA ---
    pdf.set_fill_color(230, 242, 255)
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, " Analisi Intelligente e Statistica", ln=True, fill=True)
    pdf.set_font("Arial", "", 11)
    
    _, alerts = analyze_trends(df)
    if alerts:
        pdf.set_font("Arial", "B", 11)
        pdf.cell(0, 8, "Avvisi Rilevati:", ln=True)
        pdf.set_font("Arial", "", 11)
        for a in alerts:
            pdf.multi_cell(0, 8, f"  - {a.replace('⚠️','').replace('🚩','').replace('**','')}")
    
    cols_stats = ['oxygen', 'bpm', 'temperature', 'systolic', 'diastolic', 'weight']
    valid_cols = [c for c in cols_stats if c in df.columns and not df[c].dropna().empty]
    if len(valid_cols) > 1:
        corr_matrix = df[valid_cols].corr(method='pearson')
        unstacked = corr_matrix.unstack().sort_values(ascending=False)
        top_corr = unstacked[unstacked < 0.98].head(1)
        if not top_corr.empty:
            v1, v2 = top_corr.index[0]
            pdf.ln(2)
            pdf.set_font("Arial", "B", 11)
            pdf.cell(0, 8, "Analisi delle Correlazioni (Pearson):", ln=True)
            pdf.set_font("Arial", "I", 11)
            pdf.multi_cell(0, 8, f"Rilevato legame statistico di {top_corr.values[0]:.2f} tra {v1} e {v2}.")

    # --- 2. RIEPILOGO MEDIE ---
    pdf.ln(5)
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, "Medie Storiche Periodo", ln=True)
    pdf.set_font("Arial", "", 12)
    for col in ['oxygen', 'bpm', 'systolic', 'diastolic', 'weight']:
        if col in df.columns and pd.notnull(df[col].mean()):
            pdf.cell(0, 8, f"- {col.capitalize()}: {df[col].mean():.2f}", ln=True)

    # --- 3. TABELLA DATI ---
    pdf.ln(10)
    pdf.set_font("Arial", "B", 11)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(35, 10, "Data", 1, 0, "C", True)
    pdf.cell(20, 10, "O2%", 1, 0, "C", True)
    pdf.cell(20, 10, "BPM", 1, 0, "C", True)
    pdf.cell(35, 10, "Press (S/D)", 1, 0, "C", True)
    pdf.cell(25, 10, "Peso", 1, 0, "C", True)
    pdf.cell(55, 10, "Note", 1, 0, "C", True)
    pdf.ln()
    
    pdf.set_font("Arial", "", 9)
    for _, row in df.sort_values(by='created_at', ascending=False).head(30).iterrows():
        pdf.cell(35, 8, row['created_at'].strftime('%d/%m/%y %H:%M'), 1)
        pdf.cell(20, 8, str(row['oxygen']) if pd.notnull(row['oxygen']) else "-", 1, 0, "C")
        pdf.cell(20, 8, str(row['bpm']) if pd.notnull(row['bpm']) else "-", 1, 0, "C")
        p_s = f"{int(row['systolic'])}/{int(row['diastolic'])}" if pd.notnull(row['systolic']) else "-"
        pdf.cell(35, 8, p_s, 1, 0, "C")
        pdf.cell(25, 8, f"{row['weight']:.1f}" if pd.notnull(row['weight']) else "-", 1, 0, "C")
        pdf.cell(55, 8, str(row['notes'])[:30] if pd.notnull(row['notes']) else "-", 1)
        pdf.ln()

    return bytes(pdf.output())

# --- 5. LOGICA PRINCIPALE ---
if supabase:
    try:
        res = supabase.table("health_logs").select("*").order("created_at", desc=False).execute()
        df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
        if not df.empty:
            df['created_at'] = pd.to_datetime(df['created_at'], format='ISO8601', utc=True).dt.tz_localize(None).dt.floor('s')
    except: df = pd.DataFrame()

    st.title("🩺 Sanity Diary Intelligence")

    # Banner Visite
    try:
        res_v = supabase.table("visite_mediche").select("*").eq("completata", False).order("data_visita").execute()
        if res_v.data:
            p = res_v.data[0]
            st.warning(f"🔔 **Prossima Visita:** {p['nome_visita']} - {p['data_visita']} ({p['luogo']})")
    except: pass

    if not df.empty:
        # Metriche Dashboard
        m1, m2, m3, m4 = st.columns(4)
        def get_delta(col):
            if len(df) > 1 and col in df.columns and pd.notnull(df[col].iloc[-1]) and pd.notnull(df[col].iloc[-2]):
                return f"{df[col].iloc[-1] - df[col].iloc[-2]:.1f}"
            return None
        m1.metric("Ossigeno", f"{df['oxygen'].iloc[-1]:.0f}%", get_delta('oxygen'))
        m2.metric("BPM", f"{df['bpm'].iloc[-1]:.0f}", get_delta('bpm'), delta_color="inverse")
        m3.metric("Press. Max", f"{df['systolic'].iloc[-1]:.0f}", get_delta('systolic'), delta_color="inverse")
        m4.metric("Peso", f"{df['weight'].iloc[-1]:.1f}kg", get_delta('weight'), delta_color="inverse")

        st.divider()
        t_graph, t_pearson, t_ref, t_reg = st.tabs(["📈 Trend & Medie", "🧬 Pearson IA", "📂 Referti", "📋 Registro & Report"])

        with t_graph:
            st.subheader("Riepilogo Medie Storiche")
            c_m1, c_m2, c_m3, c_m4 = st.columns(4)
            c_m1.write(f"**O2 Medio:** {df['oxygen'].mean():.1f}%")
            c_m2.write(f"**BPM Medio:** {df['bpm'].mean():.0f}")
            c_m3.write(f"**Sistolica Media:** {df['systolic'].mean():.0f}")
            c_m4.write(f"**Peso Medio:** {df['weight'].mean():.1f} kg")
            
            cols_plot = ['oxygen', 'bpm', 'temperature', 'systolic', 'diastolic', 'weight']
            valid_cols = [c for c in cols_plot if c in df.columns and not df[c].dropna().empty]
            st.plotly_chart(px.line(df, x='created_at', y=valid_cols, markers=True, template="plotly_white"), use_container_width=True)

        with t_pearson:
            st.subheader("Studio delle Correlazioni")
            c_info, c_map = st.columns([1, 2])
            with c_info:
                st.markdown("**Cos'è Pearson?** Misura il legame tra parametri.")
                if len(valid_cols) > 1:
                    corr_df = df[valid_cols].corr()
                    strong = corr_df.unstack().sort_values(ascending=False)
                    res_c = strong[strong < 0.99].head(1)
                    if not res_c.empty:
                        st.success(f"💡 **Insight:** Legame tra {res_c.index[0][0]} e {res_c.index[0][1]} ({res_c.values[0]:.2f})")
            with c_map:
                if len(valid_cols) > 1:
                    st.plotly_chart(px.imshow(corr_df, text_auto=".2f", color_continuous_scale='RdBu_r'), use_container_width=True)

        with t_ref:
            up = st.file_uploader("Carica PDF", type="pdf")
            if st.button("Salva PDF") and up:
                b64 = base64.b64encode(up.read()).decode('utf-8')
                supabase.table("referti_medici").insert({"nome_referto":up.name, "data_esame":str(datetime.now().date()), "file_path":b64}).execute()
                st.rerun()
            res_r = supabase.table("referti_medici").select("*").order("data_esame", desc=True).execute()
            for r in (res_r.data or []):
                st.download_button(f"📄 {r['nome_referto']}", base64.b64decode(r['file_path']), file_name=r['nome_referto'], key=f"d_{r['id']}")

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
                df_s['Data Ora'] = df_s['created_at'].dt.strftime('%d/%m/%Y %H:%M')
                st.dataframe(df_s[["Data Ora", "oxygen", "bpm", "weight", "systolic", "diastolic", "notes"]], use_container_width=True, hide_index=True)

    with st.sidebar:
        st.header("⚙️ Gestione")
        with st.expander("➕ Nuova Misura", expanded=True):
            with st.form("h_form", clear_on_submit=True):
                o, b, t = st.number_input("O2%", 0, 100, 0), st.number_input("BPM", 0, 250, 0), st.number_input("Temp°C", 0.0, 45.0, 0.0, 0.1)
                s, d, w = st.number_input("Sistolica", 0, 250, 0), st.number_input("Diastolica", 0, 150, 0), st.number_input("Peso kg", 0.0, 300.0, 0.0, 0.1)
                n = st.text_area("Note")
                if st.form_submit_button("Salva"):
                    data = {"oxygen":o if o>0 else None, "bpm":b if b>0 else None, "temperature":t if t>0 else None,
                            "systolic":s if s>0 else None, "diastolic":d if d>0 else None, "weight":w if w>0 else None, "notes":n if n.strip() else None}
                    supabase.table("health_logs").insert(data).execute()
                    st.rerun()
        if st.button("Logout 🚪", use_container_width=True):
            st.session_state.authenticated = False
            st.rerun()
