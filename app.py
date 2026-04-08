import streamlit as st
import pandas as pd
from openai import OpenAI
import plotly.express as px
import os
import datetime
import tempfile
from fpdf import FPDF

import requests

# The TTL Cache (43200 seconds = 12 hours)
@st.cache_data(ttl=43200)
def fetch_live_macro_events(news_api_key):
    # We explicitly search for supply chain threats
    query = "supply chain OR port strike OR trade tariff OR geopolitical"
    url = f"https://newsapi.org/v2/everything?q={query}&sortBy=publishedAt&language=en&apiKey={news_api_key}"
    
    try:
        response = requests.get(url)
        data = response.json()
        
        live_events = []
        # Grab the top 3 most recent articles
        for i, article in enumerate(data.get('articles', [])[:3]):
            live_events.append({
                "id": i + 1,
                "source": article['source']['name'],
                "text": article['title'], 
                "active": True
            })
        return live_events
    except Exception as e:
        return [{"id": 1, "source": "System", "text": "Failed to connect to Live News API.", "active": True}]

# ==========================================
# PAGE CONFIGURATION
# ==========================================
st.set_page_config(page_title="WITW: Supply Chain Copilot", layout="wide")

# --- CUSTOM CSS FOR PREMIUM TYPOGRAPHY & SPACING ---
st.markdown("""
    <style>
        /* Tighten the main block padding */
        .block-container {
            padding-top: 2rem;
            padding-bottom: 2rem;
        }
        /* Make headers sleeker and less bulky */
        h1 { font-size: 2.2rem !important; font-weight: 600 !important; }
        h2 { font-size: 1.8rem !important; font-weight: 500 !important; }
        h3 { font-size: 1.4rem !important; font-weight: 500 !important; color: #00a8ff !important; }
        
        /* Modernize the metric cards */
        [data-testid="stMetricValue"] {
            font-size: 1.8rem !important;
            font-weight: 700 !important;
        }
        [data-testid="stMetricLabel"] {
            font-size: 0.9rem !important;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: #8b9eb3 !important;
        }
    </style>
""", unsafe_allow_html=True)

st.title("🌍 WITW: What In The World")
st.markdown("Supply Chain Risk & Mitigation Engine")

# ==========================================
# MASTER SIDEBAR: SETTINGS & CONTEXT
# ==========================================
st.sidebar.header("🏢 Company Profile")

if 'company_profile' not in st.session_state:
    st.session_state.company_profile = {
        "name": "Default Corp", "industry": "Automotive", 
        "scale": "₹250Cr - ₹1,000Cr (Mid-Market)", "presence": "India"
    }

industries = ["Automotive", "Pharmaceuticals", "Fast Fashion", "Consumer Electronics", "FMCG", "Retail & E-commerce", "Heavy Manufacturing", "Chemicals"]
revenue_scales_inr = ["< ₹50 Crores", "₹50Cr - ₹250Cr", "₹250Cr - ₹1,000Cr", "₹1,000Cr - ₹5,000Cr", "> ₹5,000Cr"]
countries = ["India", "United States", "China", "Germany", "Japan", "United Kingdom", "Taiwan", "Mexico"]

comp_name = st.sidebar.text_input("Company Name:", value=st.session_state.company_profile["name"])
comp_ind = st.sidebar.selectbox("Industry:", industries, index=industries.index(st.session_state.company_profile["industry"]) if st.session_state.company_profile["industry"] in industries else 0)
comp_scale = st.sidebar.selectbox("Revenue Scale (INR):", revenue_scales_inr, index=revenue_scales_inr.index(st.session_state.company_profile["scale"]) if st.session_state.company_profile["scale"] in revenue_scales_inr else 0)
comp_presence = st.sidebar.selectbox("HQ/Hub:", countries, index=countries.index(st.session_state.company_profile["presence"]) if st.session_state.company_profile["presence"] in countries else 0)

if st.sidebar.button("💾 Save Profile"):
    st.session_state.company_profile = {"name": comp_name, "industry": comp_ind, "scale": comp_scale, "presence": comp_presence}
    st.sidebar.success("Profile Locked!")

st.sidebar.markdown("---")
st.sidebar.header("💰 Financial Exposure Model")
annual_revenue_cr = st.sidebar.number_input(
    "Total Annual Revenue (₹ Crores)", 
    min_value=10, 
    max_value=100000, 
    value=500, 
    step=50,
    help="Used to calculate Value at Risk (VaR) across the supplier network."
)
st.sidebar.header("⚙️ Configure Risk Engine")
st.sidebar.caption("Weights must sum to exactly 100%")

geo_weight = st.sidebar.slider("Geopolitical Weight", 0, 100, 25)
fin_weight = st.sidebar.slider("Financial Weight", 0, 100, 25)
ops_weight = st.sidebar.slider("Operational Weight", 0, 100, 25)
env_weight = st.sidebar.slider("Environmental Weight", 0, 100, 25)

total_weight = geo_weight + fin_weight + ops_weight + env_weight

if total_weight > 100:
    st.sidebar.error(f"⚠️ Total is {total_weight}%. Please reduce weights by {total_weight - 100}%.")
    st.stop()
elif total_weight < 100:
    st.sidebar.warning(f"⚠️ Total is {total_weight}%. Please increase weights by {100 - total_weight}% to complete the risk profile.")
    st.stop()
else:
    st.sidebar.success("✅ Risk Profile Balanced (100%)")

st.sidebar.markdown("---")
appetite_threshold = st.sidebar.slider("⚠️ Risk Appetite Threshold", 1.0, 10.0, 6.0, step=0.5)

st.sidebar.markdown("---")
st.sidebar.header("🧠 AI Configuration")
try:
    api_key = st.secrets["GROQ_API_KEY"]
    st.sidebar.success("✅ Secure API Key Loaded")
except Exception:
    api_key = st.sidebar.text_input("Paste Groq API Key here:", type="password")
    st.sidebar.warning("Create .streamlit/secrets.toml to save key permanently.")

# ==========================================
# PHASE 1: SMART INGESTION & ROLL-UP AGGREGATOR
# ==========================================
st.subheader("📂 Step 1: Data Ingestion & Smart Mapping")

# Upgraded vocabulary to recognize KPIs and Sub-Groups
def auto_guess_tags(col_name):
    col_lower = str(col_name).lower()
    tags = []
    if any(w in col_lower for w in ['supplier', 'vendor', 'name', 'company']): tags.append('Supplier Name')
    elif any(w in col_lower for w in ['component', 'product', 'part', 'item']): tags.append('Component')
    elif any(w in col_lower for w in ['sub', 'group', 'category', 'type', 'class']): tags.append('Sub-Group')
    elif any(w in col_lower for w in ['location', 'city', 'country', 'region', 'hq', 'origin']): tags.append('Location')
    elif any(w in col_lower for w in ['geo', 'tariff', 'political', 'trade']): tags.append('Geo Risk')
    elif any(w in col_lower for w in ['fin', 'cost', 'currency', 'bankrupt', 'price']): tags.append('Fin Risk')
    elif any(w in col_lower for w in ['ops', 'logistics', 'quality', 'delay', 'lead', 'defective', 'status']): tags.append('Ops Risk')
    elif any(w in col_lower for w in ['env', 'climate', 'weather', 'carbon', 'storm', 'compliance']): tags.append('Env Risk')
    elif any(w in col_lower for w in ['alt', 'backup', 'secondary']): tags.append('Alternate Supplier')
    elif any(w in col_lower for w in ['switch', 'markup', 'premium']): tags.append('Switch Cost Markup')
    
    if not tags: tags.append('Other / Keep')
    return tags

available_tags = [
    'Supplier Name', 'Component', 'Sub-Group', 'Location', 
    'Geo Risk', 'Fin Risk', 'Ops Risk', 'Env Risk', 
    'Alternate Supplier', 'Switch Cost Markup', 'Other / Keep'
]

if 'mapped_df' not in st.session_state:
    st.session_state.mapped_df = None

uploaded_file = st.file_uploader("Upload your raw Supply Chain Dataset (CSV or Excel)", type=["csv", "xlsx"])

if uploaded_file is not None and st.session_state.mapped_df is None:
    if uploaded_file.name.endswith('.csv'):
        raw_df = pd.read_csv(uploaded_file)
    else:
        raw_df = pd.read_excel(uploaded_file)
        
    with st.expander("✨ Smart Mapping Engine", expanded=True):
        st.markdown("Map your columns. Multiple columns can be grouped into one risk category.")
        user_tags = {}
        for raw_col in raw_df.columns:
            c1, c2 = st.columns([1, 2])
            with c1: st.write(f"**`{raw_col}`**")
            with c2:
                guessed_tags = auto_guess_tags(raw_col)
                user_tags[raw_col] = st.multiselect(f"Tags for {raw_col}", options=available_tags, default=guessed_tags, label_visibility="collapsed")
        
        st.markdown("---")
        if st.button("Commit Mapping & Process Data", type="primary"):
            temp_df = raw_df.copy()
            
            def get_col_by_tag(tag):
                return [col for col, tags in user_tags.items() if tag in tags]
                
            # 1. Map Core Identifiers
            sup_cols = get_col_by_tag('Supplier Name')
            comp_cols = get_col_by_tag('Component')
            sub_cols = get_col_by_tag('Sub-Group')
            loc_cols = get_col_by_tag('Location')
            alt_cols = get_col_by_tag('Alternate Supplier')
            mark_cols = get_col_by_tag('Switch Cost Markup')

            temp_df['Supplier'] = temp_df[sup_cols[0]] if sup_cols else "Unknown"
            temp_df['Component'] = temp_df[comp_cols[0]] if comp_cols else "Unknown"
            temp_df['Sub_Group'] = temp_df[sub_cols[0]] if sub_cols else "Unknown"
            temp_df['Location'] = temp_df[loc_cols[0]] if loc_cols else "Unknown"
            temp_df['Alternate_Supplier'] = temp_df[alt_cols[0]] if alt_cols else "None"
            temp_df['Switch_Cost_Markup'] = pd.to_numeric(temp_df[mark_cols[0]], errors='coerce').fillna(0) if mark_cols else 0.0
            
            # 2. Extract Raw Risks/KPIs
            def calc_risk(tag, dest_col):
                cols = get_col_by_tag(tag)
                if cols:
                    numeric_cols = temp_df[cols].apply(pd.to_numeric, errors='coerce')
                    temp_df[dest_col] = numeric_cols.mean(axis=1).fillna(0)
                else:
                    temp_df[dest_col] = 0.0

            calc_risk('Geo Risk', 'Base_Geo_Risk')
            calc_risk('Fin Risk', 'Base_Fin_Risk')
            calc_risk('Ops Risk', 'Base_Ops_Risk')
            calc_risk('Env Risk', 'Base_Env_Risk')
            
            # 3. THE MAGIC: Roll-up Grouping by Unique Supplier
            agg_funcs = {
                'Component': lambda x: x.mode()[0] if not x.mode().empty else 'Multiple',
                'Sub_Group': lambda x: x.mode()[0] if not x.mode().empty else 'Unknown',
                'Location': lambda x: x.mode()[0] if not x.mode().empty else 'Unknown',
                # THE FIX: Drops blank/NaN rows and forces it to find an actual Alternate Supplier name
                'Alternate_Supplier': lambda x: x.dropna().iloc[0] if not x.dropna().empty else "None",
                'Switch_Cost_Markup': 'mean',
                'Base_Geo_Risk': 'mean',
                'Base_Fin_Risk': 'mean',
                'Base_Ops_Risk': 'mean',
                'Base_Env_Risk': 'mean'
            }
            
            master_df = temp_df.groupby('Supplier', as_index=False).agg(agg_funcs)

            # 4. Normalize KPIs to a 0-10 Risk Scale
            for risk_col in ['Base_Geo_Risk', 'Base_Fin_Risk', 'Base_Ops_Risk', 'Base_Env_Risk']:
                max_val = master_df[risk_col].max()
                if max_val > 10:
                    master_df[risk_col] = (master_df[risk_col] / max_val) * 10
                master_df[risk_col] = master_df[risk_col].round(2)
            
            st.session_state.mapped_df = master_df
            st.rerun()

# --- GATEKEEPER LOGIC ---
if st.session_state.mapped_df is None:
    st.info("👆 Please upload and verify your dataset above to activate the WITW Command Center.")
    st.stop() 

# --- LIVE DATA EDITOR ---
col_head, col_btn = st.columns([4, 1])
with col_head: st.subheader("📊 Master Supplier Database (Consolidated)")
with col_btn:
    if st.button("Reset Data"):
        st.session_state.mapped_df = None
        st.rerun()

st.session_state.mapped_df = st.data_editor(st.session_state.mapped_df, num_rows="dynamic", use_container_width=True)
df = st.session_state.mapped_df

# ==========================================
# PHASE 2: RISK ENGINE & EXECUTIVE DASHBOARD
# ==========================================
st.markdown("---")
st.subheader("📈 Executive Risk Dashboard")

if total_weight == 0:
    w_geo = w_fin = w_ops = w_env = 0.25 
else:
    w_geo = geo_weight / total_weight; w_fin = fin_weight / total_weight
    w_ops = ops_weight / total_weight; w_env = env_weight / total_weight

try:
    df['Calculated_Risk'] = ((df['Base_Geo_Risk'] * w_geo) + (df['Base_Fin_Risk'] * w_fin) + (df['Base_Ops_Risk'] * w_ops) + (df['Base_Env_Risk'] * w_env)).round(1)
    df['Action_Required'] = df['Calculated_Risk'].apply(lambda x: '🚨 Mitigate' if x >= appetite_threshold else '✅ Monitor')
    st.session_state.scored_df = df
except KeyError as e:
    st.error(f"Mapping Error: Ensure you mapped {e} correctly in Step 1.")
    st.stop()

# --- THE MATH ENGINE ---
total_suppliers = len(df)
high_risk_df = df[df['Action_Required'] == '🚨 Mitigate']
high_risk_count = len(high_risk_df)
avg_risk = df['Calculated_Risk'].mean().round(1)

# --- THE VALUE AT RISK (VaR) CALCULATOR ---
revenue_per_supplier = annual_revenue_cr / total_suppliers if total_suppliers > 0 else 0

# Ensure the column itself is rounded to 2 decimals
df['Value_at_Risk_Cr'] = (revenue_per_supplier * (df['Calculated_Risk'] / 10)).round(2)

# Sum the critical exposure and round to 2 decimals
critical_var = df[df['Action_Required'] == '🚨 Mitigate']['Value_at_Risk_Cr'].sum().round(2)

# --- RENDER TOP METRICS ---
m1, m2, m3, m4 = st.columns(4)

with m1: 
    st.metric("Total Suppliers", total_suppliers)

with m2: 
    st.metric("Avg Network Risk", f"{avg_risk} / 10")

with m3: 
    # Only show Red/Delta if there is an actual alert
    alert_color = "inverse" if high_risk_count > 0 else "normal"
    alert_label = f"{high_risk_count} Requires Action" if high_risk_count > 0 else "All Clear"
    st.metric("Critical Alerts", high_risk_count, delta=alert_label, delta_color=alert_color)

with m4: 
    var_label = "Immediate Exposure" if critical_var > 0 else "No Exposure"
    var_delta_color = "inverse" if critical_var > 0 else "normal"
    # The :.2f forces 2 decimal places in the display
    st.metric("Value at Risk (VaR)", f"₹ {critical_var:.2f} Cr", delta=var_label, delta_color=var_delta_color)

# 5. Interactive Visualizations (Plotly)
st.markdown("---")
chart_col1, chart_col2 = st.columns([1, 2])

with chart_col1:
    st.markdown("**Network Health Distribution**")
    fig_pie = px.pie(
        df, 
        names='Action_Required', 
        hole=0.5,
        color='Action_Required',
        color_discrete_map={'✅ Monitor': '#2ecc71', '🚨 Mitigate': '#e74c3c'},
	template="plotly_dark"
    )
    fig_pie.update_layout(margin=dict(t=20, b=20, l=20, r=20), showlegend=True)
    st.plotly_chart(fig_pie, use_container_width=True)

with chart_col2:
    st.markdown("**Top Vulnerable Suppliers**")
    top_risk_df = df.sort_values(by='Calculated_Risk', ascending=False).head(10)
    fig_bar = px.bar(
        top_risk_df, 
        x='Calculated_Risk', 
        y='Supplier', 
        orientation='h',
        color='Calculated_Risk',
        color_continuous_scale='Reds',
        text='Calculated_Risk',
        hover_data=['Component', 'Location', 'Value_at_Risk_Cr'], # We added the money here!
	template="plotly_dark"
    )
    fig_bar.update_layout(
        yaxis={'categoryorder': 'total ascending'}, 
        margin=dict(t=20, b=20, l=150, r=20),
        xaxis_title="Risk Score (/10)",
        yaxis_title=""
    )
    st.plotly_chart(fig_bar, use_container_width=True)

with st.expander("📄 View Raw Risk Data", expanded=False):
    st.dataframe(df[['Supplier', 'Component', 'Location', 'Calculated_Risk', 'Action_Required']].sort_values(by='Calculated_Risk', ascending=False), use_container_width=True)

# ==========================================
# PHASE 3: COMMAND CENTER PRO (SIM & AUDIT)
# ==========================================
st.markdown("---")
st.header("🎛️ WITW: Command Center Pro")

if 'active_events' not in st.session_state:
    st.session_state.active_events = [
        {"id": 1, "source": "System", "text": "Click 'Refresh News' to load live data.", "active": True}
    ]

tab1, tab2, tab3 = st.tabs(["🌍 Reality Engine (Live)", "🧪 Simulation Sandbox", "🔍 Supplier Audit"])

# --- TAB 1: REALITY ENGINE (Fully Restored) ---
with tab1:
    st.markdown("### 🧠 AI Analysis: Internal Metrics + External Reality")
    
    generate_live_strategy = st.button("Generate Comprehensive Strategy", type="primary", use_container_width=True)
    st.markdown("---")
    
    col_news_head, col_news_btn = st.columns([4, 1])
    with col_news_head:
        st.subheader("📡 Live Intelligence Feed")
    with col_news_btn:
        if st.button("🔄 Refresh News"):
            st.session_state.active_events = fetch_live_macro_events(st.secrets["NEWS_API_KEY"])
            st.rerun()

    active_count = 0
    for event in st.session_state.active_events:
        if event["active"]:
            active_count += 1
            col_text, col_btn = st.columns([4, 1])
            with col_text: st.info(f"**{event['source']}:** {event['text']}")
            with col_btn:
                if st.button("❌ Ignore", key=f"del_real_{event['id']}"):
                    event["active"] = False
                    st.rerun()

    if 'live_strategy' not in st.session_state:
        st.session_state.live_strategy = None

    if generate_live_strategy:
        if not api_key:
            st.error("Please configure your Groq API Key in the sidebar!")
        else:
            with st.spinner("AI is analyzing real-time network risk..."):
                try:
                    client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
                    
                    active_real_events = [event['text'] for event in st.session_state.active_events if event['active']]
                    real_events_text = "\n- ".join(active_real_events) if active_real_events else "No major active global events."
                    high_risk_suppliers = df[df['Action_Required'] == '🚨 Mitigate']['Supplier'].tolist()
                    
                    system_context = f"You are an elite Supply Chain Strategy Consultant advising {st.session_state.company_profile['name']} ({st.session_state.company_profile['industry']} sector, HQ: {st.session_state.company_profile['presence']})."
                    
                    prompt = f"""
                    Live events:
                    - {real_events_text}
                    
                    Dashboard Status:
                    - Total Network Value at Risk: ₹ {df['Value_at_Risk_Cr'].sum():.2f} Cr
                    - Immediate Exposure: ₹ {critical_var:.2f} Cr
                    - Failing Suppliers: {high_risk_suppliers if high_risk_suppliers else 'None'}
                    
                    Format strictly:
                    **Section 1: Financial Impact & VaR** (Explain the Crores at risk)
                    **Section 2: Contextual Risk Explanation** (Connect news to suppliers)
                    **Section 3: Mitigation Strategy** (Procurement, Logistics, Finance Actions)
                    """
                    
                    response = client.chat.completions.create(
                        model="llama-3.1-8b-instant", 
                        messages=[{"role": "system", "content": system_context}, {"role": "user", "content": prompt}]
                    )
                    st.session_state.live_strategy = response.choices[0].message.content
                    st.success("Strategy Generated!")
                except Exception as e:
                    st.error(f"API Error: {e}")

 # Render Strategy & PDF Button
    if st.session_state.live_strategy:
        st.info(st.session_state.live_strategy)
        
        pdf = FPDF()
        pdf.add_page()
        
        # 1. Header
        pdf.set_font("Arial", 'B', 24)
        pdf.set_text_color(41, 128, 185) # WITW Blue
        pdf.cell(200, 10, txt="WITW", ln=True, align='L')
        pdf.set_font("Arial", 'I', 12)
        pdf.set_text_color(128, 128, 128)
        pdf.cell(200, 10, txt="Executive Risk Brief", ln=True, align='L')
        pdf.ln(10)
        
        # 2. Inject High-Res Graphs
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_pie, \
                 tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_bar:
                
                # Take the background screenshot of Phase 2 charts
                fig_pie.write_image(tmp_pie.name, width=800, height=400)
                fig_bar.write_image(tmp_bar.name, width=800, height=400)
                
                pdf.set_font("Arial", 'B', 14)
                pdf.set_text_color(0, 0, 0)
                pdf.cell(200, 10, txt="1. Network Health Visualizations", ln=True)
                pdf.image(tmp_pie.name, x=10, w=180)
                pdf.image(tmp_bar.name, x=10, w=180)
                pdf.add_page() # Move text to the next page
                
            os.unlink(tmp_pie.name)
            os.unlink(tmp_bar.name)
        except Exception as e:
            st.warning(f"Could not render graphs in PDF. Ensure 'kaleido' is installed. Error: {e}")

        # 3. Inject AI Strategy
        pdf.set_font("Arial", 'B', 14)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(200, 10, txt="2. AI Mitigation Strategy", ln=True)
        pdf.ln(5)

        clean_text = st.session_state.live_strategy.replace('**', '')
        safe_text = clean_text.encode('latin-1', 'replace').decode('latin-1')
        pdf.set_font("Arial", '', 11)
        pdf.multi_cell(0, 7, txt=safe_text)
        
        # 4. Generate Download
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_pdf:
            pdf.output(tmp_pdf.name)
            with open(tmp_pdf.name, "rb") as f:
                pdf_bytes = f.read()
                
        col_space, col_download = st.columns([3, 1])
        with col_download:
            st.download_button(
                label="📥 Download report", 
                data=pdf_bytes, 
                file_name="WITW_Brief.pdf", 
                mime="application/pdf", 
                type="primary", 
                use_container_width=True
            )

# --- TAB 2: SIMULATION SANDBOX (Radio Button Upgrade) ---
with tab2:
    st.subheader("🛠️ Network Stress-Test (What-If 2.0)")
    
    sim_mode = st.radio("Select Simulation Mode:", ["🎛️ Macro-Toggles", "✍️ Custom Scenario (Text)"], horizontal=True)
    st.markdown("---")

    if sim_mode == "🎛️ Macro-Toggles":
        st.markdown("Simulate 'Black Swan' events. Toggles apply a **coefficient penalty** to network math.")
        col_s1, col_s2, col_s3 = st.columns(3)
        with col_s1:
            strike_toggle = st.toggle("🚢 Major Port Strike", help="+25% Ops Risk")
            tariff_toggle = st.toggle("📉 Trade War / Tariffs", help="+20% Fin Risk")
        with col_s2:
            weather_toggle = st.toggle("🌪️ Extreme Weather Event", help="+30% Env Risk")
            cyber_toggle = st.toggle("💻 Tier-1 Cyber Attack", help="+15% Ops Risk")
        with col_s3:
            material_spike = st.slider("Raw Material Inflation (%)", 0, 50, 0, step=5)

        sim_df = df.copy()
        if strike_toggle: sim_df['Base_Ops_Risk'] = (sim_df['Base_Ops_Risk'] * 1.25).clip(0, 10)
        if tariff_toggle: sim_df['Base_Fin_Risk'] = (sim_df['Base_Fin_Risk'] * 1.20).clip(0, 10)
        if weather_toggle: sim_df['Base_Env_Risk'] = (sim_df['Base_Env_Risk'] * 1.30).clip(0, 10)
        if cyber_toggle: sim_df['Base_Ops_Risk'] = (sim_df['Base_Ops_Risk'] * 1.15).clip(0, 10)
        if material_spike > 0: sim_df['Base_Fin_Risk'] = (sim_df['Base_Fin_Risk'] + (material_spike/10)).clip(0, 10)

        sim_df['Calculated_Risk'] = ((sim_df['Base_Geo_Risk'] * w_geo) + (sim_df['Base_Fin_Risk'] * w_fin) + (sim_df['Base_Ops_Risk'] * w_ops) + (sim_df['Base_Env_Risk'] * w_env)).round(2)
        sim_revenue_per_supplier = annual_revenue_cr / total_suppliers if total_suppliers > 0 else 0
        sim_df['Value_at_Risk_Cr'] = (sim_revenue_per_supplier * (sim_df['Calculated_Risk'] / 10)).round(2)
        
        sim_critical_var = sim_df[sim_df['Calculated_Risk'] >= appetite_threshold]['Value_at_Risk_Cr'].sum().round(2)
        var_impact = (sim_critical_var - critical_var).round(2)

        st.markdown("### Simulation Impact Analysis")
        st.metric("Simulated Total VaR", f"₹ {sim_critical_var:.2f} Cr", delta=f"₹ {var_impact:.2f} Cr Change", delta_color="inverse")

    else:
        # Custom Scenario Mode
        custom_scenario = st.text_area("Describe your specific 'What-If' scenario (e.g., 'What if China blocks steel exports?'):")
        if st.button("Generate Strategy for Custom Scenario", type="primary"):
            if not api_key:
                st.error("Please configure API Key.")
            elif not custom_scenario:
                st.warning("Please type a scenario first.")
            else:
                with st.spinner("AI is analyzing the custom scenario..."):
                    try:
                        client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
                        prompt = f"Baseline VaR is ₹ {critical_var} Cr. Scenario: {custom_scenario}. Generate a highly professional mitigation strategy."
                        response = client.chat.completions.create(
                            model="llama-3.1-8b-instant", 
                            messages=[{"role": "user", "content": prompt}]
                        )
                        st.info(response.choices[0].message.content)
                    except Exception as e:
                        st.error(f"API Error: {e}")

# --- TAB 3: SUPPLIER AUDIT (AI Wire-Up) ---
with tab3:
    st.subheader("🔍 Individual Supplier Risk Audit")
    target_vendor = st.selectbox("Select a Supplier to Audit:", df['Supplier'].unique())
    
    if target_vendor:
        v_data = df[df['Supplier'] == target_vendor].iloc[0]
        st.markdown(f"## Supplier Profile: {target_vendor}")
        
        a1, a2, a3, a4 = st.columns(4)
        a1.metric("Risk Score", f"{v_data['Calculated_Risk']}/10")
        a2.metric("Revenue Impact", f"₹ {v_data['Value_at_Risk_Cr']:.2f} Cr")
        a3.metric("Component", v_data['Component'])
        a4.metric("Location", v_data['Location'])

        st.markdown("---")
        st.markdown("### 🛡️ Contingency & Switching Plan")
        
        alt_name = v_data.get('Alternate_Supplier', 'No Alternate Listed')
        alt_loc = v_data.get('Alternate_Location', 'Unknown')
        raw_markup = v_data.get('Switch_Cost_Markup', 0)
        try:
            markup_pct = float(str(raw_markup).replace('%', '').strip())
        except ValueError:
            markup_pct = 0.0
            
        est_switch_cost = (v_data['Value_at_Risk_Cr'] * (markup_pct / 100)).round(2)

        c_col1, c_col2 = st.columns(2)
        with c_col1:
            st.write(f"**Recommended Backup:** {alt_name} ({alt_loc})")
        with c_col2:
            st.write(f"**Switching Markup:** {markup_pct}%")
            st.error(f"**Estimated Switching Cost:** ₹ {est_switch_cost:.2f} Cr")

        if st.button(f"Generate AI Health Profile for {target_vendor}", type="primary"):
            if not api_key:
                st.error("Please configure API Key.")
            else:
                with st.spinner(f"Auditing {target_vendor} via AI reasoning..."):
                    try:
                        client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
                        audit_prompt = f"""
                        Perform a 'Red-Team' audit on {target_vendor}.
                        - Component: {v_data['Component']}
                        - Location: {v_data['Location']}
                        - Revenue at Risk: ₹ {v_data['Value_at_Risk_Cr']} Cr
                        - Contingency: Switch to {alt_name} in {alt_loc} with a {markup_pct}% markup.
                        
                        Provide:
                        1. A brief 'Vulnerability Assessment' for this supplier.
                        2. An evaluation of the contingency plan—is the {markup_pct}% markup justified?
                        3. A 'Go/No-Go' recommendation for diversifying this node.
                        """
                        response = client.chat.completions.create(
                            model="llama-3.1-8b-instant", 
                            messages=[{"role": "user", "content": audit_prompt}]
                        )
                        st.success("Audit Complete!")
                        st.info(response.choices[0].message.content)
                    except Exception as e:
                        st.error(f"API Error: {e}")