# Notebooks

Exploratory notebooks go here. Everything reproducible lives in `src/` and is driven by
`python -m src.cli ...`; notebooks should only read `data/processed/matches.parquet` and the
CSV files under `results/`.

Quick start inside a notebook:

```python
import sys; sys.path.insert(0, "..")
from src.config import load_settings
from src.data.providers import ParquetHistoricalProvider
df = ParquetHistoricalProvider(load_settings("../config/settings.yaml")).load()
```
