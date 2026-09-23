#!/bin/sh
# 鍵らしいものが混ざっていないか調べる。**判定はこのファイルにだけ置く**
# （`.githooks/pre-commit` と `.github/workflows/secrets.yml` の両方がこれを呼ぶ。
#  2 か所に書くと必ずずれる）。
#
#   sh scripts/scan_secrets.sh staged   # これからコミットするものを見る（フック用）
#   sh scripts/scan_secrets.sh tree     # 追跡ファイル全部を見る（CI 用）
#
# 見つかったら 1 を返し、何があったかを出す。**値そのものは出さない**
# （端末の履歴や CI のログに鍵が残らないよう、行番号と変数名だけ）。
#
# なぜ要るか: 2026-09-14 に `.env.bak-before-customdomain`（R2 の鍵と Discogs のトークン）を
# 公開リポジトリへ入れてしまい、5 日間そのままだった（docs/gotchas.md）。
# GitHub の push protection は発行元の分かる形（sk-… ghp_… AIza…）しか止められず、
# R2 の鍵は 32／64 文字のただの英数字なのですり抜ける。汎用パターンの検知は
# Organization + GitHub Team + Secret Protection（月 $23〜）でしか使えないので、自前で見る。

mode="${1:-staged}"

case "$mode" in
  staged) files=$(git diff --cached --name-only --diff-filter=ACMR) ; read_file() { git show ":$1" 2>/dev/null; } ;;
  tree)   files=$(git ls-files)                                     ; read_file() { cat "$1" 2>/dev/null; } ;;
  *) echo "使い方: sh scripts/scan_secrets.sh [staged|tree]" >&2; exit 2 ;;
esac

[ -z "$files" ] && exit 0

# 発行元が分かる形
known='(sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,}|AIza[0-9A-Za-z_-]{30,}|AKIA[0-9A-Z]{16}|rnd_[A-Za-z0-9]{16,}|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)'
# 代入の形で 16 文字以上の値が入っているもの（R2 の鍵のような「ただの英数字」はこれで捕まえる）
assign='(API_KEY|APIKEY|SECRET|SECRET_KEY|TOKEN|PASSWORD|PASSWD|ACCESS_KEY|PRIVATE_KEY)["'"'"' ]*[:=]["'"'"' ]*[A-Za-z0-9_/+-]{16,}'
# 見本・テンプレート・コードからの読み出しは鍵ではない
allow='example|sample|your-|your_|xxxx|placeholder|dummy|<[A-Za-z_]+>|\$\{|getenv|os\.environ|process\.env|secrets\.|inputs\.|vars\.|ENV\['

ng=""
tmp="${TMPDIR:-/tmp}/_scan_secrets_$$"

for f in $files; do
  # ---- 1. ファイル名 ----
  case "$f" in
    .env.example|*/.env.example) : ;;
    .env|.env.*|*/.env|*/.env.*) ng="$ng\n  $f（.env またはその控え）" ;;
    *.pem|*.p12|*.pfx|*.jks) ng="$ng\n  $f（証明書・鍵束）" ;;
    id_rsa|*/id_rsa|id_ed25519|*/id_ed25519) ng="$ng\n  $f（SSH の秘密鍵）" ;;
  esac

  # ---- 2. 中身 ----
  # 見本と、判定そのものを書いてあるファイルは中身を見ない（自分の正規表現に引っかかる）
  case "$f" in
    .env.example|*/.env.example|scripts/scan_secrets.sh|.githooks/*|.github/workflows/secrets.yml) continue ;;
  esac
  # data: URI の base64（ボードに埋め込んだフォントなど）は中身を見ない。15 万字のでたらめな英数字なので、
  # 大文字小文字を問わない照合だと「sk-…」「AKIA…」のような形にたまたま当たる（2026-09-24 に当たった）
  read_file "$f" | head -c 2000000 | sed -E 's#;base64,[A-Za-z0-9+/=]+#;base64,#g' > "$tmp" 2>/dev/null || continue
  grep -qI . "$tmp" 2>/dev/null || continue   # テキストでないものは見ない

  hit=$(grep -nEi "$known" "$tmp" 2>/dev/null | cut -d: -f1 | head -3 | tr '\n' ',' | sed 's/,$//')
  [ -n "$hit" ] && ng="$ng\n  $f（発行元の分かる鍵の形）… $hit 行目"

  hit=$(grep -nE "$assign" "$tmp" 2>/dev/null | grep -viE "$allow" \
        | sed -E 's/^([0-9]+):.*(API_KEY|APIKEY|SECRET_KEY|SECRET|TOKEN|PASSWORD|PASSWD|ACCESS_KEY|PRIVATE_KEY).*/\1:\2/' \
        | head -3 | tr '\n' ',' | sed 's/,$//')
  [ -n "$hit" ] && ng="$ng\n  $f（値の入った鍵らしい代入）… $hit（行番号:変数名）"
done
rm -f "$tmp"

[ -z "$ng" ] && exit 0

printf '\n\033[31m✖ 鍵を含むかもしれないものが見つかりました:\033[0m'
printf "$ng\n"
cat <<'MSG'

どうするか:
  - 鍵なら: リポジトリの外に出して、その鍵を失効させる（履歴は書き換えない。
    force-push は clone を壊すうえ、GitHub は GC 前の blob を残す）
  - 見本なら: 値を消して .env.example に書く
  - 誤検知なら: コミット時は git commit --no-verify。CI なら scripts/scan_secrets.sh の allow に足す

経緯は docs/gotchas.md の「鍵の入った .env の控えを公開リポジトリに入れてしまった」。
MSG
exit 1
