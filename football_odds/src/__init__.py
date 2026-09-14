"""Football odds similarity analysis system.

Package layout:
    src.data      - Football-Data download/cache, column mapping, processed database, quality report
    src.features  - odds normalisation, consensus, feature vectors
    src.models    - similarity engine, statistics, shrinkage, signal
    src.backtest  - walk-forward backtest, metrics, ROI simulation, bucket analyses
    src.pipeline  - today's matches pipeline
    src.dashboard - Streamlit app
"""

__version__ = "0.1.0"
