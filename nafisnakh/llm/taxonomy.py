"""The 45 complaint titles → 10 physical mechanisms (PLAN §3.6).

Do **not** cluster this from scratch. A prior KMeans (k=8) reached only 36.3%
purity against the 45 titles, because the 45 are near-synonyms describing ten
physical failure modes: `بدپیچی`, `بد پيچي`, `بدپیچی بسته` and
`بدپیچی / سفتی بسته` are one mechanism written four ways. Mapping them
deterministically costs nothing, is auditable by a QC person, and leaves the LLM
free to do the part a lookup table cannot: read free text, decide which
mechanism it describes, and say "none of these" when it is a new one.

⚠️ **Q13 is still open**: this is our mapping of their 45 titles, not theirs. It
should be reviewed by a Nafis Nakh QC person before it becomes the backbone of
every complaint signal. Cheap to validate now, expensive to unwind later.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..io.normalize import normalize_fa


@dataclass(frozen=True)
class Mechanism:
    id: str
    label_fa: str
    description_fa: str


MECHANISMS: dict[str, Mechanism] = {
    m.id: m
    for m in [
        Mechanism("M01_package_formation", "شکل‌گیری بسته",
                  "بدپیچی، ریبونی، سفتی یا شلی بسته، تنشن نامناسب پیچش، حلقه‌های نامنظم."),
        Mechanism("M02_filament_damage", "آسیب فیلامنت",
                  "پارگی فیلامنت، پرز، گره و اسنارل، حلقه‌های بلند."),
        Mechanism("M03_mass_count_deviation", "انحراف نمره و وزن",
                  "تلرانس یا خروج از رنج نمره، نوسان دنیر، CV، اختلاف وزنی."),
        Mechanism("M04_dye_shade", "شید رنگ",
                  "اختلاف یا نوسان شید رنگ، راه‌راهی، دورنگی بین لاها."),
        Mechanism("M05_intermingling", "مینگل",
                  "مینگل بیش از حد یا کمتر از حد."),
        Mechanism("M06_spin_finish", "روغن و اسپین‌فینیش",
                  "روغن نامتوازن، آلودگی یا لکه روغن."),
        Mechanism("M07_twist_ply", "تاب و لا",
                  "جهت یا تعداد تاب اشتباه، اختلاف و بازشدن لا، جدایش مغزی و افکت."),
        Mechanism("M08_tube_packaging", "دوک و بسته‌بندی",
                  "دوک دست دوم، شکستگی و پلیسه سر دوک، بسته‌بندی معیوب."),
        Mechanism("M09_labelling_logistics", "لیبل و حمل",
                  "لیبل اشتباه، آسیب حمل و نقل، مغایرت مستندات محموله."),
        Mechanism("M10_mechanical_properties", "خواص مکانیکی",
                  "استحکام، ازدیاد طول، جمع‌شدگی، کریمپ، سیمی بودن، زیردست."),
    ]
}

MECHANISM_IDS = list(MECHANISMS)
UNKNOWN = "UNKNOWN"

# The 45 curated titles, exactly as they appear in ``شکایات.Complaint_Title``.
TITLE_TO_MECHANISM: dict[str, str] = {
    # M01 — package formation
    "بد پيچي": "M01_package_formation",
    "بدپیچی بسته": "M01_package_formation",
    "بدپیچی / سفتی بسته": "M01_package_formation",
    "بدپیچی و ریزش نخ": "M01_package_formation",
    "پیچش بسته/ تنشن پیچش": "M01_package_formation",
    "حلقه‌های نامنظم": "M01_package_formation",
    # M02 — filament damage
    "فیلامنت و پرز": "M02_filament_damage",
    "فیلامنت پارگی و پرز": "M02_filament_damage",
    "پارگی فیلامنت": "M02_filament_damage",
    "پرز و حلقه‌های بلند": "M02_filament_damage",
    "گره و اسنارل": "M02_filament_damage",
    # M03 — mass / count deviation
    "تلرانس نمره": "M03_mass_count_deviation",
    "خارج بودن نمره": "M03_mass_count_deviation",
    "نوسان دنیر": "M03_mass_count_deviation",
    "نوسان دنیر / CV": "M03_mass_count_deviation",
    "اختلاف وزنی": "M03_mass_count_deviation",
    "حجم کمتر از انتظار": "M03_mass_count_deviation",
    # M04 — dye shade
    "شید رنگ": "M04_dye_shade",
    "شید رنگ / راه‌راهی": "M04_dye_shade",
    "اختلاف شید بین لاها": "M04_dye_shade",
    # M05 — intermingling
    "مینگل بیشتر از حد": "M05_intermingling",
    "مینگل کمتر از حد": "M05_intermingling",
    # M06 — spin finish
    "روغن نامتوازن": "M06_spin_finish",
    "آلودگی / لکه روغن": "M06_spin_finish",
    # M07 — twist / ply
    "جهت تاب اشتباه": "M07_twist_ply",
    "نوسان تعداد تاب": "M07_twist_ply",
    "اختلاف تعداد لا": "M07_twist_ply",
    "بازشدن لا / جدایش": "M07_twist_ply",
    "باز شدن لای نخ": "M07_twist_ply",
    "کم شدن لای نخ": "M07_twist_ply",
    "تنشن و تاب مجازی": "M07_twist_ply",
    "جداشدن مغزی و افکت": "M07_twist_ply",
    # M08 — tube / packaging
    "دوک دست دوم / خرابی دوک": "M08_tube_packaging",
    "خرابی دوک و بسته‌بندی": "M08_tube_packaging",
    # M09 — labelling / logistics
    "الصاق لیبل اشتباه": "M09_labelling_logistics",
    "لیبل پایه نخ اشتباه": "M09_labelling_logistics",
    "آسیب حمل و نقل": "M09_labelling_logistics",
    "آسیب دیدگی در حمل و نقل": "M09_labelling_logistics",
    "بازشدن نخ درجه C": "M09_labelling_logistics",
    # M10 — mechanical properties
    "استحکام پایین": "M10_mechanical_properties",
    "استحکام پایین / پارگی": "M10_mechanical_properties",
    "اختلاف ازدیاد طول": "M10_mechanical_properties",
    "جمع‌شدگی خارج از محدوده": "M10_mechanical_properties",
    "کریمپ / حجم ناهمگون": "M10_mechanical_properties",
    "نامناسب بودن زير دست پتو": "M10_mechanical_properties",
}

# lookup on the normalised form, so ي/ك and ZWNJ variants all resolve
_NORMALISED = {normalize_fa(t): m for t, m in TITLE_TO_MECHANISM.items()}


def mechanism_for_title(title: str | None) -> str:
    """Deterministic 45 → 10 lookup. Returns ``UNKNOWN`` for an unseen title."""
    if not title:
        return UNKNOWN
    return _NORMALISED.get(normalize_fa(title), UNKNOWN)


def mechanism_label(mechanism_id: str) -> str:
    m = MECHANISMS.get(mechanism_id)
    return m.label_fa if m else "نامشخص"


def taxonomy_prompt_block() -> str:
    """The mechanism list, rendered for a prompt."""
    return "\n".join(
        f"- {m.id} ({m.label_fa}): {m.description_fa}" for m in MECHANISMS.values()
    )


def coverage_report(titles: list[str]) -> dict[str, object]:
    """Which of the observed titles the map covers — the check that keeps this
    table honest when new titles appear in a later extract."""
    mapped = {t: mechanism_for_title(t) for t in titles}
    unmapped = sorted(t for t, m in mapped.items() if m == UNKNOWN)
    counts: dict[str, int] = {}
    for m in mapped.values():
        counts[m] = counts.get(m, 0) + 1
    return {
        "n_titles": len(titles),
        "n_mapped": len(titles) - len(unmapped),
        "unmapped": unmapped,
        "per_mechanism": counts,
    }
