import sys
from pathlib import Path
import pandas as pd
from sklearn.pipeline import Pipeline

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import churn_analysis


def test_encode_target_column_none():
    res = churn_analysis.encode_target_column(None)
    assert isinstance(res, pd.Series)
    assert len(res) == 0


def test_generate_heuristic_target_strings():
    frame = pd.DataFrame({
        "support_tickets": ["invalid_str", "2"],
        "complaint_count": ["nan", "1"],
        "payment_delays": ["", "0"],
        "customer_satisfaction_score": ["three", "4.0"],
        "tenure_months": ["10", "12"],
        "product_usage": ["N/A", "50"],
        "contract_type": ["monthly", "annual"]
    })
    res = churn_analysis.generate_heuristic_target(frame)
    assert len(res) == 2
    assert res.tolist() == [1, 0]


def test_build_model_dynamic_inference():
    X = pd.DataFrame({
        "arbitrary_numeric": [1.0, 2.0, 3.0],
        "arbitrary_categorical": ["A", "B", "C"]
    })
    feature_cols = ["arbitrary_numeric", "arbitrary_categorical"]
    model = churn_analysis.build_model(fallback=False, feature_columns=feature_cols, X=X)
    assert isinstance(model, Pipeline)
    assert "preprocessor" in model.named_steps
