import streamlit as st
import litellm
import json
import plotly.graph_objects as go
import os
import re
from datetime import datetime
from data_manager import HistoricalDataManager


# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="QuantSim — Financial Simulation Agent",
    page_icon="📈",
    layout="wide",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
def load_css():
    with open("styles.scss", "r") as f:
        css_content = f.read()
    st.markdown(f"<style>{css_content}</style>", unsafe_allow_html=True)

load_css()


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_client():
    """Return LiteLLM client using API key from env."""
    api_key = os.environ.get("AI_API_KEY") or st.secrets.get("AI_API_KEY", "")
    if not api_key:
        st.error("⚠️  `AI_API_KEY` not found. Set it as an environment variable and restart.")
        st.stop()
    return api_key


def run_simulation(asset, horizon, lookback, regime, context_text) -> dict:
    """Call LLM with a strict simulation system prompt and real historical data, return parsed JSON."""
    api_key = get_client()
    
    # Initialize data manager and fetch real historical data
    data_manager = HistoricalDataManager()
    
    try:
        # Get historical data and metrics for the specified lookback period
        historical_data, metrics = data_manager.get_data_for_lookback(asset, lookback)
        
        if historical_data.empty:
            st.error(f"Unable to fetch historical data for {asset}. Please try again.")
            return {}
        
        # Format historical data for the prompt
        historical_data_text = format_historical_data_for_prompt(historical_data, metrics)
        
        # Load system prompt from file
        with open("system_prompt.md", "r") as f:
            system_prompt = f.read().strip()

        # Load user prompt template and format with variables including historical data
        with open("user_prompt_template.md", "r") as f:
            user_prompt_template = f.read().strip()
        
        user_prompt = user_prompt_template.format(
            asset=asset,
            horizon=horizon,
            lookback=lookback,
            regime=regime,
            context_text=context_text or 'None',
            historical_data=historical_data_text
        )

        response = litellm.completion(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            api_key=api_key,
            max_tokens=2000,
        )

        raw = response.choices[0].message.content
        clean = re.sub(r"```json|```", "", raw).strip()
        result = json.loads(clean)
        
        # Add the real data source information to the result
        if "data_sources" in result:
            result["data_sources"].update({
                "primary_source": "Yahoo Finance API (real-time data)",
                "data_period": f"{historical_data['date'].min().strftime('%b %Y')} to {historical_data['date'].max().strftime('%b %Y')}",
                "data_points": len(historical_data),
                "key_metrics": metrics
            })
        
        return result
        
    finally:
        data_manager.close()


def format_historical_data_for_prompt(data, metrics) -> str:
    """Format historical data for inclusion in the AI prompt."""
    if data.empty:
        return "No historical data available."
    
    # Get the most recent data points (last 30 days for brevity in prompt)
    recent_data = data.tail(30).copy()
    
    # Format the data
    data_text = f"Historical Price Data ({len(data)} total data points, showing last 30 days):\n\n"
    data_text += "Date        | Open     | High     | Low      | Close    | Volume\n"
    data_text += "-" * 65 + "\n"
    
    for _, row in recent_data.iterrows():
        data_text += f"{row['date'].strftime('%Y-%m-%d')} | ${row['open_price']:7.2f} | ${row['high_price']:7.2f} | ${row['low_price']:7.2f} | ${row['close_price']:7.2f} | {row['volume']:8,}\n"
    
    data_text += f"\nCalculated Metrics from Full Dataset:\n"
    data_text += f"- Volatility: {metrics.get('volatility', 'N/A')}%\n"
    data_text += f"- Max Drawdown: {metrics.get('max_drawdown', 'N/A')}%\n"
    data_text += f"- Annual Return: {metrics.get('annual_return', 'N/A')}%\n"
    data_text += f"- Sharpe Ratio: {metrics.get('sharpe_ratio', 'N/A')}\n"
    
    # Add some statistical insights
    close_prices = data['close_price']
    data_text += f"\nStatistical Summary:\n"
    data_text += f"- Price Range: ${close_prices.min():.2f} - ${close_prices.max():.2f}\n"
    data_text += f"- Average Price: ${close_prices.mean():.2f}\n"
    data_text += f"- Most Recent Price: ${close_prices.iloc[-1]:.2f}\n"
    
    return data_text


def build_chart(result: dict, asset: str) -> go.Figure:
    labels = result["chart"]["labels"]
    fig = go.Figure()

    # Shaded band between bear and bull
    fig.add_trace(go.Scatter(
        x=labels + labels[::-1],
        y=result["chart"]["bull"] + result["chart"]["bear"][::-1],
        fill="toself",
        fillcolor="rgba(61,127,255,0.07)",
        line=dict(color="rgba(255,255,255,0)"),
        hoverinfo="skip",
        showlegend=False,
    ))

    colors = {"Bull Case": "#00e5a0", "Base Case": "#3d7fff", "Bear Case": "#ff6b4a"}
    widths = {"Bull Case": 1.8, "Base Case": 2.5, "Bear Case": 1.8}
    dashes  = {"Bull Case": "dot", "Base Case": "solid", "Bear Case": "dot"}

    for key, data_key in [("Bull Case","bull"),("Base Case","base"),("Bear Case","bear")]:
        fig.add_trace(go.Scatter(
            x=labels,
            y=result["chart"][data_key],
            mode="lines",
            name=key,
            line=dict(color=colors[key], width=widths[key], dash=dashes[key]),
        ))

    fig.update_layout(
        paper_bgcolor="#0a0c10",
        plot_bgcolor="#0a0c10",
        font=dict(family="DM Mono", color="#5a6179", size=11),
        legend=dict(bgcolor="#111318", bordercolor="#1e2230", borderwidth=1),
        margin=dict(l=10, r=10, t=30, b=10),
        title=dict(text=f"{asset} — Simulated Paths", font=dict(family="Syne", size=14, color="#e8ecf5")),
        xaxis=dict(gridcolor="#1e2230", linecolor="#1e2230", tickfont=dict(size=10)),
        yaxis=dict(gridcolor="#1e2230", linecolor="#1e2230", tickfont=dict(size=10)),
        hovermode="x unified",
    )
    return fig


def confidence_bar_html(ci: dict) -> str:
    low, high, median = ci["low"], ci["high"], ci["median"]
    span = high - low or 1
    median_pct = max(0, min(100, (median - low) / span * 100))
    fill_color = "#00e5a0" if median >= 0 else "#ff6b4a"
    marker_color = fill_color
    fill_left = max(0, (0 - low) / span * 100)
    fill_width = abs(median / span * 100)

    return f"""
<div style="margin-bottom:16px">
  <div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:5px">
    <span style="color:#e8ecf5">{ci['label']}</span>
    <span style="color:#5a6179">{low}% → {high}% &nbsp;·&nbsp;
      median <span style="color:{fill_color}">{'+' if median>=0 else ''}{median}%</span>
      &nbsp;·&nbsp; <span style="color:#f5c542">{ci['confidence']}% conf.</span>
    </span>
  </div>
  <div style="background:#1e2230;border-radius:4px;height:8px;position:relative">
    <div style="position:absolute;left:{fill_left:.1f}%;width:{fill_width:.1f}%;
                height:100%;background:{fill_color}33;border-radius:4px"></div>
    <div style="position:absolute;left:{median_pct:.1f}%;transform:translateX(-50%);
                width:3px;height:16px;top:-4px;background:{marker_color};border-radius:2px"></div>
  </div>
</div>"""


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown('<p style="font-family:Syne;font-size:22px;font-weight:800;color:#00e5a0;margin-bottom:2px">Quant<span style="color:#e8ecf5">Sim</span></p>', unsafe_allow_html=True)
    st.markdown('<p style="font-size:10px;letter-spacing:2px;color:#5a6179">AI SIMULATION AGENT</p>', unsafe_allow_html=True)
    st.divider()

    asset = st.selectbox("Asset / Market", [
        "S&P 500", "NASDAQ 100", "Gold (XAU/USD)",
        "Bitcoin (BTC/USD)", "10Y Treasury Yield", "EUR/USD", "Oil (WTI)",
        "NSE Nifty 50", "BSE Sensex",
    ])
    horizon = st.selectbox("Simulation Horizon", ["1 Month", "3 Months", "6 Months", "1 Year"])
    lookback = st.selectbox("Historical Lookback", ["3 Months", "6 Months", "1 Year", "5 Years", "10 Years", "20 Years", "30+ Years (full cycle)"])
    regime = st.selectbox("Market Regime", [
        "Current Macro Conditions", "Rising Rate Environment",
        "Recessionary", "Bull Market", "High Volatility / Crisis",
    ])
    context_text = st.text_area("Custom Context (optional)",
        placeholder="e.g. Fed pivot expected, earnings season, geopolitical risk…",
        height=90)

    st.divider()
    run = st.button("▶  RUN SIMULATION", use_container_width=True, type="primary")

    st.markdown("""
<div style="font-size:10px;color:#3a3f55;margin-top:16px;line-height:1.8">
Agent reasoning chain:<br>
① Anchor to historical data<br>
② Identify volatility & trends<br>
③ Map regime to analogs<br>
④ Monte Carlo simulation<br>
⑤ Scenarios + confidence
</div>""", unsafe_allow_html=True)


# ── Main area ─────────────────────────────────────────────────────────────────

st.markdown('<h1 style="font-family:Syne;font-size:26px;font-weight:800;color:#e8ecf5;margin-bottom:4px">Financial Market Simulation</h1>', unsafe_allow_html=True)
st.markdown(f'<p style="font-size:11px;color:#5a6179;letter-spacing:1px">HISTORICAL-GROUNDED · AI AGENT · {asset.upper()}</p>', unsafe_allow_html=True)
st.divider()

if not run:
    st.markdown("""
<div style="text-align:center;padding:80px 20px;color:#3a3f55">
  <div style="font-size:48px;margin-bottom:16px">📊</div>
  <div style="font-family:Syne;font-size:16px;color:#5a6179;margin-bottom:8px">Configure & Run a Simulation</div>
  <div style="font-size:12px">Set parameters in the sidebar and click <strong style="color:#00e5a0">RUN SIMULATION</strong></div>
</div>""", unsafe_allow_html=True)
    st.stop()

# ── Run simulation ────────────────────────────────────────────────────────────

thinking_placeholder = st.empty()
thinking_steps = [
    f"🔍 Anchoring to {lookback} of {asset} historical data…",
    f"📈 Extracting volatility, trend & seasonality patterns…",
    f"🔗 Mapping '{regime}' to historical analogs…",
    f"🎲 Running Monte Carlo simulation for {horizon}…",
    f"📊 Computing scenario distributions & confidence intervals…",
    f"✍️  Generating analyst report…",
]

with thinking_placeholder.container():
    st.markdown("**// Agent Reasoning**")
    steps_html = "".join(f'<div style="margin-bottom:4px">· {s}</div>' for s in thinking_steps)
    st.markdown(f'<div class="thinking-box">{steps_html}</div>', unsafe_allow_html=True)

with st.spinner("Simulating…"):
    try:
        result = run_simulation(asset, horizon, lookback, regime, context_text)
    except json.JSONDecodeError as e:
        st.error(f"Failed to parse simulation output: {e}")
        st.stop()
    except Exception as e:
        st.error(f"Simulation error: {e}")
        st.stop()

thinking_placeholder.empty()

# ── Create tabs for different views ───────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["📊 Simulation Results", "🔍 Data Transparency", "📋 Technical Details"])

with tab1:
    # ── Original simulation results ──
    
    # ── Row 1: key metrics ──
    conf_color = "#00e5a0" if result["confidence_score"] >= 75 else "#f5c542" if result["confidence_score"] >= 55 else "#ff6b4a"
    base_ret = next((s["return"] for s in result["scenarios"] if "Base" in s["name"]), "—")
    ret_color = "#00e5a0" if "+" in str(base_ret) else "#ff6b4a"

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(f'<div class="metric-card"><div class="metric-label">Asset</div><div class="metric-value" style="color:#3d7fff;font-size:18px">{asset}</div></div>', unsafe_allow_html=True)
    with m2:
        st.markdown(f'<div class="metric-card"><div class="metric-label">Base Case Return</div><div class="metric-value" style="color:{ret_color}">{base_ret}</div></div>', unsafe_allow_html=True)
    with m3:
        st.markdown(f'<div class="metric-card"><div class="metric-label">Model Confidence</div><div class="metric-value" style="color:{conf_color}">{result["confidence_score"]}/100</div></div>', unsafe_allow_html=True)
    with m4:
        st.markdown(f'<div class="metric-card"><div class="metric-label">Data Quality</div><div class="metric-value" style="color:#00e5a0;font-size:18px">{result["data_quality"]}</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Row 2: Chart + Scenarios ──
    col_chart, col_scen = st.columns([3, 2])

    with col_chart:
        st.markdown("**📈 Monte Carlo Simulation Paths**")
        fig = build_chart(result, asset)
        st.plotly_chart(fig, use_container_width=True)

    with col_scen:
        st.markdown("**🎯 Scenario Comparison**")
        for s in result["scenarios"]:
            is_pos = "+" in str(s["return"])
            is_neg = "-" in str(s["return"])
            val_color = "#00e5a0" if is_pos else "#ff6b4a" if is_neg else "#f5c542"
            dot_color = "#00e5a0" if "Bull" in s["name"] else "#ff6b4a" if "Bear" in s["name"] else "#3d7fff"
            st.markdown(f"""
<div class="scenario-row">
  <div style="width:10px;height:10px;border-radius:50%;background:{dot_color};flex-shrink:0"></div>
  <div style="flex:1">
    <div style="font-family:Syne;font-size:13px;font-weight:700;color:#e8ecf5">{s['name']}</div>
    <div style="font-size:11px;color:#5a6179;margin-top:2px">{s['rationale']}</div>
  </div>
  <div style="text-align:right;flex-shrink:0">
    <div style="font-size:18px;font-weight:700;color:{val_color};font-family:Syne">{s['return']}</div>
    <div style="font-size:10px;color:#f5c542">{s['probability']}% prob.</div>
  </div>
</div>""", unsafe_allow_html=True)

    st.divider()

    # ── Row 3: Confidence Intervals + Key Risks ──
    col_ci, col_risks = st.columns([3, 2])

    with col_ci:
        st.markdown("**📏 Confidence Intervals**")
        ci_html = "".join(confidence_bar_html(ci) for ci in result["confidence_intervals"])
        st.markdown(f'<div style="background:#111318;border:1px solid #1e2230;border-radius:10px;padding:20px">{ci_html}</div>', unsafe_allow_html=True)

    with col_risks:
        st.markdown("**⚠️ Key Risks**")
        risks_html = "".join(
            f'<div style="background:#111318;border:1px solid #1e2230;border-left:3px solid #ff6b4a;border-radius:0 8px 8px 0;padding:10px 14px;margin-bottom:8px;font-size:12px;color:#c8cfe0">{r}</div>'
            for r in result.get("key_risks", [])
        )
        st.markdown(risks_html, unsafe_allow_html=True)

    st.divider()

    # ── Row 4: Analyst Report ──
    st.markdown("**📋 Analyst Report**")

    tags_html = " ".join(f'<span class="tag">{t}</span>' for t in result.get("tags", []))
    st.markdown(f'<div style="margin-bottom:14px">{tags_html}</div>', unsafe_allow_html=True)

    paragraphs = result["summary"].split("\n\n")
    report_html = "".join(f"<p style='margin-bottom:12px'>{p}</p>" for p in paragraphs)
    st.markdown(f'<div class="report-text" style="background:#111318;border:1px solid #1e2230;border-radius:10px;padding:24px">{report_html}</div>', unsafe_allow_html=True)

    st.markdown(f"""
<div style="display:flex;justify-content:space-between;font-size:10px;color:#3a3f55;margin-top:10px;letter-spacing:0.5px">
  <span>QUANTSIM · AI SIMULATION AGENT</span>
  <span>HORIZON: {horizon.upper()} · LOOKBACK: {lookback.upper()}</span>
  <span>NOT FINANCIAL ADVICE</span>
</div>""", unsafe_allow_html=True)

with tab2:
    # ── Data Transparency Tab ──
    st.markdown("**🔍 Data Sources & Transparency**")
    st.markdown("This section provides complete transparency about the data sources and historical information used in this simulation.")
    
    if "data_sources" in result:
        data_sources = result["data_sources"]
        
        # Data Source Information
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.markdown("**📊 Primary Data Source**")
            st.markdown(f'<div style="background:#111318;border:1px solid #1e2230;border-radius:8px;padding:16px;margin-bottom:16px">{data_sources.get("primary_source", "Not specified")}</div>', unsafe_allow_html=True)
            
            st.markdown("**📅 Data Period**")
            st.markdown(f'<div style="background:#111318;border:1px solid #1e2230;border-radius:8px;padding:16px;margin-bottom:16px">{data_sources.get("data_period", "Not specified")}</div>', unsafe_allow_html=True)
            
            st.markdown("**📈 Data Points**")
            st.markdown(f'<div style="background:#111318;border:1px solid #1e2230;border-radius:8px;padding:16px;margin-bottom:16px">{data_sources.get("data_points", "Not specified"):,} data points</div>', unsafe_allow_html=True)
        
        with col2:
            st.markdown("**🎯 Key Metrics**")
            if "key_metrics" in data_sources:
                metrics = data_sources["key_metrics"]
                metrics_html = ""
                for key, value in metrics.items():
                    formatted_key = key.replace("_", " ").title()
                    metrics_html += f'<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #1e2230"><span>{formatted_key}</span><span style="color:#00e5a0;font-weight:600">{value}</span></div>'
                st.markdown(f'<div style="background:#111318;border:1px solid #1e2230;border-radius:8px;padding:16px">{metrics_html}</div>', unsafe_allow_html=True)
        
        # Notable Events
        if "notable_events" in data_sources:
            st.markdown("**📅 Notable Events During Period**")
            events_html = "".join(f'<div style="background:#111318;border:1px solid #1e2230;border-left:3px solid #3d7fff;border-radius:0 8px 8px 0;padding:12px 16px;margin-bottom:8px">{event}</div>' for event in data_sources["notable_events"])
            st.markdown(events_html, unsafe_allow_html=True)
    else:
        st.warning("Data source information not available in this simulation result.")
    
    # Data Quality Assessment
    st.markdown("**🔍 Data Quality Assessment**")
    quality_score = result.get("confidence_score", 0)
    quality_level = "HIGH" if quality_score >= 75 else "MEDIUM" if quality_score >= 55 else "LOW"
    quality_color = "#00e5a0" if quality_score >= 75 else "#f5c542" if quality_score >= 55 else "#ff6b4a"
    
    st.markdown(f"""
<div style="background:#111318;border:1px solid #1e2230;border-radius:10px;padding:20px">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
    <span style="font-family:Syne;font-size:18px;font-weight:700">Overall Data Quality</span>
    <span style="color:{quality_color};font-family:Syne;font-size:24px;font-weight:800">{quality_level}</span>
  </div>
  <div style="background:#1e2230;border-radius:4px;height:8px;position:relative">
    <div style="background:{quality_color};height:100%;border-radius:4px;width:{quality_score}%"></div>
  </div>
  <div style="text-align:center;margin-top:8px;color:#5a6179;font-size:12px">Confidence Score: {quality_score}/100</div>
</div>""", unsafe_allow_html=True)

with tab3:
    # ── Technical Details Tab ──
    st.markdown("**📋 Technical Details**")
    st.markdown("Complete technical information about this simulation run.")
    
    # Simulation Parameters
    st.markdown("**⚙️ Simulation Parameters**")
    params_html = f"""
<div style="background:#111318;border:1px solid #1e2230;border-radius:8px;padding:16px">
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
    <div><strong>Asset:</strong> {asset}</div>
    <div><strong>Horizon:</strong> {horizon}</div>
    <div><strong>Lookback:</strong> {lookback}</div>
    <div><strong>Regime:</strong> {regime}</div>
  </div>
</div>"""
    st.markdown(params_html, unsafe_allow_html=True)
    
    # Model Configuration
    st.markdown("**🤖 Model Configuration**")
    model_html = """
<div style="background:#111318;border:1px solid #1e2230;border-radius:8px;padding:16px">
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
    <div><strong>Model:</strong> GPT-4 via LiteLLM</div>
    <div><strong>Max Tokens:</strong> 2000</div>
    <div><strong>Temperature:</strong> 0 (deterministic)</div>
    <div><strong>Response Format:</strong> JSON</div>
  </div>
</div>"""
    st.markdown(model_html, unsafe_allow_html=True)
    
    # Raw JSON Response
    st.markdown("**📄 Raw Response Data**")
    with st.expander("View complete JSON response"):
        st.json(result)
