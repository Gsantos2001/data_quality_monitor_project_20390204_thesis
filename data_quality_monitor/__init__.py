"""Εκπαιδευτικό εργαλείο αξιολόγησης ποιότητας δεδομένων για σύνολα δεδομένων."""
from .engine import evaluate_dataframe, run_analysis
__all__ = ["evaluate_dataframe", "run_analysis"]
__version__ = "0.1.0"
