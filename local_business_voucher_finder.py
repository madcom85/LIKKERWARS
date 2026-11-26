#!/usr/bin/env python3
"""local_business_voucher_finder.py

Findet lokale Geschäfte im Branchenbuch (OpenStreetMap/Overpass) für eine
Stadt und eine Branche, prüft ob sie eine Webseite haben und ob auf der
Webseite Gutscheine angeboten werden.

Verwendung:
    python3 local_business_voucher_finder.py --city "Berlin" --branch "Restaurant"
    python3 local_business_voucher_finder.py --city "München" --branch "Friseur" --max 50
    python3 local_business_voucher_finder.py --city "Hamburg" --branch "alle" -o ergebnisse.csv

Optionen:
    --city      Stadt/Ort
    --branch    Branche (z.B. Restaurant, Friseur, Bäckerei, Apotheke, Hotel, Cafe)
                oder OSM-Tag wie "amenity=restaurant", "shop=*", oder "alle"
    --max       Maximale Anzahl Geschäfte (Default: 30)
    --output    Ausgabedatei (.csv oder .json)
    --delay     Wartezeit zwischen Webseiten-Abrufen in Sekunden (Default: 1.0)
    --no-webcheck  Nur Branchenbuch, keine Webseiten-Prüfung
"""

import argparse
import csv
import json
import re
import sys
import time
import urllib.request
import urllib.parse
import urllib.error

USER_AGENT = "local-business-voucher-finder/1.0 (educational)"


def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            ctype = resp.headers.get("Content-Type", "")
            return resp.status, data, ctype
    except urllib.error.HTTPError as e:
        return e.code, e.read(), ""
    except Exception as e:
        return None, str(e).encode(), ""


# ---------------------------------------------------------------------------
# Branchen -> OSM-Tags
# ---------------------------------------------------------------------------
BRANCH_MAP = {
    "restaurant": [("amenity", "restaurant")],
    "cafe": [("amenity", "cafe")],
    "bar": [("amenity", "bar")],
    "kneipe": [("amenity", "bar")],
    "hotel": [("tourism", "hotel")],
    "apotheke": [("amenity", "pharmacy")],
    "pharmacy": [("amenity", "pharmacy")],
    "friseur": [("shop", "hairdresser")],
    "hairdresser": [("shop", "hairdresser")],
    "bäckerei": [("shop", "bakery")],
    "bakery": [("shop", "bakery")],
    "metzgerei": [("shop", "butcher")],
    "supermarkt": [("shop", "supermarket")],
    "supermarket": [("shop", "supermarket")],
    "blumen": [("shop", "florist")],
    "florist": [("shop", "florist")],
    "buchhandlung": [("shop", "books")],
    "books": [("shop", "books")],
    "optiker": [("shop", "optician")],
    "optician": [("shop", "optician")],
    "tierarzt": [("amenity", "veterinary")],
    "veterinary": [("amenity", "veterinary")],
    "zahnarzt": [("amenity", "dentist")],
    "dentist": [("amenity", "dentist")],
    "arzt": [("amenity", "doctors")],
    "doctors": [("amenity", "doctors")],
    "fitness": [("leisure", "fitness_centre")],
    "fitnessstudio": [("leisure", "fitness_centre")],
    "tankstelle": [("amenity", "fuel")],
    "fuel": [("amenity", "fuel")],
}


def parse_branch(branch):
    b = branch.strip().lower()
    if b in ("alle", "all", "*"):
        return None  # None => any named business
    # raw tag like amenity=restaurant or shop=*
    m = re.fullmatch(r"([a-z_]+)=(.+)", b)
    if m:
        key, val = m.group(1), m.group(2)
        if val == "*":
            return [(key, None)]
        return [(key, val)]
    if b in BRANCH_MAP:
        return BRANCH_MAP[b]
    # fallback: try as amenity and shop
    return [("amenity", b), ("shop", b)]


# ---------------------------------------------------------------------------
# Geocoding (Nominatim)
# ---------------------------------------------------------------------------
def geocode(city):
    queries = [city, city + ", Deutschland", city + ", Germany"]
    for q in queries:
        url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
            "q": q, "format": "json", "limit": 1, "addressdetails": 1
        })
        status, data, _ = http_get(url)
        if status != 200:
            continue
        try:
            arr = json.loads(data.decode("utf-8", errors="replace"))
        except Exception:
            continue
        if arr:
            r = arr[0]
            bbox = r.get("boundingbox")
            osm_type = r.get("osm_type")
            osm_id = r.get("osm_id")
            area_id = None
            if osm_type == "relation":
                area_id = int(osm_id) + 3600000000
            elif osm_type == "way":
                area_id = int(osm_id) + 2400000000
            return {"bbox": bbox, "area_id": area_id, "display": r.get("display_name")}
    return None


# ---------------------------------------------------------------------------
# Overpass query
# ---------------------------------------------------------------------------
def overpass_query(tags, geo, max_n):
    # Build area or bbox filter
    if geo.get("area_id"):
        area_filter = f"area({geo['area_id']})"
        loc = f"(area.a)"
        area_decl = f"area({geo['area_id']})->.a;"
    else:
        s, n, w, e = geo["bbox"]  # south, north, west, east
        loc = f"({s},{w},{n},{e})"
        area_decl = ""
    parts = []
    if tags is None:
        # any named business (amenity or shop)
        for typ in ("node", "way"):
            if area_decl:
                parts.append(f'{typ}["name"]{loc};')
            else:
                parts.append(f'{typ}["name"]{loc};')
    else:
        for key, val in tags:
            for typ in ("node", "way"):
                if val is None:
                    filt = f'["{key}"]["name"]'
                else:
                    filt = f'["{key}"="{val}"]["name"]'
                if area_decl:
                    parts.append(f'{typ}{filt}{loc};')
                else:
                    parts.append(f'{typ}{filt}{loc};')
    query = f"""
[out:json][timeout:25];
{area_decl}
(
  {' '.join(parts)}
);
out center {max_n};
"""
    mirrors = [
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]
    last_err = None
    for attempt in range(2):
        for url in mirrors:
            req = urllib.request.Request(url, data=query.encode("utf-8"), headers={
                "User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"
            })
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except Exception as e:
                last_err = e
                continue
    return {"error": str(last_err), "elements": []}


def extract_business(el):
    tags = el.get("tags", {}) or {}
    name = tags.get("name")
    if not name:
        return None
    # coordinates
    if el.get("type") == "node":
        lat, lon = el.get("lat"), el.get("lon")
    else:
        c = el.get("center", {}) or {}
        lat, lon = c.get("lat"), c.get("lon")
    # address
    street = tags.get("addr:street")
    housenumber = tags.get("addr:housenumber")
    postcode = tags.get("addr:postcode")
    city = tags.get("addr:city")
    addr_parts = []
    if street:
        addr_parts.append(street + (f" {housenumber}" if housenumber else ""))
    if postcode or city:
        addr_parts.append(" ".join(x for x in [postcode, city] if x))
    address = ", ".join(addr_parts) if addr_parts else ""
    website = tags.get("website") or tags.get("contact:website") or tags.get("url")
    phone = tags.get("phone") or tags.get("contact:phone")
    email = tags.get("email") or tags.get("contact:email")
    return {
        "name": name,
        "address": address,
        "lat": lat,
        "lon": lon,
        "website": website,
        "phone": phone,
        "email": email,
        "category": tags.get("amenity") or tags.get("shop") or tags.get("tourism") or tags.get("leisure"),
        "osm_id": el.get("id"),
    }


# ---------------------------------------------------------------------------
# Webseiten-Prüfung auf Gutscheine
# ---------------------------------------------------------------------------
VOUCHER_KEYWORDS = [
    "gutschein", "geschenkgutschein", "geschenk-gutschein", "geschenkkarte",
    "voucher", "gift card", "giftcard", "gift-card", "coupon", "rabattcode",
    "promocode", "promo code", "geschenkidee",
]

VOUCHER_PATHS = ["", "/gutschein", "/gutscheine", "/geschenkgutschein",
                  "/geschenkgutscheine", "/gift-card", "/voucher", "/shop"]


def check_voucher(website, delay=1.0):
    """Gibt (has_website, has_voucher, checked_url, snippet) zurück."""
    if not website:
        return False, False, None, "keine Webseite im Branchenbuch"
    # normalize url
    url = website.strip()
    if not url.startswith("http"):
        url = "https://" + url
    found = False
    checked = None
    snippet = ""
    for path in VOUCHER_PATHS:
        target = url.rstrip("/") + path
        status, data, ctype = http_get(target)
        time.sleep(delay)
        if status != 200:
            continue
        checked = target
        try:
            text = data.decode("utf-8", errors="replace").lower()
        except Exception:
            text = data.decode("latin-1", errors="replace").lower()
        # strip html tags roughly
        plain = re.sub(r"<[^>]+>", " ", text)
        for kw in VOUCHER_KEYWORDS:
            if kw in plain:
                found = True
                # extract snippet
                idx = plain.find(kw)
                start = max(0, idx - 60)
                end = min(len(plain), idx + 60)
                snippet = plain[start:end].replace("\n", " ").strip()
                break
        if found:
            break
    return True, found, checked, snippet


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Lokale Geschäfte finden und auf Gutscheine prüfen.")
    parser.add_argument("--city", required=True, help="Stadt/Ort")
    parser.add_argument("--branch", default="alle", help="Branche oder OSM-Tag (Default: alle)")
    parser.add_argument("--max", type=int, default=30, help="Max. Anzahl Geschäfte (Default: 30)")
    parser.add_argument("-o", "--output", help="Ausgabedatei (.csv oder .json)")
    parser.add_argument("--delay", type=float, default=1.0, help="Wartezeit zwischen Web-Abrufen (Default: 1.0)")
    parser.add_argument("--no-webcheck", action="store_true", help="Keine Webseiten-Prüfung")
    args = parser.parse_args()

    tags = parse_branch(args.branch)
    print(f"Suche Geschäfte in '{args.city}' (Branche: {args.branch}) ...")
    geo = geocode(args.city)
    if not geo:
        print("Stadt nicht gefunden.")
        sys.exit(1)
    print(f"  Gefunden: {geo.get('display')}")

    data = overpass_query(tags, geo, args.max)
    if "error" in data:
        print(f"Overpass-Fehler: {data['error']}")
        sys.exit(1)
    elements = data.get("elements", [])
    businesses = []
    for el in elements:
        b = extract_business(el)
        if b:
            businesses.append(b)
    # dedupe by name+address
    seen = set()
    uniq = []
    for b in businesses:
        key = (b["name"], b["address"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(b)
    businesses = uniq[:args.max]
    print(f"  {len(businesses)} Geschäfte gefunden.\n")

    results = []
    for i, b in enumerate(businesses, 1):
        print(f"[{i}/{len(businesses)}] {b['name']} ({b['category']})")
        if b["website"]:
            print(f"    Webseite: {b['website']}")
        else:
            print("    Keine Webseite im Branchenbuch")
        voucher = False
        checked_url = None
        snippet = ""
        if (not args.no_webcheck) and b["website"]:
            has_web, voucher, checked_url, snippet = check_voucher(b["website"], delay=args.delay)
            print(f"    Gutschein: {'JA' if voucher else 'nein'}")
            if snippet:
                print(f"    Snippet: {snippet[:120]}")
        b["has_voucher"] = voucher
        b["checked_url"] = checked_url
        b["snippet"] = snippet
        results.append(b)

    # summary
    with_web = sum(1 for r in results if r["website"])
    with_voucher = sum(1 for r in results if r["has_voucher"])
    print("\n" + "=" * 60)
    print(f"Zusammenfassung: {len(results)} Geschäfte")
    print(f"  Mit Webseite : {with_web}")
    print(f"  Mit Gutschein: {with_voucher}")
    print("=" * 60)

    if args.output:
        if args.output.lower().endswith(".json"):
            with open(args.output, "w", encoding="utf-8") as fh:
                json.dump(results, fh, ensure_ascii=False, indent=2)
        else:
            fields = ["name", "category", "address", "website", "phone", "email",
                      "has_voucher", "checked_url", "snippet", "lat", "lon"]
            with open(args.output, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
                w.writeheader()
                for r in results:
                    w.writerow(r)
        print(f"Ergebnisse gespeichert in: {args.output}")


if __name__ == "__main__":
    main()
