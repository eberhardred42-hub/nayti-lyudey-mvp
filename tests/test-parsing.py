#!/usr/bin/env python3
"""
Quick test of parsing logic for Stage 3 Vacancy KB (without FastAPI)
"""

import re
from datetime import datetime

def parse_work_format(text):
    """Simple heuristic for work_format from text."""
    low = text.lower()
    if "удал" in low or "remote" in low:
        return "remote"
    elif "гибрид" in low:
        return "hybrid"
    elif "офис" in low or "office" in low:
        return "office"
    return None


def parse_employment_type(text):
    """Simple heuristic for employment_type from text."""
    low = text.lower()
    if "фулл" in low or "full" in low:
        return "full-time"
    elif "парт" in low or "part" in low:
        return "part-time"
    elif "проект" in low or "project" in low:
        return "project"
    return None


def parse_salary(text):
    """Parse salary from text, return (min, max, comment)."""
    low = text.lower()
    
    # Find all numbers, including check for 'к' suffix
    # Handle patterns: 200к, 200 000, 200-300к, etc.
    pattern = r'(\d+(?:\s\d+)*)\s*[кК]?'
    
    numbers = []
    found_k = False
    
    # Simple approach: split by common delimiters and find numbers
    import re
    # Look for number patterns with possible 'к' suffix
    parts = re.split(r'[-\s,;|]', low)
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
        
        # Check if ends with 'к'
        has_k = part.endswith('к') or part.endswith('k')
        
        # Extract just digits
        digits = ''.join(c for c in part if c.isdigit())
        if digits:
            try:
                num = int(digits)
                if has_k:
                    num *= 1000
                    found_k = True
                numbers.append(num)
            except:
                pass
    
    if not numbers:
        return None, None, None
    
    # If we found 'к' and have small numbers without it, multiply them too
    if found_k and any(n < 1000 for n in numbers):
        numbers = [n * 1000 if n < 1000 else n for n in numbers]
    
    # Remove duplicates and sort
    numbers = sorted(set(numbers))
    
    if len(numbers) == 1:
        return None, None, f"около {numbers[0]:,} руб"
    elif len(numbers) >= 2:
        return numbers[0], numbers[-1], None
    
    return None, None, None


def parse_location(text):
    """Parse location from text, return (city, region)."""
    low = text.lower()
    
    # Simple dictionary of major Russian cities
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
    
    # If no city found, try to extract as region
    return None, text if len(text) < 100 else None


print("=" * 50)
print("Stage 3 Parsing Functions Test")
print("=" * 50)

# Test 1: Work format parsing
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

# Test 2: Employment type parsing
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

# Test 3: Salary parsing
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
        print(f"  ✗ '{text}' -> parsing failed")

# Test 4: Location parsing
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
