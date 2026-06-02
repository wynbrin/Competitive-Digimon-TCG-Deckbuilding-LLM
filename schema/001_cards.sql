
DROP TABLE IF EXISTS deck_cards CASCADE;
DROP TABLE IF EXISTS decks CASCADE;


-- Drop existing table if resetting schema
DROP TABLE IF EXISTS cards CASCADE;

-- Main cards table
CREATE TABLE cards (
    card_id TEXT PRIMARY KEY,              -- maps to "id"
    name TEXT,
    type TEXT,
    level INT,
    play_cost INT,
    evolution_cost INT,
    evolution_color TEXT[],
    evolution_level INT,
    xros_req TEXT,
    color TEXT[],
    digi_type TEXT[],
    form TEXT,
    dp INT,
    attribute TEXT,
    rarity TEXT,
    stage TEXT,
    artist TEXT,
    main_effect TEXT,
    source_effect TEXT,
    alt_effect TEXT,
    link_requirements TEXT,
    link_dp INT,
    series TEXT,
    pretty_url TEXT,
    date_added TIMESTAMP,
    tcgplayer_name TEXT,
    tcgplayer_id TEXT,
    set_name TEXT,
    tags TEXT[] DEFAULT '{}'
);

-- Optional: index for faster search by name
CREATE INDEX idx_cards_name ON cards (name);

-- Optional: index for type
CREATE INDEX idx_cards_type ON cards (type);

-- Optional: index for set_name
CREATE INDEX idx_cards_set_name ON cards (set_name);

-- Optional: index for rarity
CREATE INDEX idx_cards_rarity ON cards (rarity);

-- Optional: index for color array
CREATE INDEX idx_cards_color ON cards USING GIN (color);

-- Optional: index for digi_type array
CREATE INDEX idx_cards_digi_type ON cards USING GIN (digi_type);
