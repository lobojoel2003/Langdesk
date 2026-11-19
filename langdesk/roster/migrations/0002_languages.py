"""Load the languages most often requested by people with limited English proficiency
in the United States. Edit or extend the list in the admin."""

from django.db import migrations

LANGUAGES = [
    ("es", "Spanish", "Español", False),
    ("cmn", "Mandarin", "普通话", False),
    ("yue", "Cantonese", "廣東話", False),
    ("vi", "Vietnamese", "Tiếng Việt", False),
    ("ko", "Korean", "한국어", False),
    ("tl", "Tagalog", "Tagalog", False),
    ("ru", "Russian", "Русский", False),
    ("ar", "Arabic", "العربية", False),
    ("ht", "Haitian Creole", "Kreyòl ayisyen", False),
    ("pt", "Portuguese", "Português", False),
    ("fr", "French", "Français", False),
    ("pl", "Polish", "Polski", False),
    ("ja", "Japanese", "日本語", False),
    ("hi", "Hindi", "हिन्दी", False),
    ("bn", "Bengali", "বাংলা", False),
    ("ur", "Urdu", "اردو", False),
    ("pa", "Punjabi", "ਪੰਜਾਬੀ", False),
    ("gu", "Gujarati", "ગુજરાતી", False),
    ("te", "Telugu", "తెలుగు", False),
    ("ta", "Tamil", "தமிழ்", False),
    ("fa", "Farsi", "فارسی", False),
    ("prs", "Dari", "دری", False),
    ("ps", "Pashto", "پښتو", False),
    ("so", "Somali", "Soomaali", False),
    ("am", "Amharic", "አማርኛ", False),
    ("ti", "Tigrinya", "ትግርኛ", False),
    ("sw", "Swahili", "Kiswahili", False),
    ("rw", "Kinyarwanda", "Ikinyarwanda", False),
    ("yo", "Yoruba", "Yorùbá", False),
    ("ne", "Nepali", "नेपाली", False),
    ("my", "Burmese", "မြန်မာ", False),
    ("kar", "Karen", "ကညီ", False),
    ("hmn", "Hmong", "Hmoob", False),
    ("km", "Khmer", "ខ្មែរ", False),
    ("lo", "Lao", "ລາວ", False),
    ("th", "Thai", "ไทย", False),
    ("uk", "Ukrainian", "Українська", False),
    ("ro", "Romanian", "Română", False),
    ("hy", "Armenian", "Հայերեն", False),
    ("sq", "Albanian", "Shqip", False),
    ("bs", "Bosnian", "Bosanski", False),
    ("el", "Greek", "Ελληνικά", False),
    ("it", "Italian", "Italiano", False),
    ("de", "German", "Deutsch", False),
    ("tr", "Turkish", "Türkçe", False),
    ("mam", "Mam", "Qyol Mam", False),
    ("quc", "K'iche'", "K'iche'", False),
    ("kjb", "Q'anjob'al", "Q'anjob'al", False),
    ("mh", "Marshallese", "Kajin M̧ajeļ", False),
    ("chk", "Chuukese", "Chuuk", False),
    ("nv", "Navajo", "Diné bizaad", False),
    ("ase", "American Sign Language", "ASL", True),
]


def load(apps, schema_editor):
    Language = apps.get_model("roster", "Language")
    for code, name, native, sign in LANGUAGES:
        Language.objects.get_or_create(
            code=code,
            defaults={"name": name, "native_name": native, "is_sign_language": sign},
        )


def unload(apps, schema_editor):
    Language = apps.get_model("roster", "Language")
    Language.objects.filter(code__in=[code for code, *_ in LANGUAGES], skills__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("roster", "0001_initial")]

    operations = [migrations.RunPython(load, unload)]
