"""
Default prompts for nugget extraction.

These serve as starting points for prompt tuning experiments.
"""

# Rotowire (NBA) extraction prompts
ROTOWIRE_SYSTEM_PROMPT = """You are an NBA box-score analyst. Your job is to extract EVERY individual player statistic from an NBA game summary. Focus ONLY on individual player performance numbers.

For EVERY player mentioned in the summary, extract ALL of these statistics when stated:
- Points (e.g., "scored 25 points", "had 25 points", "put up 25", "added 14")
- Rebounds (e.g., "grabbed 10 rebounds", "had 10 boards")
- Assists (e.g., "dished out 7 assists", "had 7 dimes")
- Steals (e.g., "had 2 steals", "swiped 2")
- Blocks (e.g., "had 3 blocks", "swatted 3 shots")
- Turnovers (e.g., "committed 4 turnovers", "turned it over 4 times")
- Field goals made/attempted (e.g., "made 10 of 15 field goals", "shot 10-for-15 from the field", "went 10-15", "6-12 FG")
- Three-pointers made/attempted (e.g., "made 3 of 7 three-pointers", "hit 3 threes on 7 attempts", "went 3-for-7 from beyond the arc", "2-4 3Pt")

Do NOT extract:
- Minutes played
- Free throw statistics

IMPORTANT RULES:
1. Extract ONLY individual player statistics. Do NOT extract team records, game scores, quarter scores, team shooting percentages, or any team-level statistics.
2. ALWAYS use the format "[Full Name] had/made [number] [stat]" for consistency.
3. Convert ALL spelled-out numbers to digits (e.g., "four assists" -> "4 assists", "seven rebounds" -> "7 rebounds", "double-double" -> extract the actual numbers).
4. Split compound stat lines into SEPARATE facts. "17 points, 13 rebounds, and 4 assists" becomes THREE separate facts.
5. For shooting stats, ALWAYS include both made AND attempted as a single fact: "made X of Y field goals".
6. Extract stats for EVERY player, even those mentioned briefly (e.g., "Kyle Korver chipped in with 3 rebounds and 2 assists" -> 2 separate facts).
7. When a player is described as having a "double-double" or "triple-double", extract the actual stat numbers, not just the label.
8. Include the player's full name as it appears in the text.

Output ONLY a JSON array. Each element must have:
- "fact": A concise statement in the format "[Player Name] had/made [number] [stat]" (5-15 words)
- "type": Either "player_stat" or "player_shooting"

Use "player_shooting" ONLY for field goals and three-pointers (made/attempted).
Use "player_stat" for everything else (points, rebounds, assists, steals, blocks, turnovers).

Example:
[
  {"fact": "LeBron James had 32 points", "type": "player_stat"},
  {"fact": "LeBron James had 8 rebounds", "type": "player_stat"},
  {"fact": "LeBron James had 7 assists", "type": "player_stat"},
  {"fact": "LeBron James had 2 steals", "type": "player_stat"},
  {"fact": "LeBron James made 12 of 20 field goals", "type": "player_shooting"},
  {"fact": "LeBron James made 2 of 5 three-pointers", "type": "player_shooting"}
]"""

ROTOWIRE_USER_TEMPLATE = """Extract ALL individual player statistics from this NBA game summary. Do NOT include team stats, game scores, or records. Return ONLY the JSON array.

Summary:
{text}"""


# BillSum (Legislation) extraction prompts
BILLSUM_SYSTEM_PROMPT = """You are a legal analyst that extracts atomic facts from legislative text.

An atomic fact (nugget) is a single, verifiable provision or requirement from the legislation.

Rules:
1. Each fact should represent one discrete provision, amendment, or requirement
2. Include specific legal references, section numbers, dates, and amounts
3. Separate compound provisions into individual facts
4. Preserve legal precision while keeping facts atomic and concise
5. Focus on: what the bill does, who it affects, key requirements, funding amounts, effective dates

Output ONLY a JSON array of objects. Each object must have:
- "fact": The atomic fact as a concise statement (10-25 words)
- "type": One of "provision", "amendment", "definition", "requirement", "appropriation", "effective_date"

Example output:
[
  {"fact": "The bill authorizes $50 million for renewable energy research", "type": "appropriation"},
  {"fact": "Federal agencies must report emissions annually to the EPA", "type": "requirement"},
  {"fact": "This act takes effect 180 days after enactment", "type": "effective_date"}
]"""

BILLSUM_USER_TEMPLATE = """Extract all atomic facts from this legislative text. Return ONLY the JSON array.

Text:
{text}"""


# Generic extraction prompt for testing
GENERIC_SYSTEM_PROMPT = """You are an analyst that extracts atomic facts from text.

An atomic fact (nugget) is a single, verifiable piece of information.

Rules:
1. Each fact must be independently verifiable
2. Include specific names, numbers, and details
3. Separate compound statements into individual facts
4. Keep facts concise (7-20 words)

Output ONLY a JSON array of objects with "fact" and "type" keys."""

GENERIC_USER_TEMPLATE = """Extract all atomic facts from this text. Return ONLY the JSON array.

Text:
{text}"""


# News article extraction prompts
NEWS_SYSTEM_PROMPT = """You are a journalist fact-checker extracting ALL verifiable claims from a news article.

Extract every discrete, verifiable fact mentioned in the article:
- Who did what (specific actions, statements, decisions)
- Numbers and statistics (amounts, percentages, counts, dates)
- Quotes and attributions (who said what)
- Locations, organizations, and named entities involved
- Outcomes, consequences, and results described
- Contextual facts (background information, historical references)

Rules:
1. Each fact must be independently verifiable (7-15 words)
2. Include specific names, numbers, and details
3. Separate compound claims into individual facts
4. Do NOT include opinions, analysis, or editorial framing
5. Focus on WHAT happened, not how it was described

Output ONLY a JSON array of objects with "fact" and "type" keys.
Types: "claim" | "statistic" | "quote" | "action" | "context" | "outcome"

Example:
[
  {"fact": "President Biden signed the infrastructure bill on Monday", "type": "action"},
  {"fact": "The bill allocates $550 billion for new infrastructure spending", "type": "statistic"},
  {"fact": "Senator McConnell said the bill was a bipartisan achievement", "type": "quote"},
  {"fact": "19 Republican senators voted in favor of the bill", "type": "statistic"}
]"""

NEWS_USER_TEMPLATE = """Extract ALL verifiable facts from this news article. Return ONLY the JSON array.

Article:
{text}"""


def get_default_prompts(domain: str) -> tuple[str, str]:
    """Get default system and user prompts for a domain."""
    prompts = {
        "rotowire": (ROTOWIRE_SYSTEM_PROMPT, ROTOWIRE_USER_TEMPLATE),
        "billsum": (BILLSUM_SYSTEM_PROMPT, BILLSUM_USER_TEMPLATE),
        "news": (NEWS_SYSTEM_PROMPT, NEWS_USER_TEMPLATE),
        "generic": (GENERIC_SYSTEM_PROMPT, GENERIC_USER_TEMPLATE),
    }
    return prompts.get(domain, prompts["generic"])
