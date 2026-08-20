#!/usr/bin/env bash
#
# Installe (ou réinstalle) les skills du dépôt dans ~/.hermes/skills/, puis
# vérifie que la copie correspond exactement au dépôt.
#
#   ./scripts/install-skill.sh              installe et vérifie
#   ./scripts/install-skill.sh --check      vérifie seulement, n'écrit rien
#   ./scripts/install-skill.sh --dry-run    montre ce qui serait fait
#
# Pourquoi une copie et pas un lien symbolique : Hermes refuse de monter un
# arbre de skills contenant le moindre lien symbolique dans son bac à sable.
# Il en fabrique alors une copie assainie d'où les liens sont *retirés* — et
# la skill liée disparaît silencieusement du conteneur. Voir le README.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_ROOT="$REPO/skills"
DEST_ROOT="${HERMES_HOME:-$HOME/.hermes}/skills"

MODE="install"
case "${1:-}" in
  --check)   MODE="check" ;;
  --dry-run) MODE="dry-run" ;;
  "")        ;;
  *) echo "usage: $0 [--check|--dry-run]" >&2; exit 2 ;;
esac

rouge()  { printf '\033[31m%s\033[0m\n' "$*"; }
vert()   { printf '\033[32m%s\033[0m\n' "$*"; }
jaune()  { printf '\033[33m%s\033[0m\n' "$*"; }

[ -d "$SRC_ROOT" ] || { rouge "Introuvable : $SRC_ROOT"; exit 1; }

# Les skills du dépôt, repérées par la présence d'un SKILL.md.
mapfile -t SKILLS < <(cd "$SRC_ROOT" && find . -name SKILL.md -printf '%h\n' | sed 's|^\./||' | sort)
[ "${#SKILLS[@]}" -gt 0 ] || { rouge "Aucune skill (aucun SKILL.md) sous $SRC_ROOT"; exit 1; }

echo "Dépôt      : $REPO"
echo "Destination: $DEST_ROOT"
echo "Skills     : ${SKILLS[*]}"
echo

# ---------------------------------------------------------------------------
# Garde-fou : aucun lien symbolique ne doit entrer dans l'arbre des skills.
# ---------------------------------------------------------------------------
liens_source=$(find "$SRC_ROOT" -type l 2>/dev/null || true)
if [ -n "$liens_source" ]; then
  rouge "Liens symboliques dans le dépôt — Hermes les retirerait du bac à sable :"
  echo "$liens_source" | sed 's/^/  /'
  exit 1
fi

if [ "$MODE" = "dry-run" ]; then
  for skill in "${SKILLS[@]}"; do
    echo "  rm -rf $DEST_ROOT/$skill"
    echo "  cp -r  $SRC_ROOT/$skill  $DEST_ROOT/$skill"
  done
  echo; jaune "Rien n'a été écrit (--dry-run)."
  exit 0
fi

# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------
if [ "$MODE" = "install" ]; then
  for skill in "${SKILLS[@]}"; do
    dest="$DEST_ROOT/$skill"
    mkdir -p "$(dirname "$dest")"
    rm -rf "$dest"
    cp -r "$SRC_ROOT/$skill" "$dest"
    echo "  installé : $skill"
  done
  echo
fi

# ---------------------------------------------------------------------------
# Vérification : la copie est-elle identique au dépôt ?
# ---------------------------------------------------------------------------
echec=0
for skill in "${SKILLS[@]}"; do
  dest="$DEST_ROOT/$skill"
  if [ ! -d "$dest" ]; then
    rouge "  absente de la destination : $skill"; echec=1; continue
  fi
  # __pycache__ est produit à l'exécution, il ne fait pas partie du dépôt.
  if diff -r -x '__pycache__' -x '*.pyc' "$SRC_ROOT/$skill" "$dest" > /tmp/install-skill.diff 2>&1; then
    n=$(find "$dest" -type f -not -path '*/__pycache__/*' | wc -l)
    somme=$(cd "$dest" && find . -type f -not -path './__pycache__/*' -print0 \
            | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-16)
    vert "  identique : $skill ($n fichiers, empreinte $somme)"
  else
    rouge "  DIVERGENTE : $skill"; sed 's/^/      /' /tmp/install-skill.diff | head -20; echec=1
  fi
done

# Un seul lien symbolique n'importe où dégrade *toutes* les skills installées.
liens_dest=$(find "$DEST_ROOT" -type l 2>/dev/null || true)
if [ -n "$liens_dest" ]; then
  echo
  rouge "Liens symboliques dans $DEST_ROOT — ils feront disparaître les skills du bac à sable :"
  echo "$liens_dest" | sed 's/^/  /'
  echec=1
fi

echo
if [ "$echec" -eq 0 ]; then
  vert "OK — la copie installée correspond au dépôt."
else
  rouge "ÉCHEC — la copie installée ne correspond pas au dépôt."
fi
exit "$echec"
