"""Yahoo -> NBA.com team abbreviations.

A 2026-09-26 probe found Yahoo's editorial_team_abbr identical to NBA.com's TEAM_ABBREVIATION for all
30 teams, so no translations are needed today. Add an entry if build_id_map.py reports an unknown
Yahoo team."""

YAHOO_TO_NBA: dict[str, str] = {}


def to_nba_team(abbr: str) -> str:
    return YAHOO_TO_NBA.get(abbr, abbr)
