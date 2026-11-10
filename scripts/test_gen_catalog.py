# Offline test of gen_catalog.py: native packages (rpm, deb, exe) come out with the right platform; unsigned ones are left out.
# Run: python3 -I scripts/test_gen_catalog.py
import importlib.util, sys
spec = importlib.util.spec_from_file_location("g", __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "gen_catalog.py")); g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
names = ["fs-store-0.0.9-linux-x86_64.tar.gz","fs-store-0.0.9-1.x86_64.rpm","fs-store-0.0.9-1.aarch64.rpm","fs-store_0.0.9-1_amd64.deb","fs-store_0.0.9-1_arm64.deb","fs-store-0.0.9-windows-x86_64-setup.exe","fs-store-0.0.9-windows-x86_64.zip","SHA256SUMS.txt"]
assets = [{"name": n, "browser_download_url": "https://x/"+n} for n in names] + [{"name": n+".asc", "browser_download_url": "https://x/"+n+".asc"} for n in names[:-3]+[names[5]]]
g.gh = lambda path: {"tag_name": "v0.0.9", "draft": False, "assets": assets}
g.sums = lambda r: {n: "ab" for n in names}
x = g.entry({"repo": "FreeSynergy/fs-store", "tag": "v0.0.9", "asset": "fs-store-{version}-linux-x86_64.tar.gz", "id": "fs-store", "name": "S", "summary": "s"})
import re
assert sorted(re.findall(r'platform="([^"]+)" fs-format="([^"]+)"', x)) == sorted([("aarch64-linux-gnu","rpm"),("x86_64-linux-gnu","rpm"),("x86_64-windows-msvc","exe"),("x86_64-linux-gnu","deb"),("aarch64-linux-gnu","deb")])
print("ok")
