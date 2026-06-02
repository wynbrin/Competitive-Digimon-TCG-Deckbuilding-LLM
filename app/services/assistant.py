"""Assemble grounded context for the deckbuilding assistant.

Pulls retrieved decklists (semantic search) + per-archetype meta stats from the
SQL views, and formats them into a single CONTEXT block for the LLM. The model
is instructed to answer ONLY from this block (see SYSTEM_PROMPT).
"""

from collections import Counter
from typing import Optional, List, Dict, Any

from app.services.retrieval import search_decks


SYSTEM_PROMPT = """You are a competitive Digimon TCG deckbuilding assistant. You help with \
deck construction, tech-card choices, and reading the metagame.

Grounding rules — follow these strictly:
- Answer ONLY from the data in the CONTEXT block of the user message: retrieved \
tournament decklists and per-archetype card-usage statistics. Do not rely on outside \
knowledge of specific cards, effects, rulings, or set legality.
- When you say how common a card is, quote the inclusion percentage and average copies \
from the stats. Distinguish staples (high inclusion %) from tech/flex choices (lower %).
- If the CONTEXT lacks the information needed to answer, say so plainly and name what is \
missing. Never invent card names, effects, or numbers.
- Data caveats you must respect:
  * The decks are sourced from winning / top-cut tournament lists, so they show what \
*places well*, not a true win rate.
  * There is NO head-to-head match data — you cannot give real matchup win rates. Discuss \
matchups only qualitatively (card choices, archetype composition) and flag when you are speculating.
  * "Inclusion %" is per card printing; the same card name can appear as multiple set versions.

Be concise and practical: lead with the direct answer, then justify it with the numbers."""


def _focus_archetype(decks: List[Dict[str, Any]], override: Optional[str]) -> Optional[str]:
    """Pick the archetype to profile: explicit override, else the most common
    primary archetype among the retrieved decks."""
    if override:
        return override
    names = [d["archetype"] for d in decks if d.get("archetype")]
    return Counter(names).most_common(1)[0][0] if names else None


def _card_usage(conn, archetype_name: str, limit: int = 30):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT card_name, card_type, inclusion_pct, avg_copies, total_decks
            FROM v_archetype_card_usage
            WHERE archetype_name = %s
            ORDER BY inclusion_pct DESC, decks_with_card DESC
            LIMIT %s;
            """,
            (archetype_name, limit),
        )
        return cur.fetchall()


def _meta_share(conn, block_id: Optional[str], limit: int = 12):
    with conn.cursor() as cur:
        if block_id:
            cur.execute(
                """
                SELECT archetype_name, deck_count, block_share_pct AS share
                FROM v_archetype_meta_share
                WHERE block_id = %s
                ORDER BY deck_count DESC LIMIT %s;
                """,
                (block_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT archetype_name, deck_count, overall_pct AS share
                FROM v_archetype_overall
                ORDER BY deck_count DESC LIMIT %s;
                """,
                (limit,),
            )
        return cur.fetchall()


def build_context(
    conn,
    question: str,
    block_id: Optional[str] = None,
    archetype: Optional[str] = None,
    k: int = 6,
) -> str:
    """Return a formatted CONTEXT string grounding the assistant's answer."""
    decks = search_decks(conn, question, k=k, block_id=block_id)
    focus = _focus_archetype(decks, archetype)

    lines: List[str] = ["CONTEXT", "======="]

    scope = f"block {block_id}" if block_id else "all formats"
    lines.append(f"\nMeta share ({scope}):")
    for r in _meta_share(conn, block_id):
        lines.append(f"  - {r['archetype_name']}: {r['deck_count']} decks ({r['share']}%)")

    if focus:
        usage = _card_usage(conn, focus)
        total = usage[0]["total_decks"] if usage else 0
        lines.append(
            f"\nCard usage for {focus} (inclusion % and avg copies, over {total} decks):"
        )
        for r in usage:
            lines.append(
                f"  - {r['card_name']} ({r['card_type']}): "
                f"{r['inclusion_pct']}% incl, {r['avg_copies']} avg copies"
            )
    else:
        lines.append("\n(No archetype could be identified for card-usage stats.)")

    lines.append("\nExample tournament decklists most similar to the question:")
    for i, d in enumerate(decks, 1):
        cards = d["cardlist"]
        if len(cards) > 320:
            cards = cards[:320] + "..."
        lines.append(
            f"  [{i}] {d['archetype'] or 'Unknown'} "
            f"({d['block_id']}, {d['placement']}, similarity {d['similarity']:.2f})"
        )
        lines.append(f"      {cards}")

    return "\n".join(lines)
