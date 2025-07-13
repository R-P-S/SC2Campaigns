#sync_shared_assets

from pathlib import Path
from collections import Counter 
import hashlib, json, shutil, subprocess, sys

ROOT   = Path(__file__).resolve().parents[2]
CAMPS  = ROOT / "campaigns"
MANIF  = ROOT / "maps.json"

def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

if not MANIF.is_file():
    sys.exit("maps.json missing – run update_maps_json.py first")

manifest = json.loads(MANIF.read_text())

# Count how many times every flagged filename appears
cnt = Counter(
    m["name"]
    for camp in manifest
    for m in camp["maps"]
    if m.get("shared_asset")      
)

# Keep only those that are referenced by ≥ 2 campaigns
shared_names = {name for name, n in cnt.items() if n > 1}

# log shared asset error
loners = [name for name, n in cnt.items() if n == 1]
for n in loners:
    print(f"⚠️  {n} is marked shared_asset but only appears once")

# -----------------------------------------------------------------
# locate every on-disk copy
# -----------------------------------------------------------------
copies: dict[str, list[Path]] = {n: [] for n in shared_names}
for path in CAMPS.rglob("*"):
    if path.name in copies:
        copies[path.name].append(path)

# -----------------------------------------------------------------
# for each shared asset choose *one* source copy
# -----------------------------------------------------------------
def modified_in_this_push(p: Path) -> bool:
    try:
        base = subprocess.check_output(
            ["git", "merge-base", "HEAD", "origin/main"], text=True
        ).strip()
        out = subprocess.check_output(
            ["git", "diff", "--name-only", base, "HEAD", "--", str(p)],
            text=True
        )
        return bool(out.strip())
    except Exception:
        return False

for name, paths in copies.items():
    if not paths:
        print(f"❗ {name} is referenced but no copy exists on disk")
        continue

    src = next((p for p in paths if modified_in_this_push(p)), None)
    if src is None:
        src = max(paths, key=lambda p: p.stat().st_mtime)

    src_digest = sha256(src)
    print(f"↳ canonical {name} = {src} ({src_digest[:8]}…)")

# ----------------------------------------------------------------
# replicate into every other campaign folder if needed
# ----------------------------------------------------------------
    for dst in paths:
        if dst.samefile(src):
            continue
        if dst.is_file() and sha256(dst) == src_digest:
            continue                          # already up-to-date

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"    → updated {dst.relative_to(ROOT)}")
