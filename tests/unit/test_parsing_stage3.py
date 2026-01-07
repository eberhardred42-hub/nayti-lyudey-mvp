#!/usr/bin/env python3
"""Stage 3 parsing smoke-tests (no FastAPI).

This file is the canonical location.
Legacy entrypoint: tests/test-parsing.py (wrapper).
"""

from __future__ import annotations


def parse_work_format(text: str):
    low = (text or "").lower()
    if "удал" in low or "remote" in low:
        return "remote"
    if "гибрид" in low:
        return "hybrid"
    if "офис" in low or "office" in low:
        return "office"
    return None


def parse_employment_type(text: str):
    low = (text or "").lower()
    if "фулл" in low or "full" in low:
        return "full-time"
    if "парт" in low or "part" in low:
        return "part-time"
    if "проект" in low or "project" in low:
        return "project"
    return None


def parse_salary(text: str):
    """Parse salary from text, return (min, max, comment)."""

    low = (text or "").lower()

    numbers = []
    found_k = False

    import re

    parts = re.split(r"[-\s,;|]", low)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        has_k = part.endswith("к") or part.endswith("k")

        digits = "".join(c for c in part if c.isdigit())
        if not digits:
            continue

        try:
            num = int(digits)
        except Exception:
            continue

        if has_k:
            num *= 1000
            found_k = True

        numbers.append(num)

    if not numbers:
        return None, None, None

    if found_k and any(n < 1000 for n in numbers):
        numbers = [n * 1000 if n < 1000 else n for n in numbers]

    numbers = sorted(set(numbers))

    if len(numbers) == 1:
        return None, None, f"около {numbers[0]:,} руб"

    return numbers[0], numbers[-1], None


def parse_location(text: str):
    low = (text or "").lower()

    cities = {
        "москва": "москва",
        "спб": "санкт-петербург",
        "санкт-петербург": "санкт-петербург",
        "питер": "санкт-петербург",
        "екатеринбург": "екатеринбург",
        "казань": "казань",
        "новосибирск": "новосибирск",
    }

    for city_key, city_name in cities.items():
        if city_key in low:
            return city_name, None

    return None, text if len(text or "") < 100 else None


def main() -> int:
    print("=" * 50)
    print("Stage 3 Parsing Functions Test")
    print("=" * 50)

    print("\n1. Work format parsing:")
    tests = [
        ("удалённо", "remote"),
        ("гибридный формат", "hybrid"),
        ("в офис", "office"),
        ("unknown", None),
    ]
    for text, expected in tests:
        result = parse_work_format(text)
        status = "✓" if result == expected else "✗"
        print(f"  {status} '{text}' -> {result} (expected {expected})")

    print("\n2. Employment type parsing:")
    tests = [
        ("фулл тайм", "full-time"),
        ("part-time проект", "part-time"),
        ("project work", "project"),
        ("неизвестно", None),
    ]
    for text, expected in tests:
        result = parse_employment_type(text)
        status = "✓" if result == expected else "✗"
        print(f"  {status} '{text}' -> {result} (expected {expected})")

    print("\n3. Salary parsing:")
    tests = [
        ("200-300к", (200000, 300000)),
        ("150k - 200k", (150000, 200000)),
    ]
    for text, expected_range in tests:
        min_sal, max_sal, comment = parse_salary(text)
        if min_sal and max_sal:
            status = "✓" if (min_sal, max_sal) == expected_range else "✗"
            print(f"  {status} '{text}' -> {min_sal}-{max_sal}")
        else:
            print(f"  ✗ '{text}' -> parsing failed (comment={comment})")

    print("\n4. Location parsing:")
    tests = [
        ("Москва", "москва"),
        ("Санкт-Петербург", "санкт-петербург"),
        ("Казань", "казань"),
    ]
    for text, expected in tests:
        city, region = parse_location(text)
        status = "✓" if city == expected else "✗"
        print(f"  {status} '{text}' -> {city}")

    print("\n" + "=" * 50)
    print("Tests completed!")
    print("=" * 50)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
