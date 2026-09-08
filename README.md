# Danbooru Tag DB Updater for Forge Neo + Tag Autocomplete

`PYU224/tagdb-updater` が毎週生成している最新の Danbooru タグDBを、
AUTOMATIC1111 系 WebUI / Forge Neo の `a1111-sd-webui-tagcomplete` 用 `tags` フォルダへ自動反映する個人用拡張です。

## 主な機能

- Forge Neo 起動時に更新チェック
- デフォルトでは 7 日に 1 回だけオンラインチェック
- 更新があれば以下を安全にダウンロードし、テンポラリファイル経由で置換
  - `danbooru.csv` — Tag Autocomplete の Tag Source 用
  - `danbooru-jp.csv` — Tag Autocomplete の Translation filename 用
  - `danbooru-ja.csv` — 日本語を含む5列の全部入りDB（保管用）
- `meta.json` の更新日時を使って不要なダウンロードを回避
- タグDBが壊れている/小さすぎる場合は既存ファイルを維持
- WebUI に手動更新用タブを追加
- Tag Autocomplete のフォルダを自動検出。必要ならUIからパスを指定可能

## 初回設定

1. このリポジトリを Forge Neo の `extensions` に clone
2. Forge Neo を起動
3. `Danbooru Tag DB Updater` タブを開く
4. Tag Autocomplete のディレクトリが正しく検出されているか確認
5. Tag Autocomplete の設定で、次を一度だけ設定

   - `Tag filename`: `danbooru.csv`
   - `Translation filename`: `danbooru-jp.csv`

更新後のCSVは次回WebUI起動時から利用されます。実行中に手動更新した場合は、安全のため Forge Neo の再起動を推奨します。

## 推奨フォルダ構成

```text
Forge Neo/
└─ extensions/
   ├─ a1111-danbooru-tagdb-updater/
   └─ a1111-sd-webui-tagcomplete/
      └─ tags/
         ├─ danbooru.csv
         ├─ danbooru-jp.csv
         └─ danbooru-ja.csv
```

Tag Autocomplete のフォルダ名が別名でも、自動検出します。

## 自動更新の仕組み

起動時に GitHub 上の `meta.json` を確認し、最後に成功したチェックから設定日数が経過している場合だけ問い合わせます。
デフォルトは 7 日です。更新日時が変わっていれば CSV を取得します。

この拡張自体は Danbooru に直接アクセスせず、公開済みの `PYU224/tagdb-updater` の生成物を利用します。

## 注意

- Tag Autocomplete の本体コードは変更しません。
- ネットワーク障害時は既存DBを保持します。
- 更新後に Tag Autocomplete が読み込んでいるデータを確実に切り替えるため、手動更新後は Forge Neo の再起動を推奨します。
- この拡張は個人利用を想定しています。
