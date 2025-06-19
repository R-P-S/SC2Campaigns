# .github/scripts/update_maps_json.py

from __future__ import annotations
import hashlib, json, os, re, subprocess, sys
from urllib.parse import quote
from pathlib import Path

# ────────────────────────────────────────────────────────────────────
ROOT      = Path(__file__).resolve().parents[2]          # repo root
MAPS_DIR  = ROOT / "campaigns"
MAPS_JSON = ROOT / "maps.json"

# ── derive owner/repo for RAW urls ─────────────────────────────────
def owner_repo() -> str:
    if (env := os.getenv("GITHUB_REPOSITORY")) and "/" in env:
        return env
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

# ── helpers ────────────────────────────────────────────────────────
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

def slug(s: str) -> str:
    """alphanumeric-only, lower-case."""
    return re.sub(r"[^0-9A-Za-z]", "", s).lower()

# ── load current manifest – index by folder **and** by slug ───────
if MAPS_JSON.exists():
    current_blocks: list[dict] = json.loads(MAPS_JSON.read_text())
else:
    current_blocks = []

current_by_folder: dict[str, dict] = {}
for blk in current_blocks:
    key = blk.get("folder", blk["title"])
    current_by_folder[key] = blk
    current_by_folder[slug(key)]   = blk
    current_by_folder[slug(blk["title"])] = blk 

# ── rebuild manifest ───────────────────────────────────────────────
new_manifest: list[dict] = []

for camp_dir in sorted(MAPS_DIR.iterdir()):
    if not camp_dir.is_dir():
        continue

    folder       = camp_dir.name
    pretty_title = current_by_folder.get(folder, {}).get("title") or folder
    asset_png    = f"{pretty_title}.png"

    old_block  = current_by_folder.get(folder) \
                 or current_by_folder.get(slug(folder), {})
    old_maps   = {m["name"]: m for m in old_block.get("maps", [])}
    camp_ver   = old_block.get("version", "1.0")

    # ─ collect on-disk maps / mods ────────────────────────────────
    files  = list(camp_dir.glob("*.SC2Map"))
    files += list((camp_dir / "mods").glob("*.SC2Mod"))

    keep_release = {n: e for n, e in old_maps.items() if e.get("release_asset")}

    new_entries: list[dict] = []
    for pth in sorted(files, key=lambda p: p.name.lower()):
        name   = pth.name
        digest = sha256(pth)
        entry  = old_maps.get(name, {"name": name, "version": "1.0", "sha256": ""})

        if entry["sha256"] != digest:
            entry["version"] = bump_minor(entry["version"])
            entry["sha256"]  = digest

        entry["url"] = RAW_BASE + quote(pth.relative_to(ROOT).as_posix())
        new_entries.append(entry)

    # append orphaned release assets
    present = {e["name"] for e in new_entries}
    new_entries += [e for n, e in keep_release.items() if n not in present]

    # launcher first
    new_entries.sort(key=lambda m: (0 if "launcher" in m["name"].lower() else 1,
                                    m["name"].lower()))

    # bump campaign version if maps changed
    old_sorted = sorted(old_maps.values(), key=lambda m: m["name"])
    if (len(new_entries) != len(old_sorted) or
        any(a["sha256"] != b["sha256"] or a["version"] != b["version"]
            for a, b in zip(sorted(new_entries, key=lambda m: m["name"]),
                            old_sorted))):
        camp_ver = bump_minor(camp_ver)

    block = {
        "title":   pretty_title,
        "version": camp_ver,
        "asset":   asset_png,
        "maps":    new_entries
    }

    # auto-generated folder slug (if needed)
    auto_folder = slug(pretty_title)
    if auto_folder != pretty_title:
        block["folder"] = auto_folder
    elif folder != pretty_title:       # prefer explicit folder when it differs
        block["folder"] = folder

    new_manifest.append(block)

# ── write out ──────────────────────────────────────────────────────
MAPS_JSON.write_text(json.dumps(new_manifest, indent=2))
print("✅ maps.json complete")
