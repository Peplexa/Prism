"""
Player name extraction from text.

Identifies player names mentioned in summary text by matching against
the full box score roster.
"""
from __future__ import annotations

import re
from typing import Set


class PlayerNameExtractor:
    """
    Extract player names mentioned in text by matching against a known roster.

    This uses a roster-based approach rather than NER because:
    1. We have the full roster from the box score
    2. Player name formats vary (first name, last name, full name)
    3. NER models may miss sports-specific name variations
    """

    def __init__(self, roster: list[str]):
        """
        Initialize with a list of full player names from the box score.

        Args:
            roster: List of player names (e.g., ["LeBron James", "Anthony Davis"])
        """
        self.roster = roster
        self._build_name_index()

    def _build_name_index(self):
        """Build lookup indices for different name formats."""
        self.full_names = set()
        self.last_names: dict[str, list[str]] = {}
        self.first_names: dict[str, list[str]] = {}

        for full_name in self.roster:
            if not full_name or full_name == "N/A":
                continue
            self.full_names.add(full_name.lower())

            parts = full_name.split()
            if len(parts) >= 2:
                first_name = parts[0].lower()
                last_name = parts[-1].lower()

                # Index by last name (more unique in sports writing)
                if last_name not in self.last_names:
                    self.last_names[last_name] = []
                self.last_names[last_name].append(full_name)

                # Index by first name (for disambiguation)
                if first_name not in self.first_names:
                    self.first_names[first_name] = []
                self.first_names[first_name].append(full_name)

    def extract_mentioned_players(self, text: str) -> Set[str]:
        """
        Extract player names mentioned in the text.

        Args:
            text: The summary text to search

        Returns:
            Set of full player names that are mentioned
        """
        text_lower = text.lower()
        mentioned: Set[str] = set()

        # Check for full names first (most reliable)
        for full_name_lower in self.full_names:
            if full_name_lower in text_lower:
                # Find the original case version
                for name in self.roster:
                    if name.lower() == full_name_lower:
                        mentioned.add(name)
                        break

        # Check for last names (common in sports writing)
        words = set(re.findall(r"\b[A-Za-z]+\b", text))
        words_lower = {w.lower() for w in words}

        for last_name, full_names in self.last_names.items():
            if last_name in words_lower:
                # If unique last name, add the player
                if len(full_names) == 1:
                    mentioned.add(full_names[0])
                else:
                    # Multiple players with same last name - check context
                    for full_name in full_names:
                        if full_name.lower() in text_lower:
                            mentioned.add(full_name)

        return mentioned


def get_roster_from_box_score(box_score: dict) -> list[str]:
    """
    Extract the roster (list of player names) from a box score.

    Args:
        box_score: The box_score dict from reference_content

    Returns:
        List of player names
    """
    players = []
    player_names = box_score.get("PLAYER_NAME", {})

    if isinstance(player_names, dict):
        for idx, name in player_names.items():
            if name and name != "N/A":
                players.append(name)

    return players
