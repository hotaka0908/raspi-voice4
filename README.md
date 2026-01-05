# AI Necklace Gemini Live

Raspberry Pi 5 + Google Gemini Live API + Cloud Functions を使用したリアルタイム音声AIアシスタント

## 概要

Google Gemini Live APIを使用した低レイテンシのリアルタイム双方向音声対話システムです。raspi-voice3 (OpenAI Realtime API版) をベースに、Gemini Live APIに移行しました。

## Google Cloud 利用サービス

| カテゴリ | サービス | 用途 |
|---------|---------|------|
| **コンピューティング** | Cloud Functions | ライフログ写真のAI自動分析 |
| **AI/ML** | Gemini API (Live) | リアルタイム音声対話 |
| **AI/ML** | Gemini API (Vision) | 画像認識・分析 |

## 主な機能

- **リアルタイム音声対話** - Gemini Live APIによる低レイテンシ双方向音声
- **Gmail連携** - メール確認・返信・送信
- **アラーム機能** - 時刻指定で音声通知
- **カメラ機能** - Gemini Visionで画像認識
- **写真付きメール送信**
- **音声メッセージ** - Firebase経由でスマホとやり取り
- **ライフログ** - 定期的な自動撮影 + Cloud FunctionsでAI自動分析

## 必要要件

### ハードウェア

- Raspberry Pi 5
- USBマイク
- USBスピーカー
- GPIO接続プッシュボタン（GPIO 5）
- Raspberry Pi Camera Module（オプション）

### ソフトウェア

- Python 3.9以上
- Google Gemini API キー
- Gmail API 認証情報（オプション）
- Firebase プロジェクト（オプション）

## セットアップ

### 1. リポジトリをクローン

```bash
cd ~
git clone https://github.com/yourusername/raspi-voice4.git
cd raspi-voice4
```

### 2. 仮想環境を作成

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. 依存関係をインストール

```bash
pip install -r requirements.txt
```

### 4. 環境変数を設定

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

### 5. Gmail認証（オプション）

Gmail機能を使用する場合は、Google Cloud Consoleで認証情報を取得：

1. [Google Cloud Console](https://console.cloud.google.com/)でプロジェクトを作成
2. Gmail APIを有効化
3. OAuth 2.0クライアントIDを作成
4. 認証情報をダウンロードして配置：

```bash
cp ~/Downloads/credentials.json ~/.ai-necklace/credentials.json
```

初回起動時にブラウザでOAuth認証が必要です。

## 使用方法

### 直接実行

```bash
source venv/bin/activate
python ai_necklace_gemini.py
```

### systemdサービスとして実行

```bash
# サービスファイルをコピー
sudo cp ai-necklace-gemini.service /etc/systemd/system/

# サービスを有効化・起動
sudo systemctl daemon-reload
sudo systemctl enable ai-necklace-gemini
sudo systemctl start ai-necklace-gemini

# ログを確認
sudo journalctl -u ai-necklace-gemini -f
```

## 音声コマンド例

- 「メールを確認して」
- 「1番目のメールを読んで」
- 「写真を撮って」「何が見える？」
- 「7時にアラームをセットして」
- 「スマホにメッセージを送って」
- 「ライフログ開始」「ライフログ停止」

## 利用可能なツール（14種類）

| ツール名 | 説明 |
|---------|------|
| gmail_list | メール一覧取得 |
| gmail_read | メール本文読み取り |
| gmail_send | 新規メール送信 |
| gmail_reply | メール返信 |
| alarm_set | アラーム設定 |
| alarm_list | アラーム一覧取得 |
| alarm_delete | アラーム削除 |
| camera_capture | カメラで撮影して画像を説明 |
| gmail_send_photo | 写真を撮影してメール送信 |
| voice_send | スマホに音声メッセージを送信 |
| voice_send_photo | 写真を撮影してスマホに送信 |
| lifelog_start | ライフログ撮影を開始 |
| lifelog_stop | ライフログ撮影を停止 |
| lifelog_status | ライフログのステータス確認 |

## 技術仕様

### オーディオ設定

| 項目 | 値 |
|------|-----|
| マイク入力 | 44.1kHz, 16bit, モノラル |
| Gemini API送信 | 16kHz, 16bit PCM |
| Gemini API受信 | 24kHz, 16bit PCM |
| スピーカー出力 | 48kHz, 16bit, モノラル |

### Gemini Live API

- モデル: `gemini-2.5-flash-native-audio-preview-12-2025`
- 音声: Kore（日本語対応）
- セッション時間: 最大15分（音声のみ）

## raspi-voice3（OpenAI版）との違い

| 項目 | raspi-voice3 | raspi-voice4 |
|------|-------------|-------------|
| API | OpenAI Realtime API | Gemini Live API |
| 音声モデル | gpt-4o-realtime | gemini-2.5-flash-native-audio |
| Vision | GPT-4o Vision | Gemini Vision |
| 入力サンプルレート | 24kHz | 16kHz |
| 文字起こし | Whisper-1 | （未実装） |

## ディレクトリ構成

```
raspi-voice4/
├── ai_necklace_gemini.py       # メインアプリケーション
├── firebase_voice.py           # Firebase連携モジュール
├── requirements.txt            # Python依存関係
├── ai-necklace-gemini.service  # systemdサービス
├── firebase.json               # Firebase設定
├── .firebaserc                 # Firebaseプロジェクト設定
├── README.md                   # このファイル
├── functions/                  # Cloud Functions
│   ├── index.js               # 関数定義
│   └── package.json           # Node.js依存関係
└── docs/                       # スマホ用PWA
    ├── index.html
    ├── manifest.json
    └── firebase-config.js
```

## Cloud Functions セットアップ

### 1. Firebase CLIをインストール

```bash
npm install -g firebase-tools
firebase login
```

### 2. Firebaseプロジェクトを設定

```bash
# .firebasercを編集してプロジェクトIDを設定
# または以下のコマンドで設定
firebase use your-project-id
```

### 3. 環境変数を設定

```bash
# Google API キーを設定
firebase functions:secrets:set GOOGLE_API_KEY
```

### 4. デプロイ

```bash
cd functions
npm install
cd ..
firebase deploy --only functions
```

### Cloud Functions 機能

| 関数名 | トリガー | 説明 |
|--------|---------|------|
| `analyzeLifelogPhoto` | Storage (lifelogs/) | ライフログ写真をGemini Visionで自動分析 |
| `healthCheck` | HTTPS | ヘルスチェック用エンドポイント |
| `analyzePhotoManual` | HTTPS POST | 手動で写真を分析（デバッグ用） |

### ライフログ自動分析の流れ

1. Raspberry Piが定期的に写真を撮影
2. Firebase Storageの `lifelogs/{date}/{time}.jpg` にアップロード
3. Cloud Functions がトリガーされ、Gemini Vision APIで分析
4. 分析結果がRealtime Database `lifelogs/{date}/{time}` に保存
5. スマホアプリで分析結果を確認可能

## トラブルシューティング

### 接続エラー

```
接続エラー: ...
5秒後に再試行します...
```

- GEMINI_API_KEYが正しく設定されているか確認
- ネットワーク接続を確認

### マイクが見つからない

```
入力デバイスが見つかりません
```

- USBマイクが接続されているか確認
- `arecord -l` でデバイスを確認

### スピーカーから音が出ない

```
出力デバイスが見つかりません
```

- USBスピーカーが接続されているか確認
- `aplay -l` でデバイスを確認

## ライセンス

MIT License

## 関連リンク

- [Gemini Live API ドキュメント](https://ai.google.dev/gemini-api/docs/live)
- [raspi-voice3 (OpenAI版)](https://github.com/yourusername/raspi-voice3)
