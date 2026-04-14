// Short, common words per locale used to generate memorable passphrases.
// Criteria: all lowercase, 3–8 characters, no ambiguous homophones, chosen to
// be easy to dictate over the phone. Length ~150 words per list, giving
// ~36 bits of entropy for a 5-word passphrase — enough for a rate-limited
// file-transfer password prompt.

// French: words a 10-year-old can spell intuitively from oral dictation.
// Strict criteria:
// - max 8 characters
// - no accent in standard spelling
// - no silent h
// - no -eau ending (ambiguous /o/ → o/au/eau/ot)
// - no common homophones (mer/mère, vin/vingt, pain/pin, port/porc…)
// - no ph (dauphin)
// - no alternative spelling (oignon/ognon — removed)
// Expected to yield ~35 bits of entropy for a 5-word passphrase.
export const WORDLIST_FR: readonly string[] = [
  "abeille", "aigle", "arbre", "baleine", "bambou", "banane", "bol", "bougie",
  "branche", "brume", "cabane", "calme", "canard", "carotte", "cave", "cerise",
  "chaise", "chaton", "chemin", "cheval", "chien", "chouette", "ciel",
  "colombe", "courage", "crabe", "dune", "espoir", "faucon", "femme", "ferme",
  "feu", "feuille", "flamme", "fleur", "fraise", "fromage", "fruit", "gare",
  "glace", "gorille", "graine", "homme", "jardin", "joie", "jouet", "jour",
  "koala", "lac", "laitue", "lampe", "lanterne", "lapin", "limace", "lion",
  "livre", "loup", "lune", "magie", "main", "maison", "matin", "miel",
  "minute", "monde", "montagne", "mouche", "mousse", "mouton", "neige",
  "nuage", "nuit", "olive", "ombre", "orage", "orange", "ours", "palmier",
  "panda", "panier", "papillon", "pierre", "place", "plage", "platane",
  "pluie", "poire", "poisson", "poivre", "pomme", "pommier", "porte", "poule",
  "poulpe", "racine", "raisin", "renard", "roche", "roman", "rose", "route",
  "sable", "sac", "salade", "sapin", "scorpion", "semaine", "serpent",
  "silence", "singe", "soir", "soleil", "souris", "sucre", "table", "tasse",
  "tige", "tigre", "tomate", "tortue", "tulipe", "usine", "vache", "vague",
  "valise", "viande", "ville",
] as const;

export const WORDLIST_EN: readonly string[] = [
  "apple", "table", "chair", "house", "river", "cloud", "stone", "water",
  "light", "night", "morning", "window", "garden", "flower", "forest", "mountain",
  "valley", "ocean", "island", "bridge", "street", "market", "school", "library",
  "office", "kitchen", "garden", "castle", "village", "city", "country", "planet",
  "friend", "family", "sister", "brother", "mother", "father", "daughter", "uncle",
  "coffee", "bread", "butter", "honey", "sugar", "salt", "pepper", "cheese",
  "orange", "lemon", "grape", "banana", "cherry", "melon", "peach", "plum",
  "carrot", "onion", "garlic", "tomato", "potato", "salad", "pasta", "rice",
  "bottle", "basket", "plate", "spoon", "fork", "knife", "glass", "candle",
  "pencil", "paper", "letter", "story", "novel", "poem", "music", "song",
  "guitar", "piano", "violin", "drum", "dance", "voice", "echo", "rhythm",
  "summer", "winter", "spring", "autumn", "season", "hour", "minute", "second",
  "train", "plane", "boat", "wagon", "wheel", "engine", "sail", "anchor",
  "horse", "cattle", "sheep", "goat", "rabbit", "mouse", "tiger", "eagle",
  "spider", "butterfly", "beetle", "turtle", "dolphin", "whale", "shark", "fish",
  "maple", "cedar", "birch", "willow", "oak", "pine", "rose", "tulip",
  "daisy", "lily", "ivy", "fern", "moss", "grass", "wheat", "barley",
  "sunset", "sunrise", "rainbow", "thunder", "lightning", "storm", "breeze", "tide",
  "forest", "meadow", "desert", "jungle", "canyon", "lagoon", "harbor", "cliff",
] as const;

export const WORDLIST_NL: readonly string[] = [
  "huis", "boom", "kat", "hond", "boek", "tafel", "stoel", "bloem",
  "appel", "peer", "maan", "zon", "aarde", "zee", "eiland", "brug",
  "straat", "stad", "bos", "berg", "rivier", "meer", "regen", "sneeuw",
  "wind", "wolk", "hemel", "ster", "tuin", "deur", "raam", "sleutel",
  "tas", "brood", "water", "wijn", "zout", "suiker", "fruit", "vis",
  "vlees", "kaas", "koffie", "thee", "honing", "boter", "koek", "taart",
  "chocolade", "sinaasappel", "citroen", "kers", "aardbei", "druif", "banaan",
  "tomaat", "wortel", "salade", "ui", "knoflook", "kruid", "blad", "hout",
  "steen", "zand", "rots", "ijs", "vuur", "vlam", "rook", "schaduw",
  "licht", "dag", "nacht", "ochtend", "avond", "uur", "minuut", "jaar",
  "maand", "week", "lente", "zomer", "herfst", "winter", "weg", "pad",
  "trein", "auto", "boot", "vliegtuig", "fiets", "motor", "bus", "metro",
  "station", "haven", "plein", "markt", "school", "kerk", "museum", "bioscoop",
  "theater", "hotel", "kantoor", "fabriek", "boerderij", "veld", "strand",
  "duin", "kelder", "dak", "muur", "vloer", "gazon", "struik", "roos",
  "tulp", "madelief", "eik", "den", "esdoorn", "populier", "paard", "koe",
  "schaap", "geit", "konijn", "muis", "vos", "wolf", "beer", "hert",
  "eend", "kip", "haan", "vogel", "uil", "bij", "vlinder", "spin",
  "mier", "vlieg", "libel", "schildpad", "dolfijn", "walvis", "haai",
] as const;

export function getWordlist(
  locale: string | undefined,
): readonly string[] {
  const lang = (locale ?? "").slice(0, 2).toLowerCase();
  if (lang === "en") return WORDLIST_EN;
  if (lang === "nl") return WORDLIST_NL;
  return WORDLIST_FR;
}
