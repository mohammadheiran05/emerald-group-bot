"""Group-aware XP progression for Emerald Group Bot V2."""
MAX_LEVEL = 100

RANKS = [
    (1, 10, "تازه‌وارد", "🌱"), (11, 25, "فعال", "💬"),
    (26, 45, "حرفه‌ای", "⚡"), (46, 65, "زمردی", "💚"),
    (66, 85, "نخبه", "🛡️"), (86, 100, "اسطوره", "👑"),
]
AUTO_BADGES = [
    (5, "🌟", "عضو پرتلاش"), (10, "💬", "فعال گروه"),
    (25, "⚡", "حرفه‌ای"), (50, "💚", "زمردی"),
    (75, "🛡️", "نخبه"), (100, "👑", "اسطوره"),
]
MODE_MULTIPLIER = {"easy": 0.65, "normal": 1.0, "hard": 1.6}
MODE_LABELS = {"easy": "آسان", "normal": "استاندارد", "hard": "سخت"}

def xp_to_reach_level(level: int, mode: str = "normal", costs=None) -> int:
    """Cumulative XP required; costs optionally overrides per-level costs (target level -> XP)."""
    level = max(1, min(MAX_LEVEL, int(level)))
    multiplier = MODE_MULTIPLIER.get(mode, 1.0)
    overrides = costs or {}
    total = 0
    for target in range(2, level + 1):
        default_step = 20 * target + 60
        step = int(overrides.get(target, overrides.get(str(target), max(1, int(default_step * multiplier)))))
        total += max(1, step)
    return total

def level_from_xp(xp: int, mode: str = "normal", costs=None) -> int:
    xp = max(0, int(xp)); level = 1
    while level < MAX_LEVEL and xp >= xp_to_reach_level(level + 1, mode, costs):
        level += 1
    return level

def rank_for_level(level: int):
    for low, high, name, icon in RANKS:
        if low <= level <= high: return name, icon
    return "تازه‌وارد", "🌱"

def next_level_progress(xp: int, level: int, mode: str = "normal", costs=None):
    if level >= MAX_LEVEL: return xp, xp, 100
    current_floor = xp_to_reach_level(level, mode, costs); next_floor = xp_to_reach_level(level + 1, mode, costs)
    span = max(1, next_floor - current_floor); earned = max(0, xp - current_floor)
    return earned, span, min(100, int(earned * 100 / span))

def automatic_badges(level: int):
    return [{"emoji": emoji, "name": name} for threshold, emoji, name in AUTO_BADGES if level >= threshold]
