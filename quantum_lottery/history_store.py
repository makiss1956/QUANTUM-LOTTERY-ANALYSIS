"""
Αποθετήριο Ιστορικού Προβλέψεων (History Store)
===============================================

Κρατά ΜΟΝΙΜΟ αρχείο καταγραφής όλων των προβλέψεων και συγκρίσεων σε μορφή
JSONL (μία καταχώρηση ανά γραμμή). Από εδώ βγάζουμε αργότερα στατιστικά
επιτυχίας ανά κινητήρα/σκελετό — αυτό ακριβώς το «καθαρό ιστορικό» που
επιτρέπει περιοδικές βελτιώσεις και διορθώσεις του μοντέλου.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, List

from quantum_lottery.logger_setup import get_logger
from quantum_lottery.settings import PREDICTIONS_JSONL

log = get_logger("HistoryStore")


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def append_event(event: Dict) -> None:
    """Προσθέτει ένα γεγονός (πρόβλεψη/σύγκριση/email) στο JSONL log."""
    event = {"ts": _now_iso(), **event}
    try:
        with PREDICTIONS_JSONL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        log.info("Καταχώρηση ιστορικού: %s", event.get("type", "?"))
    except OSError as exc:
        log.error("Δεν μπόρεσα να γράψω στο ιστορικό: %s", exc)


def read_events() -> List[Dict]:
    """Επιστρέφει όλα τα γεγονότα του ιστορικού."""
    if not PREDICTIONS_JSONL.exists():
        return []
    out: List[Dict] = []
    for line in PREDICTIONS_JSONL.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def pending_predictions() -> List[Dict]:
    """Οι προβλέψεις που δεν έχουν ακόμα συγκριθεί με πραγματική κλήρωση.

    Αν υπάρχουν πολλές προβλέψεις για το ίδιο target_date (π.χ. τρέξε
    `predict` δύο φορές πριν την κλήρωση), κρατάμε ΜΟΝΟ την τελευταία,
    ώστε καμία κλήρωση να μην καταμετρηθεί διπλά στα στατιστικά.
    """
    done_targets = {e["target_date"] for e in read_events() if e.get("type") == "comparison"}
    last_by_target: Dict[str, Dict] = {}
    for e in read_events():
        if (e.get("type") == "prediction" and e["target_date"] not in done_targets):
            last_by_target[e["target_date"]] = e  # η νεότερη νικά (σωστό JSONL διαβάζεται με σειρά)
    return sorted(last_by_target.values(), key=lambda e: e["target_date"])


def lifetime_stats() -> Dict:
    """
    Συγκεντρωτικά στατιστικά επιτυχίας ανά κινητήρα/σκελετό:
    πλήθος βραβείων ανά κατηγορία και συνολικές συμμετοχές.

    Κάθε comparison event κουβαλεί τα αποτελέσματα μέσα στο πεδίο «results»
    (λίστα από compare_prediction().to_dict()) — μετράμε ΚΑΘΕ μία συμμετοχή.
    """
    counters: Dict[str, Dict[str, int]] = {}
    tickets: Dict[str, int] = {}
    for e in read_events():
        if e.get("type") != "comparison":
            continue
        items = e.get("results") or ([e] if "engine" in e else [])
        for r in items:
            key = f"{r['engine']}-{r['skeleton']}"
            tickets[key] = tickets.get(key, 0) + 1
            bucket = counters.setdefault(key, {})
            tier = r.get("tier") or "none"
            bucket[tier] = bucket.get(tier, 0) + 1
    return {"tickets": tickets, "tiers": counters}
