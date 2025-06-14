# .github/scripts/update_maps_json.py

from __future__ import annotations
import hashlib, json, os, re, subprocess, sys
from urllib.parse import quote
from pathlib import Path

# -------------------------------------------------------------------
ROOT      = Path(__file__).resolve().parents[2]          # repo root
MAPS_DIR  = ROOT / "campaigns"
MAPS_JSON = ROOT / "maps.json"

# -------------------------------------------------------------------
def owner_repo() -> str:
    # 1 – GitHub Actions env
    if (env := os.getenv("GITHUB_REPOSITORY")) and "/" in env:
        return env
    # 2 – local git remote
    try:
        url = subprocess.check_output(
            ["git", "config", "--get", "remote.origin.url"], text=True
        ).strip()
        m = re.search(r"[/:]([^/]+)/([^/]+?)(?:\.git)?$", url)
        if m:
            return f"{m.group(1)}/{m.group(2)}"
    except Exception:
        pass
    sys.exit("❌  Unable to determine <owner>/<repo>")
RAW_BASE = f"https://raw.githubusercontent.com/{owner_repo()}/main/"

# -------------------------------------------------------------------
VER_RE = re.compile(r"^(?P<maj>\d+)\.(?P<min>\d+)$")
def bump_minor(ver: str | None) -> str:
    m = VER_RE.match(ver or "") or VER_RE.match("1.0")
    maj, mn = map(int, m.groups())
    return f"{maj}.{mn+1}"

def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

# -------------------------------------------------------------------
def alnum_only(s: str) -> str:
    """Remove every non-alphanumeric char."""
    return "".join(ch for ch in s if ch.isalnum())

# -------------------------------------------------------------------
current_blocks: list[dict] = json.loads(MAPS_JSON.read_text()) if MAPS_JSON.exists() else []
current_by_folder = {b.get("folder", b["title"]): b for b in current_blocks}

new_manifest: list[dict] = []

for camp_dir in sorted(MAPS_DIR.iterdir()):
    if not camp_dir.is_dir():
        continue

    folder       = camp_dir.name
    pretty_title = current_by_folder.get(folder, {}).get("title") or folder
    asset_png    = f"{pretty_title}.png"

    old_block  = current_by_folder.get(folder, {})
    old_maps   = {m["name"]: m for m in old_block.get("maps", [])}
    camp_ver   = old_block.get("version", "1.0")

    paths  = list(camp_dir.glob("*.SC2Map"))
    paths += list((camp_dir / "mods").glob("*.SC2Mod"))

    keep_release = {n: e for n, e in old_maps.items() if e.get("release_asset")}

    new_entries: list[dict] = []
    for pth in sorted(paths, key=lambda p: p.name.lower()):
        name, digest = pth.name, sha256(pth)
        entry = old_maps.get(name, {"name": name, "version": "1.0", "sha256": ""})

        if entry["sha256"] != digest:
            entry["version"] = bump_minor(entry["version"])
            entry["sha256"]  = digest

        entry["url"] = RAW_BASE + quote(pth.relative_to(ROOT).as_posix())
        new_entries.append(entry)

    # keep orphaned release_asset records
    names_present = {e["name"] for e in new_entries}
    new_entries.extend(e for n, e in keep_release.items() if n not in names_present)

    # launcher first
    new_entries.sort(key=lambda m: (0 if "launcher" in m["name"].lower() else 1,
                                    m["name"].lower()))

    # bump campaign version if anything changed
    old_sorted = sorted(old_maps.values(), key=lambda m: m["name"])
    if (len(new_entries) != len(old_sorted)
        or any(a["sha256"] != b["sha256"] or a["version"] != b["version"]
               for a, b in zip(sorted(new_entries, key=lambda m: m["name"]), old_sorted))):
        camp_ver = bump_minor(camp_ver)

    block = {
        "title":   pretty_title,
        "version": camp_ver,
        "asset":   asset_png,
        "maps":    new_entries
    }

    auto_folder = alnum_only(pretty_title)
    if auto_folder != pretty_title:
        block["folder"] = auto_folder
    else:

        if folder != pretty_title:
            block["folder"] = folder

    new_manifest.append(block)

# -------------------------------------------------------------------
MAPS_JSON.write_text(json.dumps(new_manifest, indent=2))
print("✅ maps.json complete")
