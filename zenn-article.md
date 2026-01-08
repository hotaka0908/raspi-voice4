---
title: "AI Necklace - Gemini Live APIで実現するウェアラブル音声AIアシスタント"
emoji: "🎙️"
type: "idea"
topics: ["gch4", "gemini", "raspberrypi", "cloudfunctions", "firebase"]
published: false
---

## プロジェクト概要

**AI Necklace**は、Raspberry Pi 5とGoogle Gemini Live APIを組み合わせた、ネックレス型のウェアラブル音声AIアシスタントです。

常時身につけることで、ハンズフリーで以下のことが実現できます：

- **リアルタイム音声対話** - 話しかけるだけでAIと自然な会話
- **Gmail連携** - メールの確認・返信・送信を音声で操作
- **ライフログ自動撮影** - 定期的に写真を撮影し、Cloud FunctionsでAI自動分析
- **スマホ連携** - Firebase経由で音声メッセージや写真をやり取り

### 解決したい課題

スマートフォンを取り出す手間なく、日常のタスクを音声だけで完結させたい。

- 料理中や運転中など、手が離せないシーンでのメール確認・返信
- ライフログを自動で記録し、後から「今日何してたっけ？」を振り返る
- 家族やチームメンバーとの音声メッセージによるコミュニケーション

### デモ動画

https://youtu.be/s2f3xGuAJEs

---

## システムアーキテクチャ

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        AI Necklace システム構成                          │
└─────────────────────────────────────────────────────────────────────────┘

┌──────────────────┐          WebSocket           ┌──────────────────────┐
│                  │  ◄──────────────────────►   │                      │
│  Raspberry Pi 5  │     Gemini Live API         │   Google Cloud       │
│                  │     (リアルタイム音声)         │                      │
│  ┌────────────┐  │                              │  ┌────────────────┐  │
│  │ マイク     │  │         REST API            │  │ Gemini API     │  │
│  │ スピーカー │  │  ────────────────────►      │  │ (Vision)       │  │
│  │ カメラ     │  │     画像認識・STT            │  └────────────────┘  │
│  │ GPIOボタン │  │                              │                      │
│  └────────────┘  │         REST API            │  ┌────────────────┐  │
│                  │  ────────────────────►      │  │ Gmail API      │  │
│  Python 3.11     │     メール操作               │  └────────────────┘  │
│  google-genai    │                              │                      │
└──────────────────┘                              └──────────────────────┘
         │                                                   │
         │ Firebase REST API                                 │
         │ (写真・音声アップロード)                              │
         ▼                                                   │
┌──────────────────────────────────────────────────────────────────────────┐
│                           Firebase                                       │
│                                                                          │
│  ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────────┐    │
│  │ Cloud Storage   │   │ Realtime DB     │   │ Hosting             │    │
│  │                 │   │                 │   │                     │    │
│  │ - lifelogs/     │   │ - messages/     │   │ - スマホ用PWA       │    │
│  │ - audio/        │   │ - lifelogs/     │   │                     │    │
│  │ - photos/       │   │                 │   │                     │    │
│  └────────┬────────┘   └─────────────────┘   └─────────────────────┘    │
│           │                                                              │
│           │ onObjectFinalized トリガー                                   │
│           ▼                                                              │
│  ┌─────────────────────────────────────────┐                            │
│  │ Cloud Functions (Node.js 20)            │                            │
│  │                                         │                            │
│  │ analyzeLifelogPhoto()                   │───► Gemini Vision API      │
│  │   - 画像をダウンロード                    │     で画像分析             │
│  │   - Gemini Visionで分析                  │                            │
│  │   - 結果をRealtime DBに保存              │                            │
│  └─────────────────────────────────────────┘                            │
└──────────────────────────────────────────────────────────────────────────┘
         ▲
         │ Firebase SDK (Web)
         │
┌──────────────────┐
│ スマホ (PWA)      │
│                  │
│ - 音声メッセージ  │
│   送受信          │
│ - 写真閲覧       │
│ - ライフログ確認  │
└──────────────────┘
```

---

## 使用しているGoogle Cloudサービス

### 1. Gemini Live API（音声対話）

リアルタイム双方向音声対話の中核。WebSocket経由で低レイテンシな音声通信を実現。

```python
from google import genai

client = genai.Client(api_key=api_key)

async with client.aio.live.connect(
    model="gemini-2.5-flash-native-audio-preview-12-2025",
    config=types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")
            )
        )
    )
) as session:
    # リアルタイム音声送受信
    ...
```

**特徴：**
- 日本語対応の音声（Kore）
- Function Calling対応（14種類のツールを実装）
- セッション最大15分

### 2. Gemini Vision API（画像認識）

カメラで撮影した画像をAIが解析。ライフログの自動分析にも使用。

```python
response = genai.models.generate_content(
    model="gemini-2.0-flash",
    contents=[
        "この画像を説明してください",
        {"inline_data": {"mime_type": "image/jpeg", "data": base64_image}}
    ]
)
```

### 3. Cloud Functions（サーバーレス処理）

Firebase Storageへの画像アップロードをトリガーに、自動でGemini Visionによる分析を実行。

```javascript
exports.analyzeLifelogPhoto = onObjectFinalized(
  { region: "asia-northeast1", secrets: [googleApiKey] },
  async (event) => {
    // 1. Storage から画像をダウンロード
    const [imageBuffer] = await file.download();

    // 2. Gemini Vision APIで分析
    const result = await model.generateContent([prompt, imageData]);

    // 3. 結果をRealtime Databaseに保存
    await db.ref(`lifelogs/${date}/${time}`).update({ analysis });
  }
);
```

### 4. Firebase（データ基盤）

| サービス | 用途 |
|---------|------|
| Cloud Storage | 音声ファイル、写真、ライフログ画像の保存 |
| Realtime Database | メッセージ、ライフログメタデータの管理 |
| Hosting | スマホ用PWAの配信 |

### 5. Gmail API

音声コマンドでメールを操作。

- 「メールを確認して」→ 未読メール一覧を読み上げ
- 「1番目のメールを読んで」→ 本文を読み上げ
- 「返信して」→ 音声で返信内容を入力

---

## 主な機能

### リアルタイム音声対話

Gemini Live APIによる自然な会話体験。

- **低レイテンシ**: 話しかけると即座に応答
- **割り込み対応**: AIの発話中に話しかけると中断して聞き取り
- **文脈理解**: 会話の流れを理解した応答

### ライフログ自動撮影 + AI分析

1分間隔で自動撮影し、Cloud FunctionsでAI分析。

```
ユーザー: 「ライフログ開始」
AI: 「ライフログを開始しました」

# 1分ごとに自動撮影
# → Cloud Storage にアップロード
# → Cloud Functions がトリガー
# → Gemini Vision で分析
# → 結果: { location: "カフェ", activity: "PC作業", ... }

ユーザー: 「今日何枚撮った？」
AI: 「今日は42枚撮影しました」
```

### スマホ連携（PWA）

Firebase経由でRaspberry Piとスマホ間でメッセージをやり取り。

- 押しながら話す形式で音声メッセージを送信
- 写真の送受信
- ライフログの閲覧

---

## ハードウェア構成

| パーツ | 用途 |
|-------|------|
| Raspberry Pi 5 | メイン処理 |
| USBマイク | 音声入力 |
| USBスピーカー | 音声出力 |
| Raspberry Pi Camera | 画像撮影 |
| GPIOボタン (GPIO 5) | Push-to-Talk |

---

## 実装のポイント

### 1. リアルタイム音声の品質最適化

```python
# マイク入力: 48kHz → 16kHz にダウンサンプリング
# 3倍のオーバーサンプリングで高品質を維持
"input_sample_rate": 48000,   # マイク
"send_sample_rate": 16000,    # Gemini API

# スピーカー出力: 24kHz → 48kHz にアップサンプリング
"receive_sample_rate": 24000,  # Gemini API
"output_sample_rate": 48000,   # スピーカー
```

### 2. Function Callingによるツール統合

14種類のツールをGemini Live APIのFunction Callingで統合。

```python
tools = [
    {"name": "gmail_list", "description": "メール一覧を取得"},
    {"name": "gmail_read", "description": "メール本文を読む"},
    {"name": "camera_capture", "description": "カメラで撮影"},
    {"name": "lifelog_start", "description": "ライフログ開始"},
    # ... 他10種類
]
```

### 3. Cloud Functionsによる非同期処理

Raspberry Piのリソースを消費せず、クラウドでAI分析を実行。

```
Raspberry Pi (撮影・アップロードのみ)
     ↓
Cloud Storage (画像保存)
     ↓
Cloud Functions (AI分析) ← サーバーレスで自動スケール
     ↓
Realtime Database (結果保存)
```

---

## Web版デモ

ハードウェアがなくてもブラウザでAI Necklaceの音声対話機能を体験できます。

**Web版デモ**: https://raspi-111.web.app/ai-chat.html

1. Gemini APIキーを入力して「接続」
2. マイクボタンを押しながら話しかける
3. AIが音声で応答

## 今後の展望

- **マルチモーダル対応強化**: カメラ映像のリアルタイム認識
- **より小型化**: Raspberry Pi Zero 2 Wへの移植
- **バッテリー駆動**: モバイルバッテリーでの長時間動作
- **カスタムウェイクワード**: 「OK AI」などでの起動

---

## リンク

- **GitHub**: https://github.com/hotaka0908/raspi-voice4
- **Web版デモ**: https://raspi-111.web.app/ai-chat.html

---

## まとめ

AI Necklaceは、Google Cloudの各種サービスを組み合わせることで、身につけられるAIアシスタントを実現しました。

- **Gemini Live API** で自然な音声対話
- **Cloud Functions** でサーバーレスなAI分析
- **Firebase** でリアルタイムなデータ連携

スマートフォンを取り出す必要なく、声だけで日常のタスクをこなせる未来を目指しています。
