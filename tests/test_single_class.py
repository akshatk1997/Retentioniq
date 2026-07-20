import sys
from pathlib import Path
import sqlite3
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import churn_analysis


def test_single_class_training_does_not_crash(tmp_path):
    db_path = tmp_path / "single_class.db"
    schema_path = Path(__file__).resolve().parents[1] / "sql" / "schema.sql"
    model_path = tmp_path / "single_class_model.pkl"

    # Initialize DB
    churn_analysis.ensure_database(db_path, schema_path)

    # Let's override the records with a single class target (all churned = 0)
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE customer_churn SET churned = 0")
    conn.commit()
    conn.close()

    # Train model (should fallback to DummyClassifier and not throw IndexError)
    result = churn_analysis.train_model(db_path, model_path)

    assert result["accuracy"] == 1.0  # Since all targets are 0, dummy classifier is 100% accurate
    assert model_path.exists()

    # Verify that predictions were successfully saved
    conn = sqlite3.connect(db_path)
    predictions = conn.execute("SELECT COUNT(*) FROM churn_predictions").fetchone()[0]
    labels = {row[0] for row in conn.execute("SELECT DISTINCT prediction_label FROM churn_predictions").fetchall()}
    conn.close()

    assert predictions > 0
    assert labels == {"low_risk"}
