"""Package-level coupling (Robert C. Martin metrics) via static AST import scan.
Ce = efferent coupling (distinct internal packages this one depends on)
Ca = afferent coupling (distinct internal packages that depend on this one)
I  = instability = Ce / (Ca + Ce)   (0 = stable, 1 = unstable)
No code is imported/executed, so torch/CUDA are irrelevant -> robust & reproducible.
"""
import ast, os, sys
from pathlib import Path
from collections import defaultdict

root = Path(sys.argv[1]).resolve()
# internal top-level roots: package dirs (have __init__.py or contain .py) + root modules
PKG_DIRS = ["comfy","comfy_execution","comfy_api","comfy_api_nodes","comfy_config",
            "comfy_extras","app","api_server","middleware","utils"]
ROOT_MODS = ["main","nodes","execution","server","folder_paths","node_helpers",
             "latent_preview","cuda_malloc","node_helpers","comfyui_version","protocol"]
internal = set(PKG_DIRS) | set(ROOT_MODS)

def pkg_of(path: Path) -> str:
    rel = path.relative_to(root)
    top = rel.parts[0]
    return top if top in PKG_DIRS else rel.stem  # root module -> its own name

edges = defaultdict(set)   # pkg -> set of pkgs it imports
files_per_pkg = defaultdict(int)
nodes_importers = set()    # modules importing the top-level `nodes` module (for P2)

def roots_from_import(node):
    out = []
    if isinstance(node, ast.Import):
        for a in node.names:
            out.append(a.name.split(".")[0])
    elif isinstance(node, ast.ImportFrom):
        if node.level and node.level > 0:
            return []  # relative import stays within same package
        if node.module:
            out.append(node.module.split(".")[0])
    return out

targets = [root/d for d in PKG_DIRS] + [root/f"{m}.py" for m in ROOT_MODS]
for t in targets:
    pyfiles = [t] if t.is_file() else list(t.rglob("*.py"))
    for f in pyfiles:
        try:
            tree = ast.parse(f.read_text(errors="ignore"))
        except SyntaxError:
            continue
        src = pkg_of(f)
        files_per_pkg[src] += 1
        for n in ast.walk(tree):
            for r in roots_from_import(n):
                if r in internal and r != src:
                    edges[src].add(r)
                if r == "nodes" and src != "nodes":
                    nodes_importers.add(str(f.relative_to(root)))

all_pkgs = sorted(set(list(edges.keys()) + [p for s in edges.values() for p in s]))
ca = defaultdict(set); ce = defaultdict(set)
for src, deps in edges.items():
    for d in deps:
        ce[src].add(d); ca[d].add(src)

print(f"{'package':24}{'files':>6}{'Ce':>5}{'Ca':>5}{'I':>7}")
print("-"*47)
rows=[]
for p in all_pkgs:
    cce=len(ce[p]); cca=len(ca[p]); I = cce/(cca+cce) if (cca+cce) else 0.0
    rows.append((p,files_per_pkg.get(p,0),cce,cca,I))
for p,fn,cce,cca,I in sorted(rows, key=lambda r:-r[4]):
    print(f"{p:24}{fn:>6}{cce:>5}{cca:>5}{I:>7.2f}")
print(f"\n'nodes' module afferent coupling (modules that import top-level `nodes`): {len(nodes_importers)}")
for m in sorted(nodes_importers)[:12]:
    print("   ", m)
