"""Create .env at the repo root with your keys.

Values are typed in the terminal (hidden), so they are never pasted into a
chat, a script or a commit. The file is written with permissions 600 and
must stay out of git (.gitignore lists it). Leave a value empty to skip it.

  python3 src/setup_env.py [--force]
Then:  set -a; source .env; set +a
"""
import getpass, os, subprocess, sys

NAMES = [("WILEY_TDM_TOKEN", "Wiley TDM token"), ("ELSEVIER_API_KEY", "Elsevier API key"),
         ("ELSEVIER_INSTTOKEN", "Elsevier institutional token (optional)"), ("OPENALEX_API_KEY", "OpenAlex API key"),
         ("GEMINI_API_KEY", "Gemini API key")]
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
path = os.path.join(root, ".env")
if os.path.exists(path) and "--force" not in sys.argv:
    sys.exit(f"{path} exists; rerun with --force to replace it")
ignored = os.path.exists(os.path.join(root, ".gitignore")) and \
    any(l.strip() == ".env" for l in open(os.path.join(root, ".gitignore")))
if not ignored:
    sys.exit("add .env to .gitignore first")
lines = []
for name, label in NAMES:
    v = getpass.getpass(f"{label} [{name}]: ") if sys.stdin.isatty() else sys.stdin.readline().rstrip("\n")
    v = v.strip()
    if v:
        if any(c in v for c in " \t'\"$`\\"):
            sys.exit(f"{name}: unexpected characters in the value")
        lines.append(f"{name}={v}")
    else:
        lines.append(f"# {name}=")
lines.append("GEMINI_MODEL=gemini-3.8-flash")
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    f.write("\n".join(lines) + "\n")
tracked = subprocess.run(["git", "ls-files", "--error-unmatch", ".env"], cwd=root, capture_output=True).returncode == 0
print(f"wrote {path} ({sum(1 for l in lines if not l.startswith('#')) - 1} keys); load it with: set -a; source .env; set +a")
if tracked:
    print("warning: .env is tracked by git; run: git rm --cached .env")
