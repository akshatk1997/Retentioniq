CREATE TABLE IF NOT EXISTS data_sources (
    source_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS customer_churn (
    customer_id TEXT PRIMARY KEY,
    source_id TEXT,
    tenure_months INTEGER,
    monthly_charges REAL,
    total_charges REAL,
    contract_type TEXT,
    internet_service TEXT,
    payment_method TEXT,
    region TEXT,
    support_tickets INTEGER,
    payment_delays INTEGER,
    product_usage REAL,
    complaint_count INTEGER,
    customer_satisfaction_score REAL,
    churned INTEGER
);

CREATE TABLE IF NOT EXISTS churn_predictions (
    customer_id TEXT PRIMARY KEY,
    predicted_probability REAL NOT NULL,
    prediction_label TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_notes (
    note_id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
