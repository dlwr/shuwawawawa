# シュワワワワ

日本の手話で発信している YouTube チャンネルの新着まとめ。毎日 GitHub Actions で YouTube Data API から各チャンネルの動画を取得して静的 HTML を生成し、GitHub Pages で配信する。

チャンネルの追加・削除は `channels.toml` を編集して PR を出す。

```bash
python -m unittest && YOUTUBE_API_KEY=... python build.py
```
