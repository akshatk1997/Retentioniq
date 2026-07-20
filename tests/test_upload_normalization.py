import pandas as pd

from churn_analysis import load_config, normalize_customer_frame


def test_normalize_customer_frame_auto_maps_aliases_and_target_values():
    config = load_config()
    frame = pd.DataFrame(
        {
            "customer_id": ["C001"],
            "tenure": [12],
            "monthly_charge": [49.5],
            "total_charge": [594.0],
            "contract": ["Month-to-month"],
            "internet": ["Fiber optic"],
            "payment": ["Credit card"],
            "region": ["North"],
            "support_calls": [4],
            "late_payments": [2],
            "usage": [30.0],
            "complaints": [3],
            "satisfaction": [2.1],
            "status": ["Churned"],
        }
    )

    normalized = normalize_customer_frame(frame, include_target=True, config=config)

    assert normalized.loc[0, "tenure_months"] == 12
    assert normalized.loc[0, "monthly_charges"] == 49.5
    assert normalized.loc[0, "contract_type"] == "Month-to-month"
    assert normalized.loc[0, "churned"] == 1
