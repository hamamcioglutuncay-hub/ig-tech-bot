#!/usr/bin/env bash
# Commit öncesi basit gizli bilgi taraması. Eşleşme varsa commit'i durdurur.
# Bulunan değerleri ekrana basmaz; yalnızca dosya adı ve satır numarası gösterir.
set -u
patterns='(AIza[0-9A-Za-z_-]{30,}|IGAA[0-9A-Za-z_-]{20,}|EAA[A-Za-z0-9]{30,}|[0-9]{8,10}:AA[0-9A-Za-z_-]{30,}|ghp_[0-9A-Za-z]{30,}|github_pat_[0-9A-Za-z_]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)'
found=0
while IFS= read -r -d '' f; do
  case "$f" in .env|.env.*) [ "$f" != ".env.example" ] && { echo "❌ $f commit edilemez"; found=1; }; continue;; esac
  [ -f "$f" ] || continue
  hits=$(git show ":$f" 2>/dev/null | grep -nE "$patterns" | cut -d: -f1 | tr '\n' ' ')
  if [ -n "$hits" ]; then echo "❌ Olası gizli bilgi: $f (satır: $hits)"; found=1; fi
done < <(git diff --cached --name-only -z --diff-filter=ACM)
if [ $found -ne 0 ]; then echo "Commit durduruldu. Gizli değeri kaldırın."; exit 1; fi
exit 0
