# Insights Module

Drop your insights code in here. The dashboard expects a function with this signature:

```python
def generate_insights(metrics: dict, date_range: tuple) -> str:
    ...
```

It should return a markdown string. The Insights tab will pass it directly to `st.markdown`.
