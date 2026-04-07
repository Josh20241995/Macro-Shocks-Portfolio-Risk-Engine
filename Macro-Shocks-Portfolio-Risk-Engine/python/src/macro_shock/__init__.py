# python/src/macro_shock/__init__.py
"""
Macro Shock Risk Engine
=======================
Institutional-grade asymmetric policy event risk detection and portfolio response.

Modules:
  event_detection  — Event classification, calendar, gap corridor detection
  nlp              — Language intelligence, hawkish/dovish scoring, surprise vector
  market_context   — Market state ingestion and vulnerability scoring
  scenario_engine  — Probability-weighted scenario tree construction
  risk_scoring     — Composite and sub-component risk scoring
  portfolio_impact — Asset-class-specific hedge and exposure recommendations
  backtesting      — Historical event study and walk-forward validation
  monitoring       — Alerting, audit trail, heartbeat monitoring
  execution        — OMS interface, pre-trade checks, kill switch
  data             — Ingestion, validation, synthetic data
  orchestration    — End-to-end pipeline orchestration
"""

__version__ = "1.0.0"
__author__ = "Quantitative Research & Risk Engineering"
