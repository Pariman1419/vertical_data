"""Reproduce the approved browser-native ESM vendor tree. No npm install or build step.

Only pinned registry tarballs are downloaded; verify SHA-512 before reading members.
Only JS in the package's ESM directory and its MIT license is extracted into a temporary
directory; relative imports remain relative and the one bare dependency is rewritten.
"""
import base64
import hashlib
import io
import json
import pathlib
import re
import tarfile
import tempfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
PINS = {
    "query-core": ("5.90.4", "build/modern", "index.js"),
    "table-core": ("8.21.3", "build/lib", "index.mjs"),
    "virtual-core": ("3.13.12", "dist/esm", "index.js"),
    "form-core": ("1.0.0", "dist/esm", "index.js"),
    "store": ("0.7.0", "dist/esm", "index.js"),
}


def main():
    manifest, licenses, entries = {}, [], []
    with tempfile.TemporaryDirectory(prefix="uetl-tanstack-") as temp:
        stage = pathlib.Path(temp)
        for name, (version, directory, entry) in PINS.items():
            package = "@tanstack/" + name
            url = f"https://registry.npmjs.org/{package}/-/{name}-{version}.tgz"
            with urllib.request.urlopen(url, timeout=30) as response:
                raw = response.read(10_000_001)
            if len(raw) > 10_000_000:
                raise ValueError("tarball exceeds download budget")
            expected = INTEGRITIES[name].removeprefix("sha512-")
            if base64.b64encode(hashlib.sha512(raw).digest()).decode() != expected:
                raise ValueError("Registry tarball integrity mismatch: " + name)
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
                for member in archive.getmembers():
                    path = pathlib.PurePosixPath(member.name)
                    if not member.isfile() or ".." in path.parts or path.is_absolute():
                        continue
                    if path.name.upper() in ("LICENSE", "LICENSE.MD", "LICENSE.TXT"):
                        licenses.append(f"## {package}@{version}\n\n" + archive.extractfile(member).read().decode())
                    prefix = "package/" + directory + "/"
                    if not member.name.startswith(prefix) or not member.name.endswith((".js", ".mjs")):
                        continue
                    # table-core's import entry is a complete ESM build; its .js siblings are CJS.
                    if name == "table-core" and member.name != prefix + entry:
                        continue
                    relative = member.name[len(prefix):]
                    text = archive.extractfile(member).read().decode()
                    text = re.sub(r"\n?//# sourceMappingURL=.*", "", text)
                    text = text.replace("process.env.NODE_ENV", '"production"')
                    if name == "form-core":
                        store_path = pathlib.PurePosixPath(relative).parent
                        target = "../" * (len(store_path.parts) + 1) + "store/index.js"
                        text = re.sub(r'([\'\"])@tanstack/store\1', lambda m: m[1] + target + m[1], text)
                    dest = stage / name / relative
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(text.encode())
                    manifest[f"{name}/{relative}"] = {"package": package, "version": version,
                        "sha256": hashlib.sha256(dest.read_bytes()).hexdigest()}
            entries.append(f"import * as {name.replace('-', '_')} from './{name}/{entry}';")
        entries += ["globalThis.TanStack = { ...query_core, ...table_core, ...virtual_core, ...form_core, ...store };",
                    "export const TanStack = globalThis.TanStack;"]
        (stage / "index.js").write_bytes(("\n".join(entries) + "\n").encode())
        (stage / "LICENSES.md").write_bytes(("# TanStack MIT licenses\n\n" + "\n\n".join(licenses)).encode())
        (stage / "package.json").write_bytes(b'{"type":"module"}\n')
        for name in ("index.js", "LICENSES.md", "package.json"):
            manifest[name] = {"package": "uetl-vendor", "version": "1", "sha256": hashlib.sha256((stage / name).read_bytes()).hexdigest()}
        dest = ROOT / "vendor" / "tanstack"
        existing = {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()} if dest.exists() else set()
        if existing - set(manifest) - {"MANIFEST.json"}:
            raise ValueError("Unexpected old vendor files; review before replacing the tree")
        for name in sorted(manifest):
            target = dest / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((stage / name).read_bytes())
            print(name, manifest[name]["sha256"])
        (dest / "MANIFEST.json").write_bytes((json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())


# Filled from the approved registry metadata, never refreshed implicitly during vendoring.
INTEGRITIES = {'query-core': 'sha512-+IbzYym9wonJss2+ZXrQqdGhPozHV8BzgZRRHxkLtL2Oq+/wAuwkLMKXk6NbAbbj+Ipgd/kMjUenjGWfwKYDwA==', 'table-core': 'sha512-ldZXEhOBb8Is7xLs01fR3YEc3DERiz5silj8tnGkFZytt1abEvl/GhUmCE0PMLaMPTa3Jk4HbKmRlHmu+gCftg==', 'virtual-core': 'sha512-1YBOJfRHV4sXUmWsFSf5rQor4Ss82G8dQWLRbnk3GA4jeP8hQt1hxXh0tmflpC0dz3VgEv/1+qwPyLeWkQuPFA==', 'form-core': 'sha512-GHYjF9m+FjXbIMpbMP1Ru8XzTJnQDva9wkw3E/fXUIPAtx0NmTGrefxUGqs7/aCT2uSqdrmzRyVFUJObemx51Q==', 'store': 'sha512-CNIhdoUsmD2NolYuaIs8VfWM467RK6oIBAW4nPEKZhg1smZ+/CwtCdpURgp7nxSqOaV9oKkzdWD80+bC66F/Jg=='}

if __name__ == "__main__":
    main()
