MAX_LEVEL = 100

RANKS = [
    (1, 10, "تازه‌وارد", "🌱"),
    (11, 25, "فعال", "💬"),
    (26, 45, "حرفه‌ای", "⚡"),
    (46, 65, "زمردی", "💚"),
    (66, 85, "نخبه", "🛡️"),
    (86, 100, "اسطوره", "👑"),
]

AUTO_BADGES = [
    (5, "🌟", "عضو پرتلاش"),
    (10, "💬", "فعال گروه"),
    (25, "⚡", "حرفه‌ای"),
    (50, "💚", "زمردی"),
    (75, "🛡️", "نخبه"),
    (100, "👑", "اسطوره"),
]

def xp_to_reach_level(level: int) -> int:
    """Cumulative XP needed to reach this level (level 1 starts at zero)."""
    level = max(1, min(MAX_LEVEL, int(level)))
    return 10 * (level - 1) * (level + 8)

def level_from_xp(xp: int) -> int:
    xp = max(0, int(xp))
    level = 1
    while level < MAX_LEVEL and xp >= xp_to_reach_level(level + 1):
        level += 1
    return level

def rank_for_level(level: int):
    for low, high, name, icon in RANKS:
        if low <= level <= high:
            return name, icon
    return "تازه‌وارد", "🌱"

def next_level_progress(xp: int, level: int):
    if level >= MAX_LEVEL:
        return xp, xp, 100
    current_floor = xp_to_reach_level(level)
    next_floor = xp_to_reach_level(level + 1)
    span = max(1, next_floor - current_floor)
    earned = max(0, xp - current_floor)
    return earned, span, min(100, int(earned * 100 / span))

def automatic_badges(level: int):
    return [{"emoji": emoji, "name": name} for threshold, emoji, name in AUTO_BADGES if level >= threshold]
