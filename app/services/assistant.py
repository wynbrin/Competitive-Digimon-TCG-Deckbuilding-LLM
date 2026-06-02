"""Assemble grounded context for the deckbuilding assistant.

Pulls retrieved decklists (semantic search) + per-archetype meta stats from the
SQL views, and formats them into a single CONTEXT block for the LLM. The model
is instructed to answer ONLY from this block (see SYSTEM_PROMPT).
"""

from collections import Counter
from typing import Optional, List, Dict, Any

from app.services.retrieval import search_decks
from ingestion.loaders.archetypes_loader import normalize


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
- If a BANLIST / RESTRICTIONS section is present, treat it as binding for that format: never \
recommend a banned card, and respect copy limits (restricted = max 1). If the section is absent, \
do not assume anything about legality.

Be concise and practical: lead with the direct answer, then justify it with the numbers."""


def _format_name(conn, block_id: str) -> Optional[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM formats WHERE block_id = %s;", (block_id,))
        row = cur.fetchone()
        return row["name"] if row else None


def _banlist(conn, block_id: str):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT card_name, status, note FROM banlist WHERE block_id = %s ORDER BY status, card_name;",
            (block_id,),
        )
        return cur.fetchall()


def _archetype_named_in(conn, question: str) -> Optional[str]:
    """If the question explicitly names an archetype, return that archetype.

    Matches each archetype's normalized name as a whole-token substring of the
    normalized question; prefers the longest (most specific) match.
    """
    q = f" {normalize(question)} "
    best = None
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM archetypes;")
        for row in cur.fetchall():
            name_norm = normalize(row["name"])
            if name_norm and f" {name_norm} " in q:
                if best is None or len(name_norm) > len(best[1]):
                    best = (row["name"], name_norm)
    return best[0] if best else None


def _focus_archetype(
    conn, question: str, decks: List[Dict[str, Any]], override: Optional[str]
) -> Optional[str]:
    """Pick the archetype to profile: explicit override > named in the question >
    the most common primary archetype among the semantically-retrieved decks."""
    if override:
        return override
    named = _archetype_named_in(conn, question)
    if named:
        return named
    names = [d["archetype"] for d in decks if d.get("archetype")]
    return Counter(names).most_common(1)[0][0] if names else None


def _example_decks(conn, archetype_name: str, block_id: Optional[str], k: int):
    """Recent example decklists for a specific archetype (most recent first)."""
    sql = """
        SELECT d.id, a.name AS archetype, d.block_id, d.placement, NULL::float AS similarity,
               string_agg(dc.quantity || 'x ' || c.name, ', '
                          ORDER BY dc.quantity DESC, c.name) AS cardlist
        FROM deck_archetypes da
        JOIN decks d       ON d.id = da.deck_id
        JOIN archetypes a  ON a.id = da.archetype_id
        JOIN deck_cards dc ON dc.deck_id = d.id
        JOIN cards c       ON c.card_id = dc.card_id
        WHERE da.is_primary AND a.name = %s {block}
        GROUP BY d.id, a.name, d.block_id, d.placement, d.deck_date
        ORDER BY d.deck_date DESC NULLS LAST, d.id DESC
        LIMIT %s;
    """
    params = [archetype_name]
    block = ""
    if block_id:
        block = "AND d.block_id = %s"
        params.append(block_id)
    params.append(k)
    with conn.cursor() as cur:
        cur.execute(sql.format(block=block), params)
        return cur.fetchall()


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
    retrieved = search_decks(conn, question, k=k, block_id=block_id)
    focus = _focus_archetype(conn, question, retrieved, archetype)

    # If we have a focus archetype, show example decks OF that archetype (coherent
    # with the stats). Otherwise fall back to the semantic search results.
    if focus:
        decks = _example_decks(conn, focus, block_id, k) or retrieved
    else:
        decks = retrieved

    lines: List[str] = ["CONTEXT", "======="]

    if block_id:
        fmt_name = _format_name(conn, block_id)
        scope = f"{fmt_name} [{block_id}]" if fmt_name else block_id
    else:
        scope = "all formats"
    lines.append(f"\nMeta share ({scope}):")
    for r in _meta_share(conn, block_id):
        lines.append(f"  - {r['archetype_name']}: {r['deck_count']} decks ({r['share']}%)")

    if block_id:
        bl = _banlist(conn, block_id)
        if bl:
            lines.append(f"\nBANLIST / RESTRICTIONS for {scope}:")
            for r in bl:
                note = f" ({r['note']})" if r["note"] else ""
                lines.append(f"  - {r['card_name']}: {r['status']}{note}")

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

    header = (
        f"\nExample {focus} tournament decklists (most recent):"
        if focus
        else "\nExample tournament decklists most similar to the question:"
    )
    lines.append(header)
    for i, d in enumerate(decks, 1):
        cards = d["cardlist"]
        if len(cards) > 320:
            cards = cards[:320] + "..."
        sim = d.get("similarity")
        sim_str = f", similarity {sim:.2f}" if sim is not None else ""
        lines.append(
            f"  [{i}] {d['archetype'] or 'Unknown'} "
            f"({d['block_id']}, {d['placement']}{sim_str})"
        )
        lines.append(f"      {cards}")

    return "\n".join(lines)
