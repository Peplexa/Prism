"""
Rotowire dataset loader.

The Rotowire dataset contains NBA game summaries paired with box score statistics.
Source: https://github.com/harvardnlp/boxscore-data
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterator

from django.conf import settings

from .base import DatasetLoader


class RotowireLoader(DatasetLoader):
    """Loads Rotowire NBA game summaries with box scores."""

    # Stat abbreviations to full names
    STAT_NAMES = {
        "PTS": "points",
        "REB": "rebounds",
        "AST": "assists",
        "STL": "steals",
        "BLK": "blocks",
        "TO": "turnovers",
        "FGM": "field goals made",
        "FGA": "field goal attempts",
        "FG3M": "three-pointers made",
        "FG3A": "three-point attempts",
        "FTM": "free throws made",
        "FTA": "free throw attempts",
        "OREB": "offensive rebounds",
        "DREB": "defensive rebounds",
        "MIN": "minutes",
    }

    # Stats to extract as facts (most commonly mentioned in summaries)
    KEY_PLAYER_STATS = ["PTS", "REB", "AST", "STL", "BLK", "FGM", "FGA", "FG3M", "FG3A"]
    KEY_TEAM_STATS = ["PTS", "REB", "AST"]

    def __init__(self, data_path: Path | None = None):
        self.data_path = data_path or settings.ROTOWIRE_DATA_PATH

    @property
    def name(self) -> str:
        return "rotowire"

    @property
    def description(self) -> str:
        return "NBA game summaries paired with box score statistics"

    def get_available_splits(self) -> list[str]:
        return ["train", "valid", "test"]

    def load(self, split: str = "train", limit: int | None = None) -> Iterator[dict[str, Any]]:
        """Load documents from Rotowire dataset."""
        file_path = self.data_path / f"{split}.json"

        if not file_path.exists():
            raise FileNotFoundError(
                f"Rotowire {split} data not found at {file_path}. "
                f"Download from https://github.com/harvardnlp/boxscore-data"
            )

        with open(file_path, "r") as f:
            data = json.load(f)

        count = 0
        for i, entry in enumerate(data):
            if limit and count >= limit:
                break

            # Extract game info
            home_team = entry.get("home_name", "")
            away_team = entry.get("vis_name", "")
            home_city = entry.get("home_city", "")
            away_city = entry.get("vis_city", "")

            yield {
                "external_id": f"{split}_{i}",
                "primary_text": " ".join(entry.get("summary", [])),
                "reference_content": {
                    "box_score": entry.get("box_score", {}),
                    "home_line": entry.get("home_line", {}),
                    "vis_line": entry.get("vis_line", {}),
                },
                "title": f"{away_city} {away_team} vs {home_city} {home_team}",
                "metadata": {
                    "home_team": home_team,
                    "away_team": away_team,
                    "home_city": home_city,
                    "away_city": away_city,
                    "day": entry.get("day", ""),
                },
            }
            count += 1

    def extract_ground_truth(self, document_data: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract ground truth facts from box scores."""
        facts = []
        ref = document_data["reference_content"]
        box_score = ref.get("box_score", {})
        home_line = ref.get("home_line", {})
        vis_line = ref.get("vis_line", {})
        metadata = document_data.get("metadata", {})

        # Extract player stats
        facts.extend(self._extract_player_facts(box_score))

        # Extract team stats
        facts.extend(
            self._extract_team_facts(
                home_line,
                metadata.get("home_city", ""),
                metadata.get("home_team", ""),
            )
        )
        facts.extend(
            self._extract_team_facts(
                vis_line,
                metadata.get("away_city", ""),
                metadata.get("away_team", ""),
            )
        )

        # Extract game outcome
        facts.extend(self._extract_game_outcome(home_line, vis_line, metadata))

        return facts

    def filter_ground_truth_to_summary(
        self,
        facts: list[dict[str, Any]],
        summary_text: str,
        box_score: dict,
    ) -> list[dict[str, Any]]:
        """
        Filter ground truth facts to only include players mentioned in the summary.

        This addresses the evaluation mismatch where summaries mention 4-7 players
        but box scores contain 20+ players. We only want to evaluate extraction
        against facts that could reasonably appear in the summary.

        Args:
            facts: List of ground truth fact dicts (with fact_type and metadata)
            summary_text: The summary text (primary_text from Document)
            box_score: The box score dict (from reference_content)

        Returns:
            Filtered list of facts for mentioned players + team/game facts
        """
        from apps.datasets.services.player_extractor import (
            PlayerNameExtractor,
            get_roster_from_box_score,
        )

        # Get roster and extract mentioned players
        roster = get_roster_from_box_score(box_score)
        extractor = PlayerNameExtractor(roster)
        mentioned_players = extractor.extract_mentioned_players(summary_text)

        # Filter facts
        filtered = []
        for fact in facts:
            metadata = fact.get("metadata", {})
            fact_type = fact.get("fact_type", "")

            # Always include team and game outcome facts
            if fact_type in ("team_stat", "game_outcome"):
                filtered.append(fact)
                continue

            # For player facts, check if player is mentioned in summary
            player_name = metadata.get("player", "")
            if player_name and player_name in mentioned_players:
                filtered.append(fact)

        return filtered

    # Number words to digits mapping
    NUMBER_WORDS = {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
        "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
        "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
        "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
        "eighteen": 18, "nineteen": 19, "twenty": 20,
    }

    def filter_ground_truth_to_stated_facts(
        self,
        facts: list[dict[str, Any]],
        summary_text: str,
        box_score: dict,
    ) -> list[dict[str, Any]]:
        """
        Filter ground truth facts to only include facts whose values are
        actually stated near the player's name in the summary text.

        Requires both the player name AND the stat value to appear within
        a proximity window in the text. This prevents false matches where
        a value like "2" appears elsewhere in the text but isn't about
        the player in question.

        Args:
            facts: List of ground truth fact dicts
            summary_text: The summary text
            box_score: The box score dict

        Returns:
            Filtered list of facts that are explicitly stated in the text
        """
        from apps.datasets.services.player_extractor import (
            PlayerNameExtractor,
            get_roster_from_box_score,
        )

        # Normalize text for matching (lowercase, handle hyphenation)
        text_lower = summary_text.lower().replace(" - ", "-")

        # Convert spelled-out numbers to digits for matching
        for word, digit in self.NUMBER_WORDS.items():
            text_lower = re.sub(rf'\b{word}\b', str(digit), text_lower)

        # Get roster and extract mentioned players
        roster = get_roster_from_box_score(box_score)
        extractor = PlayerNameExtractor(roster)
        mentioned_players = extractor.extract_mentioned_players(summary_text)

        # Build a map of player names to their text positions
        player_name_patterns = {}
        for player in mentioned_players:
            names = [player.lower()]
            parts = player.split()
            if len(parts) > 1:
                names.append(parts[-1].lower())
            player_name_patterns[player] = names

        # Build player "blocks" — text regions attributed to each player.
        # A block starts when a player is named and extends until the next
        # player is named (handles pronoun references like "He scored 17").
        all_player_names = []
        for player in mentioned_players:
            variants = player_name_patterns.get(player, [player.lower()])
            all_player_names.append((player, variants))

        # Split text into sentences for additional checking
        sentences = re.split(r'\s*\.\s+', text_lower)

        def _build_player_blocks() -> dict[str, str]:
            """Map each player to the text block(s) where they are discussed.

            Uses forward blocks (from player name to next player name) plus
            any sentence that contains the player's name. This handles both
            pronoun references ("He scored 17") and backward references
            ("paced by 23 points from Eric Bledsoe").
            """
            blocks: dict[str, list[str]] = {p: [] for p in mentioned_players}
            # Find all player name positions in text
            positions = []
            for player, variants in all_player_names:
                for variant in variants:
                    for m in re.finditer(re.escape(variant), text_lower):
                        positions.append((m.start(), player))
            positions.sort(key=lambda x: x[0])

            if not positions:
                return {p: text_lower for p in mentioned_players}

            # Forward blocks: from each player mention to the next player mention
            for i, (pos, player) in enumerate(positions):
                end = positions[i + 1][0] if i + 1 < len(positions) else len(text_lower)
                blocks[player].append(text_lower[pos:end])

            # Also include full sentences containing the player's name
            for player, variants in all_player_names:
                for sentence in sentences:
                    if any(variant in sentence for variant in variants):
                        blocks[player].append(sentence)

            return {p: " ".join(segs) for p, segs in blocks.items()}

        player_blocks = _build_player_blocks()

        def _value_near_player(player_name: str, value: int, text: str) -> bool:
            """Check if a stat value appears in a player's text block."""
            block = player_blocks.get(player_name, "")
            if not block:
                return False
            value_str = str(value)
            return bool(re.search(rf'\b{value_str}\b', block))

        def _shooting_near_player(player_name: str, made: int, attempted: int) -> bool:
            """Check if shooting stats (made/attempted) appear in player's block."""
            block = player_blocks.get(player_name, "")
            if not block:
                return False
            made_str = str(made)
            attempted_str = str(attempted)
            return (bool(re.search(rf'\b{made_str}\b', block)) and
                    bool(re.search(rf'\b{attempted_str}\b', block)))

        # Filter facts
        filtered = []
        for fact in facts:
            metadata = fact.get("metadata", {})
            fact_type = fact.get("fact_type", "")

            # Skip game outcome and team stats — our extraction focuses on players
            if fact_type in ("game_outcome", "team_stat"):
                continue

            if fact_type in ("player_stat", "player_shooting"):
                player_name = metadata.get("player", "")

                # Player must be mentioned in the summary
                if player_name not in mentioned_players:
                    continue

                if fact_type == "player_shooting":
                    made = metadata.get("made")
                    attempted = metadata.get("attempted")
                    if made is not None and attempted is not None:
                        if _shooting_near_player(player_name, made, attempted):
                            filtered.append(fact)
                else:
                    value = metadata.get("value")
                    if value is not None:
                        if _value_near_player(player_name, value, text_lower):
                            filtered.append(fact)

        return filtered

    def _extract_player_facts(self, box_score: dict) -> list[dict[str, Any]]:
        """Extract individual player statistics as facts."""
        facts = []

        # Box score is organized by stat type, then player index
        # First, restructure to get player-centric view
        players = {}
        for stat, values in box_score.items():
            if not isinstance(values, dict):
                continue
            for player_idx, value in values.items():
                if player_idx not in players:
                    players[player_idx] = {}
                players[player_idx][stat] = value

        for player_idx, stats in players.items():
            player_name = stats.get("PLAYER_NAME", "")
            if not player_name or player_name == "N/A":
                continue

            # Only extract facts for players who actually played
            minutes = stats.get("MIN", "0")
            if minutes == "0" or minutes == "N/A":
                continue

            for stat_key in self.KEY_PLAYER_STATS:
                value = stats.get(stat_key)
                if value is None or value == "N/A" or value == "":
                    continue

                try:
                    value_int = int(value)
                except (ValueError, TypeError):
                    continue

                # Skip zero values for counting stats (less informative)
                if value_int == 0 and stat_key not in ["FGM", "FGA", "FG3M", "FG3A"]:
                    continue

                stat_name = self.STAT_NAMES.get(stat_key, stat_key.lower())

                # Generate natural language fact
                if stat_key in ["FGM", "FGA"]:
                    if stat_key == "FGM":
                        fga = stats.get("FGA", "0")
                        fact_text = f"{player_name} made {value_int} of {fga} field goals"
                        facts.append({
                            "fact_text": fact_text,
                            "fact_type": "player_shooting",
                            "confidence": 1.0,
                            "metadata": {
                                "player": player_name,
                                "stat": "FG",
                                "made": value_int,
                                "attempted": int(fga) if fga != "N/A" else 0,
                            },
                        })
                elif stat_key in ["FG3M", "FG3A"]:
                    if stat_key == "FG3M":
                        fg3a = stats.get("FG3A", "0")
                        fact_text = f"{player_name} made {value_int} of {fg3a} three-pointers"
                        facts.append({
                            "fact_text": fact_text,
                            "fact_type": "player_shooting",
                            "confidence": 1.0,
                            "metadata": {
                                "player": player_name,
                                "stat": "FG3",
                                "made": value_int,
                                "attempted": int(fg3a) if fg3a != "N/A" else 0,
                            },
                        })
                else:
                    fact_text = f"{player_name} had {value_int} {stat_name}"
                    facts.append({
                        "fact_text": fact_text,
                        "fact_type": "player_stat",
                        "confidence": 1.0,
                        "metadata": {
                            "player": player_name,
                            "stat": stat_key,
                            "value": value_int,
                        },
                    })

        return facts

    def _extract_team_facts(
        self, team_line: dict, city: str, team_name: str
    ) -> list[dict[str, Any]]:
        """Extract team-level statistics as facts."""
        facts = []
        full_name = f"{city} {team_name}".strip()

        if not full_name:
            return facts

        for stat_key in self.KEY_TEAM_STATS:
            value = team_line.get(stat_key)
            if value is None or value == "N/A":
                continue

            try:
                value_int = int(value)
            except (ValueError, TypeError):
                continue

            stat_name = self.STAT_NAMES.get(stat_key, stat_key.lower())
            fact_text = f"The {full_name} had {value_int} {stat_name}"

            facts.append({
                "fact_text": fact_text,
                "fact_type": "team_stat",
                "confidence": 1.0,
                "metadata": {
                    "team": full_name,
                    "stat": stat_key,
                    "value": value_int,
                },
            })

        return facts

    def _extract_game_outcome(
        self, home_line: dict, vis_line: dict, metadata: dict
    ) -> list[dict[str, Any]]:
        """Extract game outcome facts."""
        facts = []

        home_pts = home_line.get("PTS")
        vis_pts = vis_line.get("PTS")

        if home_pts is None or vis_pts is None:
            return facts

        try:
            home_score = int(home_pts)
            vis_score = int(vis_pts)
        except (ValueError, TypeError):
            return facts

        home_name = f"{metadata.get('home_city', '')} {metadata.get('home_team', '')}".strip()
        vis_name = f"{metadata.get('away_city', '')} {metadata.get('away_team', '')}".strip()

        if home_score > vis_score:
            winner, loser = home_name, vis_name
            winner_score, loser_score = home_score, vis_score
        else:
            winner, loser = vis_name, home_name
            winner_score, loser_score = vis_score, home_score

        facts.append({
            "fact_text": f"The {winner} defeated the {loser} {winner_score}-{loser_score}",
            "fact_type": "game_outcome",
            "confidence": 1.0,
            "metadata": {
                "winner": winner,
                "loser": loser,
                "winner_score": winner_score,
                "loser_score": loser_score,
            },
        })

        # Final score fact
        facts.append({
            "fact_text": f"The final score was {winner_score}-{loser_score}",
            "fact_type": "game_outcome",
            "confidence": 1.0,
            "metadata": {
                "home_score": home_score,
                "away_score": vis_score,
            },
        })

        return facts
