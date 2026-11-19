"""City bounding boxes shared by every geo download script.

bbox order is (west, south, east, north) in WGS84 degrees.

Groups:
  core    TBO-relevant outbound destinations; the matching benchmark is built on these.
  india   overlap with the MakeMyTrip / Goibibo hotel samples.
  europe  overlap with the 515K Booking.com review set (1,493 hotels in six cities).
"""

CITIES = {
    # core
    "dubai": {"bbox": (54.89, 24.79, 55.57, 25.36), "group": "core", "wikivoyage": "Dubai", "lang": "ar"},
    "bangkok": {"bbox": (100.33, 13.49, 100.94, 13.96), "group": "core", "wikivoyage": "Bangkok", "lang": "th"},
    "singapore": {"bbox": (103.60, 1.20, 104.05, 1.48), "group": "core", "wikivoyage": "Singapore", "lang": "zh"},
    # india
    "delhi": {"bbox": (76.84, 28.40, 77.35, 28.88), "group": "india", "wikivoyage": "Delhi", "lang": "hi"},
    "mumbai": {"bbox": (72.77, 18.89, 73.00, 19.28), "group": "india", "wikivoyage": "Mumbai", "lang": "hi"},
    "goa": {"bbox": (73.67, 14.89, 74.34, 15.80), "group": "india", "wikivoyage": "Goa", "lang": "hi"},
    # europe
    "london": {"bbox": (-0.51, 51.28, 0.33, 51.69), "group": "europe", "wikivoyage": "London", "lang": "en"},
    "paris": {"bbox": (2.22, 48.81, 2.47, 48.91), "group": "europe", "wikivoyage": "Paris", "lang": "fr"},
    "amsterdam": {"bbox": (4.73, 52.28, 5.08, 52.43), "group": "europe", "wikivoyage": "Amsterdam", "lang": "nl"},
    "barcelona": {"bbox": (2.05, 41.32, 2.23, 41.47), "group": "europe", "wikivoyage": "Barcelona", "lang": "es"},
    "vienna": {"bbox": (16.18, 48.12, 16.58, 48.32), "group": "europe", "wikivoyage": "Vienna", "lang": "de"},
    "milan": {"bbox": (9.04, 45.39, 9.28, 45.54), "group": "europe", "wikivoyage": "Milan", "lang": "it"},
}

# Extra Wikivoyage pages for destinations that are not a single article with district sub-pages.
WIKIVOYAGE_EXTRA = {
    "goa": [
        "Panaji", "Calangute", "Baga", "Candolim", "Anjuna", "Palolem", "Margao", "Vasco da Gama",
        "Colva", "Arambol", "Old Goa", "Mapusa", "Benaulim", "Agonda", "Morjim", "Vagator", "North Goa", "South Goa",
    ],
}

USER_AGENT = "canon-benchmark-builder/0.1 (hackathon research; polite; contact via repo)"
