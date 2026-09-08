# Danbooru Tag DB Updater for Forge Neo + Tag Autocomplete

`PYU224/tagdb-updater` が毎週生成している最新の Danbooru タグDBを、Forge Neo / `a1111-sd-webui-tagcomplete` に反映する個人用拡張です。

## v1.1 の変更点

### 1. `bandage_on_hair` など空白入りタグの補完を修正

`PYU224/tagdb-updater` は日本語表示をしやすくするため、生成CSVではDanbooruのアンダースコアを空白へ変換します。

一方、`a1111-sd-webui-tagcomplete` が読む4列CSVは canonical なアンダースコア形式を前提としています。そのため本拡張はダウンロード直後に、英語タグ名とaliasだけを安全に次のように正規化します。

```text
bandage on hair  ->  bandage_on_hair
long hair        ->  long_hair
```

日本語訳そのものは変更しません。

`danbooru.csv` と `danbooru-ja.csv` のタグ名・alias、および `danbooru-jp.csv` の英語キーを対象にしています。

### 2. 日本語入力によるタグ補完を自動設定

Tag Autocomplete には翻訳ファイルを使って翻訳語から検索する機能があります。翻訳ファイルは `<English tag/alias>,<Translation>` の2列CSVで、`Search by translation` を有効にすると日本語から検索できます。

本拡張ではデフォルトで、既存の設定が未設定の場合だけ次を自動設定します。

```text
Tag filename:          danbooru.csv
Translation filename:  danbooru-jp.csv
Search by translation: ON
```

すでにユーザーが別のTag/Translation fileを選んでいる場合、それを上書きしません。

## 更新の仕組み

- 起動時にGitHub上の `meta.json` を確認
- デフォルトでは7日に1回だけ確認
- 新しいスナップショットがあれば3ファイルを取得
- Tag Autocomplete互換形式へ正規化
- 一時ファイル経由で原子的に差し替え
- 失敗した場合は旧DBを維持

対象ファイル:

- `danbooru.csv` — Tag Autocomplete のメインタグDB
- `danbooru-jp.csv` — 日本語検索用翻訳ファイル
- `danbooru-ja.csv` — 日本語付き5列DB（保管用）

## 初回設定

1. このリポジトリをForge Neoの `extensions` に置く
2. Forge Neoを起動
3. Tag Autocompleteの設定で、通常は次を確認

```text
Tag filename:          danbooru.csv
Translation filename:  danbooru-jp.csv
Search by translation: ON
```

v1.1ではこの設定を拡張側から自動設定できます。

4. 一度Forge Neoを再起動

## 日本語入力の例

たとえば翻訳DBに

```text
long_hair,ロングヘア
```

が存在し、`Search by translation` がONなら、プロンプト欄で

```text
ロング
```

と入力して候補を検索できます。

翻訳が存在するタグだけが日本語検索の対象です。

## 注意

- Tag Autocomplete本体のコードは変更しません。
- 更新後にTag Autocompleteがすでに旧DBを読み込んでいる場合があるため、Forge Neoの再起動を推奨します。
- ネットワーク障害やCSV破損時は既存DBを保持します。
- 日本語翻訳の内容は `PYU224/tagdb-updater` の生成物に依存します。翻訳には機械翻訳由来のものも含まれます。
