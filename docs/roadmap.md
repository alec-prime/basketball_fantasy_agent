# Roadmap

MVP: a chatbot (Claude, via a local MCP server) that I can query during a live Yahoo draft to find
undrafted players and see their past-season stats, in the context of my league's settings and Yahoo ADP. Each sub-project gets spec → plan → implementation.

| # | Sub-project | Delivers | Spec | Status |
|---|---|---|---|---|
| 0 | Live-picks spike | proof that picks can be polled by room ID | `specs/2026-08-10-draft-room-by-id-spike-design.md` | done |
| 1 | Player ID map | `data/player_id_map.csv` (also the draftable pool), `yahoo_client`, package skeleton | `specs/2026-09-25-yahoo-nba-player-id-map-design.md` (+ `yahoo_position` amendment in the MVP spec) | spec approved |
| 2 | Stats cache | 3 regular seasons + 2026-27 preseason season lines; 2025-26 and preseason game logs | `specs/2026-09-26-draft-chat-mvp-design.md` | spec in review |
| 3 | Yahoo league context | league settings (scoring type, teams, roster slots, categories) fetched when a room is set; Yahoo ADP via `scripts/pull_adp.py` | same | spec in review |
| 4 | Draft client | drafted picks for a room, fetched on demand | same | spec in review |
| 5 | MCP server | `set_draft_room`, `league_settings`, `draft_status`, `available_players`, `player_stats`, `game_logs` | same | spec in review |
| 6 | End-to-end check | a live Yahoo NBA mock draft, queried through Claude | same | — |

Spec paths are relative to `docs/superpowers/`.

## Later (parked, not MVP)

- Valuation engine: 9-cat z-scores, season blending, punt toggles
- Per-league ADP, auction values
- Rankings web UI (FastAPI)
- Recommendations: need-based picks, positional scarcity, tiers; tracking my team and opponents
