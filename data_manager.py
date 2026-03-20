import yfinance as yf
import duckdb
import pandas as pd
from datetime import datetime, timedelta
import os
from typing import Optional, Tuple, Dict
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class HistoricalDataManager:
    def __init__(self, db_path: str = "financial_data.duckdb"):
        """Initialize the historical data manager with DuckDB cache."""
        self.db_path = db_path
        self.conn = duckdb.connect(db_path)
        self._initialize_database()
        
        # Asset symbol mappings
        self.asset_symbols = {
            "S&P 500": "^GSPC",
            "NASDAQ 100": "^NDX", 
            "Gold (XAU/USD)": "GC=F",
            "Bitcoin (BTC/USD)": "BTC-USD",
            "10Y Treasury Yield": "^TNX",
            "EUR/USD": "EURUSD=X",
            "Oil (WTI)": "CL=F",
            "NSE Nifty 50": "^NSEI",
            "BSE Sensex": "^BSESN"
        }
    
    def _initialize_database(self):
        """Create the necessary tables in DuckDB."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS historical_data (
                asset_symbol VARCHAR,
                date DATE,
                open_price FLOAT,
                high_price FLOAT,
                low_price FLOAT,
                close_price FLOAT,
                volume BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (asset_symbol, date)
            )
        """)
        
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_asset_date ON historical_data(asset_symbol, date)
        """)
        
        logger.info("Database initialized successfully")
    
    def _get_symbol_for_asset(self, asset_name: str) -> str:
        """Get Yahoo Finance symbol for asset name."""
        return self.asset_symbols.get(asset_name, asset_name)
    
    def _is_data_fresh(self, asset_symbol: str, latest_date: datetime) -> bool:
        """Check if the cached data is fresh enough (less than 1 day old)."""
        # For daily data, we consider it fresh if it's from the previous trading day
        yesterday = datetime.now() - timedelta(days=1)
        return latest_date.date() >= yesterday.date()
    
    def fetch_latest_data(self, asset_name: str, force_refresh: bool = False) -> pd.DataFrame:
        """Fetch latest historical data, using cache when available."""
        asset_symbol = self._get_symbol_for_asset(asset_name)
        
        # Check if we have recent cached data
        if not force_refresh:
            cached_data = self._get_cached_data(asset_symbol)
            if cached_data is not None and not cached_data.empty:
                latest_date = pd.to_datetime(cached_data['date']).max()
                if self._is_data_fresh(asset_symbol, latest_date):
                    logger.info(f"Using fresh cached data for {asset_name} ({asset_symbol})")
                    return cached_data
        
        # Fetch new data from Yahoo Finance
        logger.info(f"Fetching fresh data for {asset_name} ({asset_symbol}) from Yahoo Finance")
        try:
            ticker = yf.Ticker(asset_symbol)
            
            # Get data for the last 2 years to ensure we have enough history
            end_date = datetime.now()
            start_date = end_date - timedelta(days=730)  # 2 years
            
            hist_data = ticker.history(start=start_date, end=end_date)
            
            if hist_data.empty:
                logger.warning(f"No data found for {asset_symbol}")
                return pd.DataFrame()
            
            # Process and store the data
            hist_data.reset_index(inplace=True)
            hist_data['asset_symbol'] = asset_symbol
            
            # Rename columns to match our schema
            hist_data = hist_data.rename(columns={
                'Date': 'date',
                'Open': 'open_price',
                'High': 'high_price', 
                'Low': 'low_price',
                'Close': 'close_price',
                'Volume': 'volume'
            })
            
            # Select only the columns we need
            hist_data = hist_data[['asset_symbol', 'date', 'open_price', 'high_price', 
                                 'low_price', 'close_price', 'volume']]
            
            # Store in database (upsert)
            self._store_data(hist_data)
            
            logger.info(f"Successfully fetched and stored {len(hist_data)} records for {asset_name}")
            return hist_data
            
        except Exception as e:
            logger.error(f"Error fetching data for {asset_name}: {str(e)}")
            # Return cached data if available as fallback
            return self._get_cached_data(asset_symbol) or pd.DataFrame()
    
    def _get_cached_data(self, asset_symbol: str) -> Optional[pd.DataFrame]:
        """Retrieve cached data from DuckDB."""
        try:
            query = """
                SELECT asset_symbol, date, open_price, high_price, low_price, close_price, volume
                FROM historical_data 
                WHERE asset_symbol = ?
                ORDER BY date DESC
            """
            result = self.conn.execute(query, [asset_symbol]).fetchdf()
            return result if not result.empty else None
        except Exception as e:
            logger.error(f"Error retrieving cached data: {str(e)}")
            return None
    
    def _store_data(self, data: pd.DataFrame):
        """Store data in DuckDB using upsert logic."""
        try:
            # Make sure created_at column is included
            if 'created_at' not in data.columns:
                data['created_at'] = datetime.now()
            
            # Select columns in the correct order
            data_to_store = data[['asset_symbol', 'date', 'open_price', 'high_price', 
                                 'low_price', 'close_price', 'volume', 'created_at']]
            
            # Delete existing records for the same dates and symbol
            self.conn.execute("""
                DELETE FROM historical_data 
                WHERE asset_symbol = ? AND date IN (SELECT unnest(?) FROM (SELECT 1))
            """, [data['asset_symbol'].iloc[0], data['date'].tolist()])
            
            # Insert new data
            self.conn.execute("INSERT INTO historical_data SELECT * FROM data_to_store")
            logger.info(f"Stored {len(data)} records in database")
            
        except Exception as e:
            logger.error(f"Error storing data: {str(e)}")
    
    def get_data_for_lookback(self, asset_name: str, lookback_period: str) -> Tuple[pd.DataFrame, Dict]:
        """Get historical data for a specific lookback period with metrics."""
        data = self.fetch_latest_data(asset_name)
        
        if data.empty:
            return data, {}
        
        # Calculate lookback period in days
        lookback_days = self._parse_lookback_period(lookback_period)
        if lookback_days is None:
            lookback_days = 365  # Default to 1 year
        
        # Filter data for the lookback period
        cutoff_date = datetime.now() - timedelta(days=lookback_days)
        data['date'] = pd.to_datetime(data['date'])
        filtered_data = data[data['date'] >= cutoff_date].copy()
        
        if filtered_data.empty:
            return filtered_data, {}
        
        # Calculate key metrics
        metrics = self._calculate_metrics(filtered_data)
        
        return filtered_data, metrics
    
    def _parse_lookback_period(self, lookback_period: str) -> Optional[int]:
        """Parse lookback period string to number of days."""
        period_map = {
            "1 Month": 30,
            "3 Months": 90,
            "6 Months": 180,
            "1 Year": 365,
            "2 Years": 730,
            "5 Years": 1825
        }
        return period_map.get(lookback_period)
    
    def _calculate_metrics(self, data: pd.DataFrame) -> Dict:
        """Calculate key financial metrics from the data."""
        if data.empty or len(data) < 2:
            return {}
        
        close_prices = data['close_price']
        
        # Calculate daily returns
        daily_returns = close_prices.pct_change().dropna()
        
        # Key metrics
        volatility = float(daily_returns.std() * (252 ** 0.5))  # Annualized volatility
        
        # Maximum drawdown using pandas
        cumulative_returns = (1 + daily_returns).cumprod()
        running_max = cumulative_returns.expanding().max()
        drawdown = (cumulative_returns - running_max) / running_max
        max_drawdown = float(drawdown.min())
        
        # Annual return (simple)
        if len(data) >= 252:
            annual_return = float((close_prices.iloc[-1] / close_prices.iloc[0]) ** (252/len(data)) - 1)
        else:
            annual_return = float((close_prices.iloc[-1] / close_prices.iloc[0]) - 1)
        
        # Sharpe ratio (assuming risk-free rate = 0)
        if volatility > 0:
            sharpe_ratio = annual_return / volatility
        else:
            sharpe_ratio = 0.0
        
        return {
            "volatility": round(volatility * 100, 2),  # Convert to percentage
            "max_drawdown": round(max_drawdown * 100, 2),  # Convert to percentage
            "annual_return": round(annual_return * 100, 2),  # Convert to percentage
            "sharpe_ratio": round(sharpe_ratio, 2)
        }
    
    def get_notable_events(self, asset_name: str, start_date: datetime, end_date: datetime) -> list:
        """Get notable market events for the period (simplified version)."""
        # This is a simplified version - in production, you might use a news API
        events = []
        
        # Add some generic major market events based on date ranges
        if start_date.year == 2022 and end_date.year == 2022:
            if start_date.month <= 2 and end_date.month >= 2:
                events.append("Russia-Ukraine conflict begins (Feb 2022)")
            if start_date.month <= 6 and end_date.month >= 6:
                events.append("Inflation concerns and Fed rate hikes (2022)")
        
        return events
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
