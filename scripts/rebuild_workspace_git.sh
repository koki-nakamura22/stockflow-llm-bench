#!/usr/bin/env bash
# 各 run の workspace/ に git リポジトリを復元する。
#
# 公開リポジトリでは workspace/.git を同梱していない(nested git repo は
# GitHub 上で正しく追跡できないため)。代わりに submission.patch と
# results/BASELINE_MANIFEST.tsv を同梱しており、このスクリプトで
# 「baseline commit + モデルの変更を未コミット差分として持つ」元の状態を復元する。
#
#   使い方: scripts/rebuild_workspace_git.sh [run_dir ...]
#           引数なしで results/ 配下の全 run を対象にする。
#
# 復元後は元どおり以下が使える:
#   git -C <workspace> status --short   (= 同梱の changed-files.txt と一致)
#   git -C <workspace> diff             (= 同梱の submission.patch と一致)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$ROOT/results/BASELINE_MANIFEST.tsv"
GIT_ID=(-c user.name=benchmark -c user.email=benchmark@localhost -c commit.gpgsign=false)

rebuild_one() {
  local run="$1"
  local ws="$run/workspace"
  local patch="$run/submission.patch"
  [ -d "$ws" ] || { echo "skip (no workspace): $run" >&2; return 0; }
  [ -e "$ws/.git" ] && { echo "skip (already a repo): $ws"; return 0; }

  git "${GIT_ID[@]}" -C "$ws" init -q -b main
  # モデルの変更を巻き戻して baseline の状態にする
  if [ -s "$patch" ]; then git -C "$ws" apply -R --whitespace=nowarn "$patch"; fi
  git -C "$ws" add -A
  git "${GIT_ID[@]}" -C "$ws" commit -q -m "benchmark baseline"
  # モデルの変更を未コミット差分として戻す
  if [ -s "$patch" ]; then git -C "$ws" apply --whitespace=nowarn "$patch"; fi
  # bench/workflow.py の save_patch() と同じく intent-to-add を立てる
  # (モデルが新規作成したファイルが status で ?? ではなく A と出る状態にする)
  git -C "$ws" add -N .

  # manifest に記録された baseline tree と一致するか検証
  local want got rel
  rel="${run#"$ROOT"/}"
  want="$(awk -F'\t' -v r="$rel" '$1==r{print $6}' "$MANIFEST" 2>/dev/null || true)"
  got="$(git -C "$ws" rev-parse 'HEAD^{tree}')"
  if [ -n "$want" ] && [ "$want" != "$got" ]; then
    echo "WARN baseline tree mismatch: $rel (want $want, got $got)" >&2
    return 1
  fi
  echo "ok $rel  baseline=$got"
}

if [ $# -gt 0 ]; then
  for r in "$@"; do rebuild_one "$r"; done
else
  while IFS= read -r ws; do rebuild_one "$(dirname "$ws")"; done \
    < <(find "$ROOT/results" -name workspace -type d | sort)
fi
