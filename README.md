# AI Necklace - ウェアラブル音声AIアシスタント

Raspberry Pi 5 + Google Gemini Live API + Cloud Functions を使用したネックレス型リアルタイム音声AIアシスタント

## 概要

**AI Necklace**は、常に身につけられるウェアラブル音声AIアシスタントです。Google Gemini Live APIによる低レイテンシのリアルタイム音声対話と、Cloud Functionsによるサーバーレス処理を組み合わせ、ハンズフリーで日常のタスクをこなせます。

### 解決したい課題

- 料理中や運転中など、手が離せないシーンでのメール確認・返信
- ライフログを自動で記録し、後から振り返る
- 家族やチームとの音声メッセージによるコミュニケーション

### デモ動画

https://youtu.be/s2f3xGuAJEs

## Google Cloud 利用サービス

| カテゴリ | サービス | 用途 |
|---------|---------|------|
| **AI/ML** | Gemini Live API | リアルタイム双方向音声対話 |
| **AI/ML** | Gemini Vision API | 画像認識・ライフログ分析 |
| **コンピューティング** | Cloud Functions | ライフログ写真のAI自動分析 |
| **データベース** | Firebase Realtime Database | メッセージ・メタデータ管理 |
| **ストレージ** | Firebase Cloud Storage | 音声・写真・ライフログ保存 |
| **ホスティング** | Firebase Hosting | スマホ用PWA配信 |

## システムアーキテクチャ

```
┌──────────────────┐          WebSocket           ┌──────────────────────┐
│                  │  ◄────────────────────►     │                      │
│  Raspberry Pi 5  │     Gemini Live API         │   Google Cloud       │
│                  │     (リアルタイム音声)        │                      │
│  ┌────────────┐  │                              │  ┌────────────────┐  │
│  │ マイク     │  │         REST API            │  │ Gemini API     │  │
│  │ スピーカー │  │  ─────────────────►         │  │ (Vision)       │  │
│  │ カメラ     │  │     画像認識・STT            │  └────────────────┘  │
│  │ GPIOボタン │  │                              │                      │
│  └────────────┘  │         REST API            │  ┌────────────────┐  │
│                  │  ─────────────────►         │  │ Gmail API      │  │
└──────────────────┘     メール操作               │  └────────────────┘  │
         │                                        └──────────────────────┘
         │ Firebase REST API
         ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                           Firebase                                       │
│                                                                          │
│  ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────────┐    │
│  │ Cloud Storage   │   │ Realtime DB     │   │ Hosting             │    │
│  │ - lifelogs/     │   │ - messages/     │   │ - スマホ用PWA       │    │
│  │ - audio/        │   │ - lifelogs/     │   │                     │    │
│  └────────┬────────┘   └─────────────────┘   └─────────────────────┘    │
│           │ onObjectFinalized                                            │
│           ▼                                                              │
│  ┌─────────────────────────────────────────┐                            │
│  │ Cloud Functions (Node.js 20)            │                            │
│  │ analyzeLifelogPhoto() → Gemini Vision   │                            │
│  └─────────────────────────────────────────┘                            │
└──────────────────────────────────────────────────────────────────────────┘
         ▲
         │ Firebase SDK
┌──────────────────┐
│ スマホ (PWA)      │
│ - 音声メッセージ  │
│ - ライフログ確認  │
└──────────────────┘
```

## 主な機能

| 機能 | 説明 | Google Cloudサービス |
|------|------|---------------------|
| リアルタイム音声対話 | 話しかけると即座に応答、割り込み対応 | Gemini Live API |
| Gmail連携 | メール確認・返信・送信を音声で操作 | Gmail API |
| カメラ | 撮影して「何が見える？」と質問 | Gemini Vision API |
| ライフログ | 1分間隔で自動撮影、AI分析 | Cloud Functions + Gemini Vision |
| 音声メッセージ | スマホと音声・写真をやり取り | Firebase Storage + Realtime DB |
| アラーム | 時刻指定で音声通知 | ローカル処理 |

## 必要なもの

### ハードウェア

| パーツ | 用途 |
|-------|------|
| Raspberry Pi 5 | メイン処理 |
| USBマイク | 音声入力 |
| USBスピーカー | 音声出力 |
| Raspberry Pi Camera | 画像撮影（オプション） |
| GPIOボタン (GPIO 5) | Push-to-Talk |

### ソフトウェア・API

- Python 3.9以上
- Google Gemini API キー
- Gmail API 認証情報（オプション）
- Firebase プロジェクト（オプション）

## セットアップ

### 1. リポジトリをクローン

```bash
git clone https://github.com/yourusername/raspi-voice4.git
cd raspi-voice4
```

### 2. Python環境を構築

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. 環境変数を設定

```bash
mkdir -p ~/.ai-necklace
cat > ~/.ai-necklace/.env << 'EOF'
GEMINI_API_KEY=your-gemini-api-key

# Firebase（オプション）
FIREBASE_API_KEY=your-firebase-api-key
FIREBASE_AUTH_DOMAIN=your-project.firebaseapp.com
FIREBASE_DATABASE_URL=https://your-project.firebaseio.com
FIREBASE_PROJECT_ID=your-project-id
FIREBASE_STORAGE_BUCKET=your-project.appspot.com
EOF
```

### 4. 実行

```bash
python ai_necklace_gemini.py
```

### 5. systemdサービスとして実行（オプション）

```bash
sudo cp ai-necklace-gemini.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ai-necklace-gemini
sudo systemctl start ai-necklace-gemini

# ログ確認
sudo journalctl -u ai-necklace-gemini -f
```

## Cloud Functions セットアップ

ライフログ自動分析を有効にするには、Cloud Functionsをデプロイします。

```bash
# Firebase CLI インストール
npm install -g firebase-tools
firebase login

# プロジェクト設定
firebase use your-project-id

# シークレット設定
firebase functions:secrets:set GOOGLE_API_KEY

# デプロイ
cd functions && npm install && cd ..
firebase deploy --only functions
```

### Cloud Functions 機能

| 関数名 | トリガー | 説明 |
|--------|---------|------|
| `analyzeLifelogPhoto` | Storage (lifelogs/) | Gemini Visionで自動分析 |
| `healthCheck` | HTTPS | ヘルスチェック |
| `analyzePhotoManual` | HTTPS POST | 手動分析（デバッグ用） |

## 使い方

ボタンを押しながら話しかけ、離すと応答が返ってきます。

### 音声コマンド例

```
「メールを確認して」       → 未読メール一覧を読み上げ
「1番目のメールを読んで」  → メール本文を読み上げ
「返信して、了解しました」 → メールに返信
「写真を撮って」          → カメラで撮影して説明
「7時にアラームをセット」  → アラーム設定
「スマホにメッセージ送って」→ 音声メッセージ送信
「ライフログ開始」        → 1分間隔で自動撮影開始
「今日何枚撮った？」       → ライフログステータス確認
```

## ツール一覧（14種類）

| カテゴリ | ツール | 説明 |
|---------|--------|------|
| Gmail | `gmail_list` | メール一覧取得 |
| Gmail | `gmail_read` | メール本文読み取り |
| Gmail | `gmail_send` | 新規メール送信 |
| Gmail | `gmail_reply` | メール返信 |
| アラーム | `alarm_set` | アラーム設定 |
| アラーム | `alarm_list` | アラーム一覧取得 |
| アラーム | `alarm_delete` | アラーム削除 |
| カメラ | `camera_capture` | 撮影して説明 |
| カメラ | `gmail_send_photo` | 写真付きメール送信 |
| 音声 | `voice_send` | 音声メッセージ送信 |
| 音声 | `voice_send_photo` | 写真をスマホに送信 |
| ライフログ | `lifelog_start` | ライフログ開始 |
| ライフログ | `lifelog_stop` | ライフログ停止 |
| ライフログ | `lifelog_status` | ステータス確認 |

## 技術仕様

### Gemini Live API

| 項目 | 値 |
|------|-----|
| モデル | `gemini-2.5-flash-native-audio-preview-12-2025` |
| 音声 | Kore（日本語対応） |
| セッション時間 | 最大15分 |

### オーディオ設定

| 項目 | 値 |
|------|-----|
| マイク入力 | 48kHz, 16bit, モノラル |
| Gemini API送信 | 16kHz, 16bit PCM |
| Gemini API受信 | 24kHz, 16bit PCM |
| スピーカー出力 | 48kHz, 16bit, モノラル |

## ディレクトリ構成

```
raspi-voice4/
├── ai_necklace_gemini.py       # メインアプリケーション
├── firebase_voice.py           # Firebase連携モジュール
├── requirements.txt            # Python依存関係
├── ai-necklace-gemini.service  # systemdサービス
├── firebase.json               # Firebase設定
├── .firebaserc                 # Firebaseプロジェクト設定
├── functions/                  # Cloud Functions
│   ├── index.js               # 関数定義
│   └── package.json           # Node.js依存関係
└── docs/                       # スマホ用PWA
    ├── index.html
    ├── manifest.json
    └── firebase-config.js
```

## Gmail認証（オプション）

Gmail機能を使用する場合：

1. [Google Cloud Console](https://console.cloud.google.com/)でプロジェクト作成
2. Gmail APIを有効化
3. OAuth 2.0クライアントIDを作成（デスクトップアプリ）
4. 認証情報をダウンロード

```bash
cp ~/Downloads/credentials.json ~/.ai-necklace/credentials.json
```

初回起動時にブラウザでOAuth認証が必要です。

## トラブルシューティング

### 接続エラー

```
接続エラー: ...
5秒後に再試行します...
```

- `GEMINI_API_KEY`が正しく設定されているか確認
- ネットワーク接続を確認

### マイクが見つからない

```bash
arecord -l  # デバイス一覧を確認
```

### スピーカーから音が出ない

```bash
aplay -l    # デバイス一覧を確認
```

## ライセンス

MIT License

## デプロイ済みURL

- **Web版 AI Chat**: https://raspi-111.web.app/ai-chat.html
- **Voice Messenger**: https://raspi-111.web.app/

## リンク

- [Gemini Live API ドキュメント](https://ai.google.dev/gemini-api/docs/live)
- [Firebase ドキュメント](https://firebase.google.com/docs)
- [Cloud Functions ドキュメント](https://cloud.google.com/functions/docs)
