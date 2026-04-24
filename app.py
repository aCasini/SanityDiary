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

# --- 4. FUNZIONI DI ANALISI AVANZATA ---
def get_ai_insights(df):
    if df.empty: return [], ""
    recent = df.sort_values(by='created_at', ascending=True).tail(10)
    alerts = []
    if 'systolic' in recent.columns and (recent['systolic'] > 140).any():
        alerts.append("Rilevati episodi di pressione sistolica alta (>140) nei dati recenti.")
    if 'oxygen' in recent.columns and (recent['oxygen'] < 94).any():
        alerts.append("Rilevati cali di ossigenazione sotto il 94% negli ultimi record.")
    
    # Matrice completa: includiamo tutti i parametri numerici disponibili
    cols_stats = ['oxygen', 'bpm', 'temperature', 'systolic', 'diastolic', 'weight']
    valid_cols = [c for c in cols_stats if c in df.columns and not df[c].dropna().empty]
    
    correlation_str = ""
    if len(valid_cols) > 1:
        corr_matrix = df[valid_cols].corr()
        # Estraiamo la correlazione più forte (escludendo l'autocorrelazione 1.0)
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

    # SEZIONE AI
    pdf.set_fill_color(230, 242, 255)
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, " Analisi Intelligente dei Dati", ln=True, fill=True)
    pdf.set_font("Arial", "", 11)
    alerts, corr_text = get_ai_insights(df)
    if alerts:
        for a in alerts: pdf.multi_cell(0, 8, f"  - {a}")
    else: pdf.cell(0, 8, "  - Nessuna anomalia critica rilevata.", ln=True)
    if corr_text:
        pdf.ln(2)
        pdf.set_font("Arial", "I", 11)
        pdf.multi_cell(0, 8, f"Insight IA: {corr_text}")

    # MEDIE
    pdf.ln(5)
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, "Medie Storiche", ln=True)
    pdf.set_font("Arial", "", 12)
    for col in ['oxygen', 'bpm', 'temperature', 'systolic', 'diastolic', 'weight']:
        if col in df.columns and pd.notnull(df[col].mean()):
            pdf.cell(0, 8, f"- {col.capitalize()}: {df[col].mean():.2f}", ln=True)

    # TABELLA
    pdf.ln(10)
    pdf.set_font("Arial", "B", 10)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(35, 10, "Data", 1, 0, "C", True)
    pdf.cell(15, 10, "O2%", 1, 0, "C", True)
    pdf.cell(15, 10, "BPM", 1, 0, "C", True)
    pdf.cell(15, 10, "T C", 1, 0, "C", True)
    pdf.cell(30, 10, "Press (S/D)", 1, 0, "C", True)
    pdf.cell(20, 10, "Peso", 1, 0, "C", True)
    pdf.cell(60, 10, "Note", 1, 0, "C", True)
    pdf.ln()
    
    pdf.set_font("Arial", "", 9)
    for _, row in df.sort_values(by='created_at', ascending=False).head(30).iterrows():
        pdf.cell(35, 8, row['created_at'].strftime('%d/%m/%y %H:%M'), 1)
        pdf.cell(15, 8, str(row['oxygen']) if pd.notnull(row['oxygen']) else "-", 1, 0, "C")
        pdf.cell(15, 8, str(row['bpm']) if pd.notnull(row['bpm']) else "-", 1, 0, "C")
        pdf.cell(15, 8, str(row['temperature']) if pd.notnull(row['temperature']) else "-", 1, 0, "C")
        p_s = f"{int(row['systolic'])}/{int(row['diastolic'])}" if pd.notnull(row['systolic']) else "-"
        pdf.cell(30, 8, p_s, 1, 0, "C")
        pdf.cell(20, 8, f"{row['weight']:.1f}" if pd.notnull(row['weight']) else "-", 1, 0, "C")
        note = str(row['notes'])[:35] if pd.notnull(row['notes']) else "-"
        pdf.cell(60, 8, note, 1)
        pdf.ln()
    return bytes(pdf.output())

# --- 5. LOGICA APP ---
if supabase:
    try:
        res = supabase.table("health_logs").select("*").order("created_at", desc=False).execute()
        df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
        if not df.empty:
            df['created_at'] = pd.to_datetime(df['created_at'], format='ISO8601', utc=True).dt.tz_localize(None).dt.floor('s')
    except: df = pd.DataFrame()

    st.title("🩺 Sanity Diary Intelligence")

    if not df.empty:
        # Metriche con delta
        m1, m2, m3, m4 = st.columns(4)
        def calc_delta(col):
            if len(df) >= 2:
                last, prev = df[col].iloc[-1], df[col].iloc[-2]
                if pd.notnull(last) and pd.notnull(prev): return round(float(last - prev), 2)
            return None

        m1.metric("Ossigeno", f"{df['oxygen'].iloc[-1]:.0f}%", calc_delta('oxygen'))
        m2.metric("BPM", f"{df['bpm'].iloc[-1]:.0f}", calc_delta('bpm'), delta_color="inverse")
        m3.metric("Press. Max", f"{df['systolic'].iloc[-1]:.0f}", calc_delta('systolic'), delta_color="inverse")
        m4.metric("Peso", f"{df['weight'].iloc[-1]:.1f}kg", calc_delta('weight'))

        st.divider()
        t_graph, t_pearson, t_ref, t_reg = st.tabs(["📈 Trend & Medie", "🧬 Pearson IA", "📂 Referti", "📋 Registro & Report"])

        with t_graph:
            st.subheader("Riepilogo Medie Storiche")
            c_m = st.columns(5)
            params = [('oxygen', 'O2%'), ('bpm', 'BPM'), ('temperature', 'Temp'), ('systolic', 'Sist'), ('weight', 'Peso')]
            for i, (col, label) in enumerate(params):
                if col in df.columns:
                    c_m[i].write(f"**{label} Medio:** {df[col].mean():.2f}")
            
            valid_cols = [c for c in ['oxygen', 'bpm', 'temperature', 'systolic', 'diastolic', 'weight'] if c in df.columns]
            st.plotly_chart(px.line(df, x='created_at', y=valid_cols, markers=True, template="plotly_white"), use_container_width=True)

        with t_pearson:
            st.subheader("🧬 Studio delle Correlazioni Intelligenti")
            c_info, c_map = st.columns([1, 2])
            alerts, corr_text = get_ai_insights(df)
            with c_info:
                st.markdown("**Analisi Multidimensionale:**")
                if corr_text:
                    st.info(f"💡 {corr_text}")
                else:
                    st.write("Dati insufficienti per l'analisi.")
                
                st.caption("La matrice a destra analizza tutti i parametri inseriti (inclusa temperatura e peso) per trovare legami nascosti.")
                if alerts:
                    st.warning("⚠️ **Alert Recenti:**\n" + "\n".join([f"- {a}" for a in alerts]))

            with c_map:
                if len(valid_cols) > 1:
                    corr_df = df[valid_cols].corr()
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
                    st.download_button("Genera Report PDF", data=pdf_data, file_name="report_completo.pdf", mime="application/pdf", use_container_width=True)
                except Exception as e: st.error(f"Errore: {e}")
            with c_tab:
                df_s = df.sort_values(by='created_at', ascending=False).copy()
                df_s['Data Ora'] = df_s['created_at'].dt.strftime('%d/%m/%Y %H:%M')
                disp_cols = ["Data Ora", "oxygen", "bpm", "temperature", "weight", "systolic", "diastolic", "notes"]
                st.dataframe(df_s[[c for c in disp_cols if c in df_s.columns]], use_container_width=True, hide_index=True)

    with st.sidebar:
        st.header("⚙️ Gestione")
        with st.expander("➕ Nuova Misura", expanded=True):
            with st.form("h_form", clear_on_submit=True):
                o, b, t = st.number_input("O2%", 0), st.number_input("BPM", 0), st.number_input("Temp °C", 0.0, format="%.1f")
                s, d, w = st.number_input("Sistolica", 0), st.number_input("Diastolica", 0), st.number_input("Peso kg", 0.0, format="%.1f")
                n = st.text_area("Note")
                if st.form_submit_button("Salva"):
                    data = {"oxygen":o if o>0 else None, "bpm":b if b>0 else None, "temperature":t if t>0 else None,
                            "systolic":s if s>0 else None, "diastolic":d if d>0 else None, "weight":w if w>0 else None, "notes":n}
                    supabase.table("health_logs").insert(data).execute()
                    st.rerun()
        if st.button("Logout 🚪", use_container_width=True):
            st.session_state.authenticated = False
            st.rerun()
