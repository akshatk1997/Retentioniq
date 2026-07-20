# AI Churn Prediction Model Tool

This project is a configurable customer churn prediction workflow built with Python, SQLite, and scikit-learn. It is designed so a company can adapt the model to its own customer data, business rules, retention actions, and churn-risk thresholds.

## What this version supports
- Initializes a SQLite database for customer churn analysis
- Imports customer data from CSV files
- Trains a churn model using business-relevant features
- Predicts churn probability for future or existing customers
- Stores outputs in SQL and generates business-friendly summaries
- Uses a JSON configuration file so the workflow can be edited for different companies

## Company-editable configuration
The file [config/company_config.json](config/company_config.json) controls:
- feature columns used by the model
- numeric versus categorical variables
- churn-risk threshold
- label names such as high_risk and low_risk
- retention actions for each predicted segment
- default values for missing categorical fields

## Built-in AI insights (free, no API key)
The dashboard generates a natural-language retention narrative and per-segment
breakdowns from your prediction data using an **offline generator** — no network,
no API key, and it never fails. To upgrade to a free local LLM, install
[Ollama](https://ollama.com) and pull a model, then enable it in the config:

```bash
ollama pull llama3.2
```

```json
"ollama": { "base_url": "http://localhost:11434", "model": "llama3.2", "enabled": true }
```

When enabled, the endpoint asks the local model to enrich the summary and
gracefully falls back to the offline generator if Ollama is unavailable.

## Setup
```bash
python -m pip install -r requirements.txt
```

## Quick start
```bash
python churn_analysis.py init
python churn_analysis.py train --config config/company_config.json
python churn_analysis.py predict data/new_customers.csv --config config/company_config.json
python churn_analysis.py report --config config/company_config.json
```

## Web dashboard
```bash
python app.py
```
Then open http://127.0.0.1:5000/ in your browser.

Use the upload control to analyze your own company CSV data and view churn predictions instantly.

## Commands
- `init`: creates the database and seeds sample data
- `import <csv_path>`: imports customer data into SQL using your configured fields
- `train`: trains the model and stores it in artifacts/churn_model.pkl
- `predict <csv_path>`: scores a CSV file and saves predictions to SQL
- `report`: shows the latest churn prediction summary with recommended actions

## Recommended company data fields
A real company dataset should ideally include:
- customer_id
- tenure_months
- monthly_charges
- total_charges
- contract_type
- internet_service
- payment_method
- region
- churned (historical target label)

You can add more fields such as support_tickets, usage_frequency, complaint_count, or account_age if they are relevant to your business.
