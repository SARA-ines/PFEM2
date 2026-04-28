import json
from pathlib import Path

import joblib


BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / "models"
META_PATH = MODEL_DIR / "classifier_meta.json"
MODULE_MODEL_PATH = MODEL_DIR / "module_classifier.joblib"
TYPE_MODEL_PATH = MODEL_DIR / "type_classifier.joblib"


def classifier_ready() -> bool:
    return META_PATH.exists() and MODULE_MODEL_PATH.exists() and TYPE_MODEL_PATH.exists()


def load_classifier_bundle():
    if not classifier_ready():
        return None
    try:
        metadata = json.loads(META_PATH.read_text(encoding="utf-8"))
        return {
            "meta": metadata,
            "module_model": joblib.load(MODULE_MODEL_PATH),
            "type_model": joblib.load(TYPE_MODEL_PATH),
        }
    except Exception:
        return None


def predict_labels(bundle, text: str) -> dict:
    module_model = bundle["module_model"]
    type_model = bundle["type_model"]

    module_label = module_model.predict([text])[0]
    type_label = type_model.predict([text])[0]

    module_scores = {}
    if hasattr(module_model, "predict_proba"):
        classes = list(module_model.classes_)
        probs = module_model.predict_proba([text])[0]
        module_scores = {label: round(float(prob), 4) for label, prob in zip(classes, probs)}
    else:
        module_scores[module_label] = 1.0

    type_scores = {}
    if hasattr(type_model, "predict_proba"):
        classes = list(type_model.classes_)
        probs = type_model.predict_proba([text])[0]
        type_scores = {label: round(float(prob), 4) for label, prob in zip(classes, probs)}
    else:
        type_scores[type_label] = 1.0

    return {
        "module": module_label,
        "type_incident": type_label,
        "module_scores": module_scores,
        "type_scores": type_scores,
    }
