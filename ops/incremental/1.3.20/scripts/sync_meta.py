import sys, re, pathlib
v = sys.argv[1] if len(sys.argv) > 1 else "1.3.20"
n = 0
for f in ("/opt/material_matcher/current/release-manifest.json", "/opt/material_matcher/current/BUILD_INFO.txt"):
    p = pathlib.Path(f)
    if not p.is_file():
        continue
    t = p.read_text(encoding="utf-8")
    t2 = re.sub(r'"release_version": *"[0-9.]+"', '"release_version": "%s"' % v, t)
    t2 = re.sub(r"(version[=:\"] *)1\.3\.1[0-9]+", r"\g<1>%s" % v, t2)
    if t2 != t:
        p.write_text(t2, encoding="utf-8"); n += 1
print("meta-synced files:", n)
