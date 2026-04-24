import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
from datetime import datetime
import base64
from fpdf import FPDF

# --- 1. CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Sanity Diary Intelligence", page_icon="🩺", layout="wide")

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

# --- 4. FUNZIONI DI ANALISI E EXPORT ---
def analyze_trends(df):
    """Analisi rapida degli ultimi valori per generare alert."""
    if len(df) < 1: return None, []
    insights = []
    last = df.iloc[-1]
    
    if last.get('systolic') and last['systolic'] > 140:
        insights.append("⚠️ **Pressione Sistolica Alta**: Valore sopra 140 mmHg.")
    if last.get('oxygen') and last['oxygen'] < 94:
        insights.append("🚩 **Ossigeno Critico**: Rilevato valore sotto il 94%.")
    return last, insights

def export_pdf(df):
    """Genera un report PDF professionale con dati e insight IA."""
    pdf = FPDF()
    pdf.add_page()
    
    # Intestazione
    pdf.set_font("Arial", "B", 18)
    pdf.cell(0, 10, "Sanity Diary - Report Intelligente", ln=True, align="C")
    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 10, f"Documento generato il: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align="C")
    pdf.ln(5)

    # --- SEZIONE: INSIGHT IA ---
    pdf.set_fill_color(230, 242, 255) 
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, " Analisi Intelligente (AI Insights)", ln=True, fill=True)
    pdf.set_font("Arial", "", 11)
    
    _, alerts = analyze_trends(df)
    if alerts:
        for a in alerts:
            clean_alert = a.replace("⚠️", "").replace("🚩", "").replace("**", "")
            pdf.multi_cell(0, 8, f"o {clean_alert}")
    else:
        pdf.cell(0, 8, "o Nessuna anomalia critica rilevata nelle ultime misurazioni.", ln=True)

    # Correlazioni nel PDF
    cols_ref = ['oxygen', 'bpm', 'temperature', 'systolic', 'diastolic', 'weight']
    valid_cols = [c for c in cols_ref if c in df.columns and not df[c].dropna().empty]
    if len(valid_cols) > 1:
        corr_df = df[valid_cols].corr(method='pearson')
        strong_corr = corr_df.unstack().sort_values(ascending=False)
        strongest = strong_corr[strong_corr < 0.95].head(1)
        if not strongest.empty:
            v1, v2 = strongest.index[0]
            val = strongest.values[0]
            pdf.ln(2)
            pdf.set_font("Arial", "I", 11)
            pdf.multi_cell(0, 8, f"Analisi Statistica: Trovato legame di {val:.2f} tra {v1} e {v2}.")

    pdf.ln(10)

    # --- SEZIONE: TABELLA DATI ---
    pdf.set_font("Arial", "B", 12)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(35, 10, "Data", 1, 0, "C", True)
    pdf.cell(25, 10, "O2%", 1, 0, "C", True)
    pdf.cell(25, 10, "BPM", 1, 0, "C", True)
    pdf.cell(35, 10, "Press (S/D)", 1, 0, "C", True)
    pdf.cell(30, 10, "Peso", 1, 0, "C", True)
    pdf.ln()
    
    pdf.set_font("Arial", "", 10)
    df_recent = df.sort_values(by='created_at', ascending=False).head(25)
    for _, row in df_recent.iterrows():
        pdf.cell(35, 8, row['created_at'].strftime('%d/%m/%y'), 1)
        pdf.cell(25, 8, str(row['oxygen']) if pd.notnull(row['oxygen']) else "-", 1, 0, "C")
        pdf.cell(25, 8, str(row['bpm']) if pd.notnull(row['bpm']) else "-", 1, 0, "C")
        press_str = f"{int(row['systolic'])}/{int(row['diastolic'])}" if pd.notnull(row['systolic']) else "-"
        pdf.cell(35, 8, press_str, 1, 0, "C")
        pdf.cell(30, 8, f"{row['weight']:.1f}" if pd.notnull(row['weight']) else "-", 1, 0, "C")
        pdf.ln()

    return bytes(pdf.output())

# --- 5. LOGICA PRINCIPALE ---
if supabase:
    # Recupero dati
    try:
        res = supabase.table("health_logs").select("*").order("created_at", desc=False).execute()
        df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
        if not df.empty:
            df['created_at'] = pd.to_datetime(df['created_at'], format='ISO8601', utc=True).dt.tz_localize(None).dt.floor('s')
    except:
        df = pd.DataFrame()

    st.title("🩺 Sanity Diary Intelligence")

    # Banner Promemoria Visite
    try:
        res_v = supabase.table("visite_mediche").select("*").eq("completata", False).order("data_visita").execute()
        if res_v.data:
            p = res_v.data[0]
            c1, c2 = st.columns([4, 1])
            c1.warning(f"🔔 **Prossima Visita:** {p['nome_visita']} il {p['data_visita']} ({p['luogo']})")
            if c2.button("✅ Completata"):
                supabase.table("visite_mediche").update({"completata": True}).eq("id", p['id']).execute()
                st.rerun()
    except: pass

    # --- 6. DASHBOARD KPI ---
    if not df.empty:
        m1, m2, m3, m4 = st.columns(4)
        def get_delta(col):
            if len(df) > 1 and col in df.columns and pd.notnull(df[col].iloc[-1]) and pd.notnull(df[col].iloc[-2]):
                return f"{df[col].iloc[-1] - df[col].iloc[-2]:.1f}"
            return None

        m1.metric("Ossigeno", f"{df['oxygen'].iloc[-1]:.0f}%" if 'oxygen' in df.columns else "N/A", get_delta('oxygen'))
        m2.metric("BPM", f"{df['bpm'].iloc[-1]:.0f}" if 'bpm' in df.columns else "N/A", get_delta('bpm'), delta_color="inverse")
        m3.metric("Press. Max", f"{df['systolic'].iloc[-1]:.0f}" if 'systolic' in df.columns else "N/A", get_delta('systolic'), delta_color="inverse")
        m4.metric("Peso", f"{df['weight'].iloc[-1]:.1f}kg" if 'weight' in df.columns else "N/A", get_delta('weight'), delta_color="inverse")

        _, alerts = analyze_trends(df)
        for a in alerts: st.info(a)

        # --- 7. TABS ---
        st.divider()
        t_graph, t_pearson, t_ref, t_reg = st.tabs(["📈 Trend", "🧬 Pearson IA", "📂 Referti", "📋 Registro & Report"])

        with t_graph:
            cols_plot = ['oxygen', 'bpm', 'temperature', 'systolic', 'diastolic', 'weight']
            valid_cols = [c for c in cols_plot if c in df.columns and not df[c].dropna().empty]
            fig = px.line(df, x='created_at', y=valid_cols, markers=True, template="plotly_white")
            st.plotly_chart(fig, use_container_width=True)

        with t_pearson:
            st.subheader("Studio delle Correlazioni")
            c_info, c_map = st.columns([1, 2])
            with c_info:
                st.markdown("**Cos'è Pearson?** Misura il legame tra parametri. 1.0 (Blu) significa che crescono insieme.")
                if len(valid_cols) > 1:
                    corr_df = df[valid_cols].corr(method='pearson')
                    strongest = corr_df.unstack().sort_values(ascending=False)
                    res_corr = strongest[strongest < 0.99].head(1)
                    if not res_corr.empty:
                        st.success(f"💡 **Insight:** Trovato legame tra {res_corr.index[0][0]} e {res_corr.index[0][1]} ({res_corr.values[0]:.2f})")
            with c_map:
                if len(valid_cols) > 1:
                    fig_corr = px.imshow(corr_df, text_auto=".2f", color_continuous_scale='RdBu_r', range_color=[-1, 1])
                    st.plotly_chart(fig_corr, use_container_width=True)

        with t_ref:
            up = st.file_uploader("Carica nuovo referto PDF", type="pdf")
            if st.button("Salva PDF") and up:
                b64 = base64.b64encode(up.read()).decode('utf-8')
                supabase.table("referti_medici").insert({"nome_referto":up.name, "data_esame":str(datetime.now().date()), "file_path":b64}).execute()
                st.rerun()
            res_r = supabase.table("referti_medici").select("*").order("data_esame", desc=True).execute()
            for r in (res_r.data or []):
                col_n, col_d = st.columns([4, 1])
                col_n.write(f"📄 {r['nome_referto']} ({r['data_esame']})")
                col_d.download_button("Scarica", base64.b64decode(r['file_path']), file_name=r['nome_referto'], key=f"d_{r['id']}")

        with t_reg:
            c_tab, c_exp = st.columns([3, 1])
            with c_exp:
                st.write("🖨️ **Export Medico**")
                try:
                    pdf_data = export_pdf(df)
                    st.download_button("Genera Report PDF", data=pdf_data, file_name=f"report_{datetime.now().strftime('%Y%m%d')}.pdf", mime="application/pdf", use_container_width=True)
                except Exception as e: st.error(f"Errore PDF: {e}")
            with c_tab:
                df_sorted = df.sort_values(by='created_at', ascending=False).copy()
                df_sorted['Data Ora'] = df_sorted['created_at'].dt.strftime('%d/%m/%Y %H:%M')
                cols_v = ["Data Ora", "oxygen", "bpm", "temperature", "weight", "systolic", "diastolic", "notes"]
                st.dataframe(df_sorted[[c for c in cols_v if c in df_sorted.columns]], use_container_width=True, hide_index=True)

    # --- 8. SIDEBAR ---
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
else:
    st.error("Connessione Database fallita.")
