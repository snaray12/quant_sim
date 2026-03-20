# QuantSim — Financial Market Simulation Agent

A Streamlit web app powered by Claude that runs historical-grounded financial simulations.

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set your Anthropic API key
```bash
# Option A: Environment variable (recommended)
export ANTHROPIC_API_KEY=sk-ant-...

# Option B: .streamlit/secrets.toml
# Create the file .streamlit/secrets.toml and add:
# ANTHROPIC_API_KEY = "sk-ant-..."
```

### 3. Run the app
```bash
streamlit run app.py
```

The app will open at **http://localhost:8501**

## Features
- 📈 Monte Carlo simulation paths (Bull / Base / Bear)
- 🎯 Scenario comparison with probabilities & historical analogs
- 📏 Confidence intervals (1M / 3M / 6M)
- 📋 Full analyst report grounded in historical data
- ⚠️ Key risk factors

## Assets supported
S&P 500, NASDAQ 100, Gold, Bitcoin, 10Y Treasury, EUR/USD, Oil (WTI)
