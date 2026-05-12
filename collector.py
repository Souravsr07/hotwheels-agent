import re
import unicodedata

TIER_RANK = {
    "ignored": -100,
    "common": 0,
    "fantasy": 10,
    "maybe": 30,
    "real_car": 60,
    "premium": 80,
    "grail": 100,
}

DEFAULT_COLLECTOR_RULES = {
    "grail_keywords": [
        "super treasure hunt",
        "sth",
        "rlc",
        "red line club",
        "chase",
        "0/5",
        "ferrari",
        "laferrari",
        "f40",
        "f50",
        "enzo",
        "testarossa",
    ],
    "premium_keywords": [
        "premium",
        "car culture",
        "boulevard",
        "team transport",
        "real riders",
        "metal/metal",
        "fast and furious",
        "pop culture",
        "retro entertainment",
        "collector set",
        "treasure hunt",
        "t-hunt",
        "gran turismo",
        "forza",
        "rlc",
        "red line club",
        "ultra hots",
        "zamac",
        "spectraflame",
        "screen time",
        "replica entertainment",
        "drag strip demons",
        "collector edition",
        "convention exclusive",
    ],
    "priority_keywords": [
        "abarth",
        "acura",
        "alfa romeo",
        "aston martin",
        "audi",
        "bentley",
        "bmw",
        "bugatti",
        "cadillac",
        "camaro",
        "chevrolet",
        "chevy",
        "corvette",
        "datsun",
        "dodge",
        "charger",
        "challenger",
        "viper",
        "f1",
        "formula 1",
        "ford escort",
        "ford gt",
        "gt40",
        "mustang",
        "bronco",
        "gordon murray",
        "gma",
        "t.33",
        "t33",
        "t.50",
        "t50",
        "honda",
        "civic",
        "s2000",
        "nsx",
        "integra",
        "jaguar",
        "koenigsegg",
        "lamborghini",
        "lancia",
        "lexus",
        "lfa",
        "lotus",
        "maserati",
        "mazda",
        "rx-7",
        "rx7",
        "miata",
        "mclaren",
        "mercedes",
        "amg",
        "mini cooper",
        "mitsubishi",
        "lancer",
        "evo",
        "nissan",
        "skyline",
        "gt-r",
        "gtr",
        "silvia",
        "s13",
        "s14",
        "s15",
        "pagani",
        "zonda",
        "huayra",
        "plymouth",
        "porsche",
        "911",
        "934",
        "935",
        "renault",
        "subaru",
        "wrx",
        "sti",
        "tesla",
        "toyota",
        "supra",
        "ae86",
        "celica",
        "volkswagen",
        "vw",
        "r34",
        "r33",
        "r32",
        "bnr34",
        "nissan z",
        "fairlady",
        "240z",
        "370z",
        "350z",
        "240sx",
        "nismo",
        "hakosuka",
        "kenmeri",
        "bluebird",
        "fd3s",
        "fc3s",
        "mx-5",
        "mx5",
        "cosmo",
        "787b",
        "a80",
        "a90",
        "gr supra",
        "trueno",
        "levin",
        "2000gt",
        "gr86",
        "mr2",
        "gr corolla",
        "gr yaris",
        "ek9",
        "type r",
        "crx",
        "impreza",
        "brz",
        "eclipse",
        "3000gt",
        "gto",
        "cappuccino",
        "jimny",
        "swift",
        "countach",
        "huracan",
        "aventador",
        "diablo",
        "gallardo",
        "murcielago",
        "urus",
        "sesto elemento",
        "veneno",
        "revuelto",
        "458",
        "488",
        "sf90",
        "812",
        "296",
        "599xx",
        "f355",
        "360 modena",
        "308",
        "gt3",
        "gt2 rs",
        "cayman",
        "918",
        "carrera",
        "targa",
        "spyder",
        "962",
        "senna",
        "p1",
        "720s",
        "765lt",
        "elva",
        "600lt",
        "artura",
        "chiron",
        "veyron",
        "divo",
        "bolide",
        "vulcan",
        "db5",
        "db11",
        "vantage",
        "one-77",
        "valkyrie",
        "agera",
        "jesko",
        "regera",
        "utopia",
        "sls amg",
        "clk gtr",
        "300sl",
        "amg gt",
        "m3 gtr",
        "m4",
        "i8",
        "2002",
        "r8",
        "rs6",
        "quattro",
        "esprit",
        "giulia",
        "4c",
        "stratos",
        "delta integrale",
        "charger daytona",
        "super bee",
        "barracuda",
        "road runner",
        "copo camaro",
        "zl1",
        "stingray",
        "zr1",
        "grand sport",
        "c8",
        "chevelle",
        "el camino",
        "bel air",
        "nova",
        "gt500",
        "boss 429",
        "shelby",
        "cobra",
        "mach 1",
        "thunderbird",
        "trans am",
        "firebird",
        "pontiac gto",
        "grand national",
        "442",
        "le mans",
        "gulf",
        "martini racing",
        "rothmans",
        "castrol",
        "group b",
        "rally",
        "lmp1",
        "gt3 race",
        "tokyo drift",
        "initial d",
        "need for speed",
        "delorean",
    ],
    "maybe_keywords": [
        "batmobile",
        "barbie",
        "monster truck",
        "motorcycle",
        "ducati",
        "harley",
        "range rover",
        "land rover",
        "jeep",
        "bronco",
        "mustang",
        "bronze chase",
    ],
    "fantasy_keywords": [
        "bone shaker",
        "boneshaker",
        "deora",
        "twin mill",
        "rodger dodger",
        "mad manga",
        "surf crate",
        "baja bone shaker",
        "dragon blaster",
        "roller toaster",
        "donut drifter",
        "quick bite",
        "street wiener",
        "duck n roll",
        "sharkruiser",
        "rocketfire",
        "skull crusher",
        "buns of steel",
        "tooned",
        "too'nd",
        "toon'd",
    ],
    "pack_keywords": [
        "nightburnerz",
        "night burnerz",
        "hw motorshow",
        "motor show",
        "formula 1 5",
        "f1 5-pack",
        "f1 5 pack",
        "muscle mania",
        "circuit legends",
        "speed graphics",
        "sports car club",
        "hw checkmate",
        "tooned",
        "daredevils",
        "fast and furious 5",
        "gran turismo 5",
        "forza 5",
        "pop culture 5",
        "race team",
    ],
    "ignore_keywords": [
        "assorted",
        "mystery",
        "random",
        "set of",
        "pack of",
        "design may vary",
        "designs may vary",
        "design and colour may vary",
        "colour and designs may vary",
        "colour may vary",
        "color may vary",
        "colours may vary",
        "colors may vary",
        "1:64 scale toy car",
        "1:64 die cast car",
        "worldwide basic",
        "copy colouring",
        "coloring book",
        "colouring book",
        "dreamland publications",
        "toy bike",
        "moto x-blade",
        "rollin thunder",
        "gift pack",
        "5 car gift",
        "assorted pack",
        "mystery pack",
        "surprise pack",
        "hot wheels 5 pack",
        "track set",
        "city set",
        "track builder",
        "launcher",
        "garage",
        "playset",
        "action set",
        "builder set",
        "bone shaker",
        "boneshaker",
        "twin mill",
        "deora",
        "beatnik bandit",
        "splittin image",
        "python",
        "torero",
        "silhouette",
        "rodger dodger",
        "heavy chevy",
        "the demon",
        "turbofire",
        "bad mudder",
        "backburner",
        "carbonic",
        "solid muscle",
        "power rocket",
        "rivited",
        "twinduction",
        "fangula",
        "motoblade",
        "tur-bone charged",
        "cockney cab",
        "dragon blaster",
        "impavido 1",
        "loop coupe",
        "ballistik",
        "chicane",
        "covelight",
        "crescendo",
        "cruise bruiser",
        "dashtop",
        "fast fish",
        "gyre attack",
        "haggler",
        "hw44",
        "hypertruck experiment",
        "ice shredder",
        "iridium",
        "el segundo rallye",
        "mad manga",
        "surf crate",
        "baja bone shaker",
        "roller toaster",
        "donut drifter",
        "quick bite",
        "street wiener",
        "duck n roll",
        "sharkruiser",
        "rocketfire",
        "skull crusher",
        "buns of steel",
        "tooned",
        "too'nd",
        "toon'd",
    ],
    "immediate_alert_tiers": ["grail", "premium", "real_car"],
    "digest_include_tiers": ["grail", "premium", "real_car", "maybe", "fantasy"],
    "digest_max_priority_items": 10,
    "digest_max_other_items": 14,
}


def classify_products(products: list[dict], config: dict) -> list[dict]:
    rules = _rules(config)
    classified = []
    for product in products:
        enriched = dict(product)
        tier, terms = classify_name(product.get("name", ""), rules)
        enriched["collector_tier"] = tier
        enriched["collector_score"] = TIER_RANK[tier]
        enriched["collector_terms"] = terms
        enriched["collector_reason"] = _reason(tier, terms)
        classified.append(enriched)
    return sorted(classified, key=_sort_key)


def priority_products(products: list[dict], config: dict) -> list[dict]:
    rules = _rules(config)
    immediate_tiers = set(rules["immediate_alert_tiers"])
    return [product for product in products if product.get("collector_tier") in immediate_tiers]


def classify_name(name: str, rules: dict | None = None) -> tuple[str, list[str]]:
    rules = rules or DEFAULT_COLLECTOR_RULES
    normalized = normalize(name)

    pack_terms = _matched_pack_terms(normalized, rules.get("pack_keywords", []))
    if pack_terms:
        return "premium", pack_terms

    ignored_terms = _matched_terms(normalized, rules["ignore_keywords"])
    if ignored_terms:
        return "ignored", ignored_terms

    checks = [
        ("grail", rules["grail_keywords"]),
        ("premium", rules["premium_keywords"]),
        ("real_car", rules["priority_keywords"]),
        ("maybe", rules["maybe_keywords"]),
        ("fantasy", rules["fantasy_keywords"]),
    ]
    for tier, keywords in checks:
        terms = _matched_terms(normalized, keywords)
        if terms:
            return tier, terms

    return "common", []


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = value.lower().replace("&", " and ")
    value = value.replace("t.33", "t33").replace("t.50", "t50")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _rules(config: dict) -> dict:
    configured = config.get("collector", {})
    rules = {
        key: list(value) if isinstance(value, list) else value
        for key, value in DEFAULT_COLLECTOR_RULES.items()
    }
    merge_list_keys = {
        "grail_keywords",
        "premium_keywords",
        "priority_keywords",
        "maybe_keywords",
        "fantasy_keywords",
        "pack_keywords",
        "ignore_keywords",
    }
    for key, value in configured.items():
        if key in rules and isinstance(value, list) and key in merge_list_keys:
            rules[key] = _unique_terms(list(rules[key]) + value)
        elif key in rules and isinstance(value, list):
            rules[key] = value
        elif key in rules:
            rules[key] = value

    desired_castings = list(config.get("desired_castings", []))
    desired_castings.extend(config.get("collector", {}).get("desired_castings", []))
    exclude_castings = list(config.get("exclude_castings", []))
    exclude_castings.extend(config.get("collector", {}).get("exclude_castings", []))

    rules["priority_keywords"] = _unique_terms(
        list(rules["priority_keywords"]) + desired_castings
    )
    rules["ignore_keywords"] = _unique_terms(
        list(rules["ignore_keywords"]) + exclude_castings
    )
    return rules


def _matched_terms(normalized_name: str, keywords: list[str]) -> list[str]:
    matches = []
    compact_seen = set()
    for keyword in keywords:
        normalized_keyword = normalize(keyword)
        if not normalized_keyword:
            continue
        compact_keyword = normalized_keyword.replace(" ", "")
        if compact_keyword in compact_seen:
            continue
        if _term_matches(normalized_name, normalized_keyword):
            matches.append(keyword)
            compact_seen.add(compact_keyword)

    return matches


def _matched_pack_terms(normalized_name: str, keywords: list[str]) -> list[str]:
    if not any(_term_matches(normalized_name, marker) for marker in ["pack", "5 pack", "5 car"]):
        return []
    return _matched_terms(normalized_name, keywords)


def _term_matches(normalized_name: str, normalized_keyword: str) -> bool:
    haystack = f" {normalized_name} "
    needle = f" {normalized_keyword} "
    if needle in haystack:
        return True

    name_tokens = normalized_name.split()
    keyword_tokens = normalized_keyword.split()
    compact_keyword = normalized_keyword.replace(" ", "")
    if len(compact_keyword) < 3:
        return False

    window_sizes = [len(keyword_tokens)] if len(keyword_tokens) > 1 else [2, 3]
    for size in window_sizes:
        if size <= 1:
            continue
        for index in range(0, len(name_tokens) - size + 1):
            if "".join(name_tokens[index : index + size]) == compact_keyword:
                return True

    return False


def _unique_terms(terms: list[str]) -> list[str]:
    unique = []
    seen = set()
    for term in terms:
        normalized = normalize(str(term))
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(term)
    return unique


def _reason(tier: str, terms: list[str]) -> str:
    if tier == "ignored":
        return f"Suppressed non-casting/generic stock: {', '.join(terms[:4])}"
    if tier == "common":
        return "Available stock"
    label = {
        "grail": "Grail / rare signal",
        "premium": "Premium series signal",
        "real_car": "Licensed collector casting",
        "maybe": "Maybe-interesting casting",
        "fantasy": "Fantasy casting",
    }[tier]
    return f"{label}: {', '.join(terms[:4])}"


def _sort_key(product: dict) -> tuple:
    return (
        -int(product.get("collector_score", 0)),
        product.get("location", ""),
        product.get("name", ""),
    )
