# AI Necklace Gemini Live

Raspberry Pi 5 + Google Gemini Live API を使用したリアルタイム音声AIアシスタント

## 機能

- **リアルタイム音声対話** - Gemini Live APIによる低レイテンシ双方向音声
- **Gmail連携** - メール確認・返信・送信
- **アラーム** - 時刻指定で音声通知
- **カメラ** - Gemini Visionで画像認識・写真送信
- **音声メッセージ** - Firebase経由でスマホとやり取り
- **ライフログ** - 1分間隔で自動撮影、Cloud FunctionsでAI分析

## 必要なもの

- Raspberry Pi 5
- USBマイク・スピーカー
- GPIOプッシュボタン (GPIO 5)
- カメラモジュール（オプション）
- Google Gemini API キー

## セットアップ

```bash
# クローン
git clone https://github.com/yourusername/raspi-voice4.git
cd raspi-voice4

# 仮想環境
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 環境変数
mkdir -p ~/.ai-necklace
cat > ~/.ai-necklace/.env << 'EOF'
GEMINI_API_KEY=your-gemini-api-key
EOF

# 実行
python ai_necklace_gemini.py
```

### systemdサービス

```bash
sudo cp ai-necklace-gemini.service /etc/systemd/system/
sudo systemctl enable --now ai-necklace-gemini
sudo journalctl -u ai-necklace-gemini -f
```

## 使い方

ボタンを押しながら話しかけ、離すと応答が返ってきます。

**音声コマンド例:**
- 「メールを確認して」
- 「写真を撮って」
- 「7時にアラームをセットして」
- 「スマホにメッセージを送って」
- 「ライフログ開始」

## ツール一覧

| カテゴリ | ツール |
|---------|--------|
| Gmail | gmail_list, gmail_read, gmail_send, gmail_reply |
| アラーム | alarm_set, alarm_list, alarm_delete |
| カメラ | camera_capture, gmail_send_photo |
| 音声メッセージ | voice_send, voice_send_photo |
| ライフログ | lifelog_start, lifelog_stop, lifelog_status |

## 技術仕様

| 項目 | 値 |
|------|-----|
| モデル | gemini-2.5-flash-native-audio-preview-12-2025 |
| 音声 | Kore（日本語対応） |
| マイク | 48kHz → 16kHz (リサンプリング) |
| スピーカー | 24kHz → 48kHz (リサンプリング) |
| VAD | 手動（プッシュトゥトーク） |

## ファイル構成

```
├── ai_necklace_gemini.py   # メインアプリ
├── firebase_voice.py       # Firebase連携
├── requirements.txt
├── ai-necklace-gemini.service
├── functions/              # Cloud Functions (ライフログ分析)
└── docs/                   # スマホ用PWA
```

## オプション機能

### Gmail

Google Cloud ConsoleでOAuth認証情報を取得し、`~/.ai-necklace/credentials.json` に配置。

### Firebase（音声メッセージ・ライフログ）

```bash
# .envに追加
FIREBASE_API_KEY=...
FIREBASE_DATABASE_URL=...
FIREBASE_STORAGE_BUCKET=...
```

### Cloud Functions

```bash
npm install -g firebase-tools
firebase login
firebase functions:secrets:set GOOGLE_API_KEY
firebase deploy --only functions
```

## ライセンス

MIT License
