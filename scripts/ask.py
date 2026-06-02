# scripts/ask.py
"""Ask the Digimon TCG deckbuilding assistant a question.

Retrieves grounding context from Postgres (semantic deck search + meta-stat
views), then asks Claude to answer using ONLY that context.

Requires ANTHROPIC_API_KEY in .env (and `pip install anthropic`).

Usage:
    python scripts/ask.py "What tech cards should I run in Imperialdramon right now?"
    python scripts/ask.py "How do I build Puppets?" --block bt24_ex11
    python scripts/ask.py "What beats Royal Knights?" --archetype "Royal Knights" --k 8
"""

import sys
import os
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT)

from dotenv import load_dotenv

from app.db.connection import get_connection
from app.services.assistant import build_context, SYSTEM_PROMPT

MODEL = "claude-opus-4-8"


def main():
    parser = argparse.ArgumentParser(description="Digimon TCG deckbuilding assistant")
    parser.add_argument("question", help="your deckbuilding / meta question")
    parser.add_argument("--block", default=None, help="restrict meta context to a block_id (format)")
    parser.add_argument("--archetype", default=None, help="force the archetype to profile")
    parser.add_argument("--k", type=int, default=6, help="number of example decks to retrieve")
    parser.add_argument("--show-context", action="store_true", help="print the retrieved context too")
    args = parser.parse_args()

    load_dotenv()
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY is not set (add it to .env).")
        sys.exit(1)

    import anthropic

    conn = get_connection()
    try:
        context = build_context(
            conn, args.question, block_id=args.block, archetype=args.archetype, k=args.k
        )
    finally:
        conn.close()

    if args.show_context:
        print(context)
        print("\n" + "=" * 60 + "\n")

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    user_message = f"{context}\n\nQUESTION: {args.question}"

    with client.messages.stream(
        model=MODEL,
        max_tokens=4000,
        thinking={"type": "adaptive"},  # let Claude reason about deck choices
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},  # cache the stable instructions
            }
        ],
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
        final = stream.get_final_message()

    u = final.usage
    print(
        f"\n\n[tokens: in={u.input_tokens}, out={u.output_tokens}, "
        f"cache_read={getattr(u, 'cache_read_input_tokens', 0)}]"
    )


if __name__ == "__main__":
    main()
