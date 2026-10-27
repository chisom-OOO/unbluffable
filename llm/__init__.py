"""Model integration: Meta client, strict extraction, record/replay, scoring.

Replay is the default (LLM_MODE=replay) and needs no key; LLM_MODE=live calls
the backend chosen by LLM_BACKEND (meta_api; open_weights is a stub)."""
