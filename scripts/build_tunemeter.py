"""Build deterministic CLI, optional Skill and allowlisted public source archives."""
from pathlib import Path
import hashlib
import io
import json
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def archive(items):
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as stream:
        for name, value in sorted(items.items()):
            info = zipfile.ZipInfo(name, (2026, 10, 19, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            stream.writestr(info, value)
    return target.getvalue()


def main():
    source = ROOT / "src/tunenomics_tunemeter"
    version = re.search(r'__version__ = "(\d+\.\d+\.\d+)"', (source/"__init__.py").read_text())[1]
    license_bytes = (ROOT/"LICENSE").read_bytes()
    source_files = {p.relative_to(ROOT).as_posix(): p.read_bytes() for p in source.rglob("*")
                    if p.is_file() and "__pycache__" not in p.parts and p.suffix in {".py", ".md"}}
    items = {"__main__.py": b"from tunenomics_tunemeter.cli import main\nraise SystemExit(main())\n", "LICENSE": license_bytes}
    items.update({name.removeprefix("src/"): value for name, value in source_files.items()})
    app = archive(items)
    app_digest = hashlib.sha256(app).hexdigest()
    docs = ROOT/"release-docs"
    verification = json.loads((docs/"verification-receipt.json").read_text(encoding="utf-8"))
    if verification["version"] != version:
        raise ValueError("Verification receipt version mismatch")
    if verification["status"] == "passed" and verification.get("app_sha256") != app_digest:
        raise ValueError("Verified app hash mismatch; re-run verification before delivery")
    skill = ROOT/"skills/tunenomics-tunemeter"
    (skill/"scripts").mkdir(exist_ok=True)
    (skill/"scripts/tunemeter.pyz").write_bytes(app)
    (skill/"LICENSE").write_bytes(license_bytes)
    (skill/"verification-receipt.json").write_bytes((docs/"verification-receipt.json").read_bytes())
    cli_items = {"tunemeter.pyz": app, "LICENSE": license_bytes,
                 "README.txt": "请先阅读 START-HERE.md；仅提交复核后的元舵提交包.zip。\n".encode("utf-8")}
    for name in ("START-HERE.md", "SUPPORT.md", "PRIVACY.md", "VERIFICATION.md", "verification-receipt.json"):
        cli_items[name] = (docs/name).read_bytes()
    for name in ("harnesses.md", "provider-contracts.md"):
        cli_items[name] = (skill/"references"/name).read_text(encoding="utf-8").replace("scripts/tunemeter.pyz", "tunemeter.pyz").encode("utf-8")
    skill_items = {(Path(skill.name)/p.relative_to(skill)).as_posix(): p.read_bytes()
                   for p in skill.rglob("*") if p.is_file() and "__pycache__" not in p.parts
                   and (p.suffix in {".md", ".json", ".pyz"} or p == skill/"LICENSE")}
    public = dict(source_files)
    public.update({"README.md": (docs/"GITHUB-README.md").read_bytes(), "LICENSE": license_bytes,
                   "UPSTREAMS.md": (docs/"UPSTREAMS.md").read_bytes(), "pyproject.toml": (ROOT/"pyproject.toml").read_bytes(),
                   ".gitignore": b"__pycache__/\n*.pyc\n.venv/\nbuild/\ndist/\n*.egg-info/\nreports/\nverification/\nAGENTS.md\nCURRENT-STATE.md\nMEMORY.md\n"})
    for name in ("build_tunemeter.py", "verify_tunemeter_release.py", "verify_tunemeter_harnesses.py"):
        public["scripts/"+name] = (ROOT/"scripts"/name).read_bytes()
    for p in docs.iterdir():
        if p.is_file() and p.suffix in {".md", ".json"}:
            public["release-docs/"+p.name] = p.read_bytes()
    for name, value in skill_items.items():
        if not name.endswith(".pyz"):
            public["skills/"+name] = value
    prefix = f"tunenomics-tunemeter-v{version}/"
    outputs = {f"tunenomics-tunemeter-v{version}.pyz": app,
               f"tunenomics-tunemeter-cli-v{version}.zip": archive(cli_items),
               f"tunenomics-tunemeter-skill-v{version}.zip": archive(skill_items),
               f"tunenomics-tunemeter-source-v{version}.zip": archive({prefix+k: v for k, v in public.items()})}
    destination = ROOT/"dist"
    destination.mkdir(exist_ok=True)
    for name, value in outputs.items():
        (destination/name).write_bytes(value)
    receipt = {name: {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()} for name, value in outputs.items()}
    (destination/f"tunenomics-tunemeter-v{version}-checksums.json").write_text(json.dumps(receipt, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"version": version, "skill_files": len(skill_items), "source_files": len(public), "artifacts": receipt}))


if __name__ == "__main__":
    main()
