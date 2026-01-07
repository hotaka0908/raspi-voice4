#!/usr/bin/env python3
"""
AI Necklace Gemini Live - Raspberry Pi 5 リアルタイム音声AIアシスタント（Gemini版）

Google Gemini Live APIを使用したリアルタイム双方向音声対話システム。
Gmail、アラーム、カメラ、音声メッセージ機能を統合。

機能:
- リアルタイム音声対話（低レイテンシ）
- Gmail連携（メール確認・返信・送信）
- アラーム機能（時刻指定で音声通知）
- カメラ機能（Gemini Visionで画像認識）
- 写真付きメール送信
- 音声メッセージ（Firebase経由でスマホとやり取り）
"""

import os
import sys
import json
import base64
import asyncio
import threading
import signal
import time
import re
import subprocess
import io
import wave
import tempfile
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

import numpy as np
import pyaudio
try:
    import alsaaudio
    ALSA_AVAILABLE = True
except ImportError:
    ALSA_AVAILABLE = False
    print("警告: alsaaudioが見つかりません。PyAudioで出力します。")
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Gmail API
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GMAIL_AVAILABLE = True
except ImportError:
    GMAIL_AVAILABLE = False
    print("警告: Google APIライブラリが見つかりません。Gmail機能は無効です。")

# Firebase Voice Messenger
try:
    from firebase_voice import FirebaseVoiceMessenger
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    print("警告: firebase_voiceモジュールが見つかりません。音声メッセージ機能は無効です。")

# GPIOライブラリ
try:
    from gpiozero import Button
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("警告: gpiozeroが使用できません。ボタン操作は無効です。")

# systemdで実行時にprint出力をリアルタイムで表示するため
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# 環境変数の読み込み（~/.ai-necklace/.env から）
env_path = os.path.expanduser("~/.ai-necklace/.env")
load_dotenv(env_path)

# Gmail APIスコープ
GMAIL_SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.modify'
]

# 設定
CONFIG = {
    # Gemini Live API設定
    "model": "gemini-2.5-flash-native-audio-preview-12-2025",
    "voice": "Kore",  # Gemini voice options: Puck, Charon, Kore, Fenrir, Aoede

    # オーディオ設定 (Gemini Live API仕様)
    "send_sample_rate": 16000,    # Gemini入力: 16kHz
    "receive_sample_rate": 24000,  # Gemini出力: 24kHz
    "input_sample_rate": 48000,    # マイク入力: 48kHz（16kHzへの3倍ダウンサンプリングで高品質）
    "output_sample_rate": 48000,   # スピーカー出力: 48kHz
    "channels": 1,                 # モノラル（raspi-voice3と同じ）
    "chunk_size": 1024,

    # デバイス設定（PyAudioで自動検出）
    "input_device_index": None,
    "output_device_index": None,

    # GPIO設定
    "button_pin": 5,
    "use_button": True,

    # Gmail設定
    "gmail_credentials_path": os.path.expanduser("~/.ai-necklace/credentials.json"),
    "gmail_token_path": os.path.expanduser("~/.ai-necklace/token.json"),

    # アラーム設定
    "alarm_file_path": os.path.expanduser("~/.ai-necklace/alarms.json"),

    # ライフログ設定
    "lifelog_dir": os.path.expanduser("~/lifelog"),
    "lifelog_interval": 60,  # 1分（秒）

    # システムプロンプト
    "instructions": """あなたは親切なAIアシスタントです。
ユーザーの質問に簡潔に答えてください。
日本語で回答してください。
音声での会話なので、1-2文程度の短い応答を心がけてください。

利用可能なツール:
- gmail_list: メール一覧取得
- gmail_read: メール本文読み取り
- gmail_send: 新規メール送信
- gmail_reply: メール返信
- alarm_set: アラーム設定
- alarm_list: アラーム一覧取得
- alarm_delete: アラーム削除
- camera_capture: カメラで撮影して画像を説明
- gmail_send_photo: 写真を撮影してメール送信
- voice_send: スマホに音声メッセージを送信
- voice_send_photo: 写真を撮影してスマホに送信
- lifelog_start: ライフログ撮影を開始
- lifelog_stop: ライフログ撮影を停止
- lifelog_status: ライフログのステータス確認

ユーザーが「メールを確認」と言ったらgmail_listを使用。
ユーザーが「写真を撮って」「何が見える？」と言ったらcamera_captureを使用。
ユーザーが「アラームをセット」と言ったらalarm_setを使用。
ユーザーが「スマホにメッセージを送って」「ボイスメッセージを送りたい」「メッセージ送信」などと言ったら、必ずvoice_sendツールを呼び出してください。口頭で説明するだけではダメです。
ユーザーが「ライフログ開始」「ライフログを始めて」と言ったらlifelog_startを使用。
ユーザーが「ライフログ停止」「ライフログを止めて」と言ったらlifelog_stopを使用。
ユーザーが「今日何枚撮った？」「ライフログの状態」と言ったらlifelog_statusを使用。

ツールはユーザーが明示的に依頼した場合のみ使用してください。
挨拶や質問には普通に会話で応答してください。
""",
}

# グローバル変数
running = True
button = None
is_recording = False
gemini_client = None

# Gmail関連
gmail_service = None
last_email_list = []

# アラーム関連
alarms = []
alarm_next_id = 1

# Firebase関連
firebase_messenger = None
voice_message_mode = False  # 音声メッセージ録音モード
voice_message_mode_timestamp = None  # 音声メッセージモード開始時刻
VOICE_MESSAGE_MODE_TIMEOUT = 60  # 60秒でタイムアウト
voice_message_buffer = []   # 録音バッファ


def check_and_reset_voice_message_mode():
    """voice_message_modeのタイムアウトをチェックし、必要ならリセット"""
    global voice_message_mode, voice_message_mode_timestamp

    if voice_message_mode and voice_message_mode_timestamp:
        elapsed = time.time() - voice_message_mode_timestamp
        if elapsed > VOICE_MESSAGE_MODE_TIMEOUT:
            print(f"voice_message_mode タイムアウト ({elapsed:.1f}秒経過) - リセット")
            voice_message_mode = False
            voice_message_mode_timestamp = None
            return False  # タイムアウトでリセットされた
    return voice_message_mode


def reset_voice_message_mode():
    """voice_message_modeを強制リセット（再接続時などに使用）"""
    global voice_message_mode, voice_message_mode_timestamp

    if voice_message_mode:
        print("voice_message_mode を強制リセット")
    voice_message_mode = False
    voice_message_mode_timestamp = None

# ライフログ関連
lifelog_enabled = False
lifelog_thread = None
lifelog_photo_count = 0  # 今日の撮影枚数

# カメラ排他制御用ロック
camera_lock = threading.Lock()

# グローバルオーディオハンドラ（スマホからの音声再生用）
global_audio_handler = None


def signal_handler(sig, frame):
    """Ctrl+C で終了"""
    global running
    print("\n終了します...")
    running = False


# ==================== ユーティリティ ====================

def find_audio_device(p, device_type="input"):
    """オーディオデバイスを自動検出"""
    # 入力デバイス用の名前リスト（USB機器を優先、defaultは最後の手段）
    input_target_names = ["usbmic", "USB PnP Sound", "USB Audio", "USB PnP Audio"]
    # 出力デバイス用の名前リスト（UACDemo=USBスピーカーを優先）
    output_target_names = ["usbspk", "UACDemo", "USB Audio", "USB PnP Audio"]
    target_names = input_target_names if device_type == "input" else output_target_names

    # デバッグ: 全デバイスを表示
    print(f"=== オーディオデバイス一覧 ({device_type}) ===")
    for i in range(p.get_device_count()):
        info = p.get_device_info_by_index(i)
        name = info.get("name", "")
        in_ch = info.get("maxInputChannels", 0)
        out_ch = info.get("maxOutputChannels", 0)
        print(f"  [{i}] {name} (入力:{in_ch}ch, 出力:{out_ch}ch)")

    # USBデバイスを探す
    for i in range(p.get_device_count()):
        info = p.get_device_info_by_index(i)
        name = info.get("name", "")

        if device_type == "input" and info.get("maxInputChannels", 0) > 0:
            for target in target_names:
                if target in name:
                    print(f"入力デバイス検出: [{i}] {name}")
                    return i
        elif device_type == "output" and info.get("maxOutputChannels", 0) > 0:
            for target in target_names:
                if target in name:
                    print(f"出力デバイス検出: [{i}] {name}")
                    return i

    # フォールバック: 最初に見つかった適切なデバイスを使用
    print(f"USBデバイスが見つかりません。代替デバイスを探しています...")
    for i in range(p.get_device_count()):
        info = p.get_device_info_by_index(i)
        if device_type == "input" and info.get("maxInputChannels", 0) > 0:
            print(f"代替入力デバイス: [{i}] {info.get('name', '')}")
            return i
        elif device_type == "output" and info.get("maxOutputChannels", 0) > 0:
            print(f"代替出力デバイス: [{i}] {info.get('name', '')}")
            return i

    print(f"{device_type}デバイスが見つかりません")
    return None


def resample_audio(audio_data, from_rate, to_rate):
    """オーディオをリサンプリング（整数倍ダウンサンプリング対応）"""
    if from_rate == to_rate:
        return audio_data

    audio_array = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)

    # 整数倍ダウンサンプリングの場合は平均化（簡易ローパスフィルタ効果）
    ratio = from_rate / to_rate
    if ratio == int(ratio) and ratio > 1:
        # 例: 48kHz → 16kHz (3倍) の場合、3サンプルの平均を取る
        factor = int(ratio)
        # 端数を切り捨てて整数個のグループにする
        trim_length = (len(audio_array) // factor) * factor
        trimmed = audio_array[:trim_length]
        # グループごとに平均を計算
        resampled = trimmed.reshape(-1, factor).mean(axis=1)
    else:
        # 非整数倍の場合は線形補間
        original_length = len(audio_array)
        target_length = int(original_length * to_rate / from_rate)
        indices = np.linspace(0, original_length - 1, target_length)
        resampled = np.interp(indices, np.arange(original_length), audio_array)

    return resampled.astype(np.int16).tobytes()


def mono_to_stereo(audio_data):
    """モノラル音声をステレオに変換"""
    audio_array = np.frombuffer(audio_data, dtype=np.int16)
    # 左右チャンネルに同じ音声を設定
    stereo = np.column_stack((audio_array, audio_array))
    return stereo.astype(np.int16).tobytes()


# ==================== Gmail機能 ====================

def init_gmail():
    """Gmail API初期化"""
    global gmail_service

    if not GMAIL_AVAILABLE:
        print("Gmail: 無効（ライブラリなし）")
        return False

    creds = None
    token_path = CONFIG["gmail_token_path"]
    credentials_path = CONFIG["gmail_credentials_path"]

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, GMAIL_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(credentials_path):
                print(f"Gmail: 無効（認証情報なし: {credentials_path}）")
                return False
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, GMAIL_SCOPES)
            creds = flow.run_local_server(port=0)

        os.makedirs(os.path.dirname(token_path), exist_ok=True)
        with open(token_path, 'w') as token:
            token.write(creds.to_json())

    try:
        gmail_service = build('gmail', 'v1', credentials=creds)
        print("Gmail: 有効")
        return True
    except Exception as e:
        print(f"Gmail初期化エラー: {e}")
        return False


def gmail_list_func(query="is:unread", max_results=5):
    """メール一覧を取得"""
    global gmail_service, last_email_list

    if not gmail_service:
        return "Gmail機能が初期化されていません"

    try:
        results = gmail_service.users().messages().list(
            userId='me', q=query, maxResults=max_results
        ).execute()

        messages = results.get('messages', [])
        if not messages:
            return "該当するメールはありません"

        email_list = []
        last_email_list = []

        for i, msg in enumerate(messages, 1):
            msg_detail = gmail_service.users().messages().get(
                userId='me', id=msg['id'], format='metadata',
                metadataHeaders=['From', 'Subject', 'Date']
            ).execute()

            headers = {h['name']: h['value'] for h in msg_detail.get('payload', {}).get('headers', [])}
            from_header = headers.get('From', '不明')
            from_match = re.match(r'(.+?)\s*<', from_header)
            from_name = from_match.group(1).strip() if from_match else from_header.split('@')[0]

            email_info = {
                'id': msg['id'],
                'from': from_name,
                'from_email': from_header,
                'subject': headers.get('Subject', '(件名なし)'),
            }
            last_email_list.append(email_info)
            email_list.append(f"{i}. {from_name}さんから: {email_info['subject']}")

        return "メール一覧:\n" + "\n".join(email_list)

    except HttpError as e:
        return f"メール取得エラー: {e}"


def gmail_read_func(message_id):
    """メール本文を読み取り"""
    global gmail_service, last_email_list

    if not gmail_service:
        return "Gmail機能が初期化されていません"

    # 番号で指定された場合
    if isinstance(message_id, int) or (isinstance(message_id, str) and message_id.isdigit()):
        idx = int(message_id) - 1
        if 0 <= idx < len(last_email_list):
            message_id = last_email_list[idx]['id']
        else:
            return "指定されたメールが見つかりません"

    try:
        msg = gmail_service.users().messages().get(
            userId='me', id=message_id, format='full'
        ).execute()

        headers = {h['name']: h['value'] for h in msg.get('payload', {}).get('headers', [])}
        body = ""
        payload = msg.get('payload', {})

        if 'body' in payload and payload['body'].get('data'):
            body = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
        elif 'parts' in payload:
            for part in payload['parts']:
                if part.get('mimeType') == 'text/plain' and part.get('body', {}).get('data'):
                    body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                    break

        if len(body) > 500:
            body = body[:500] + "...(以下省略)"

        from_header = headers.get('From', '不明')
        from_match = re.match(r'(.+?)\s*<', from_header)
        from_name = from_match.group(1).strip() if from_match else from_header

        return f"送信者: {from_name}\n件名: {headers.get('Subject', '(件名なし)')}\n\n本文:\n{body}"

    except HttpError as e:
        return f"メール読み取りエラー: {e}"


def gmail_send_func(to, subject, body):
    """新規メール送信"""
    global gmail_service

    if not gmail_service:
        return "Gmail機能が初期化されていません"

    try:
        message = MIMEText(body)
        message['to'] = to
        message['subject'] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        gmail_service.users().messages().send(
            userId='me', body={'raw': raw}
        ).execute()

        return f"{to}にメールを送信しました"

    except HttpError as e:
        return f"メール送信エラー: {e}"


def gmail_reply_func(message_id, body, attach_photo=False):
    """メール返信"""
    global gmail_service, last_email_list

    if not gmail_service:
        return "Gmail機能が初期化されていません"

    # 番号で指定された場合
    to_email = None
    if isinstance(message_id, int) or (isinstance(message_id, str) and message_id.isdigit()):
        idx = int(message_id) - 1
        if 0 <= idx < len(last_email_list):
            actual_id = last_email_list[idx]['id']
            to_email = last_email_list[idx].get('from_email')
        else:
            return "指定されたメールが見つかりません"
    else:
        actual_id = message_id

    try:
        original = gmail_service.users().messages().get(
            userId='me', id=actual_id, format='metadata',
            metadataHeaders=['From', 'Subject', 'Message-ID', 'References', 'Reply-To']
        ).execute()

        headers = {h['name']: h['value'] for h in original.get('payload', {}).get('headers', [])}
        to_raw = to_email or headers.get('Reply-To') or headers.get('From', '')

        # メールアドレス抽出
        match = re.search(r'<([^>]+)>', to_raw)
        to = match.group(1) if match else to_raw.strip()

        subject = headers.get('Subject', '')
        if not subject.startswith('Re:'):
            subject = 'Re: ' + subject

        thread_id = original.get('threadId')

        message = MIMEText(body)
        message['to'] = to
        message['subject'] = subject

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        gmail_service.users().messages().send(
            userId='me', body={'raw': raw, 'threadId': thread_id}
        ).execute()

        to_name = to.split('@')[0]
        return f"{to_name}さんに返信を送信しました"

    except HttpError as e:
        return f"返信エラー: {e}"


# ==================== Firebase音声メッセージ機能 ====================

def init_firebase():
    """Firebase Voice Messengerを初期化"""
    global firebase_messenger

    if not FIREBASE_AVAILABLE:
        print("Firebase Voice Messenger: 無効（モジュールなし）")
        return False

    try:
        firebase_messenger = FirebaseVoiceMessenger(
            device_id="raspi",
            on_message_received=on_voice_message_received
        )
        firebase_messenger.start_listening(poll_interval=1.5)
        print("Firebase Voice Messenger: 有効")
        return True
    except Exception as e:
        print(f"Firebase初期化エラー: {e}")
        return False


def generate_shutter_sound():
    """シャッター音を生成"""
    try:
        sample_rate = 48000
        duration = 0.08  # 短いクリック音

        # クリック音（短いノイズ + 減衰）
        samples = int(sample_rate * duration)
        t = np.linspace(0, duration, samples, False)

        # ホワイトノイズ + 高周波クリック
        noise = np.random.uniform(-1, 1, samples)
        click = np.sin(2 * np.pi * 2000 * t)

        # 急速な減衰エンベロープ
        envelope = np.exp(-t * 50)

        # 合成
        sound = ((noise * 0.3 + click * 0.7) * envelope * 0.4 * 32767).astype(np.int16)

        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(sound.tobytes())

        return wav_buffer.getvalue()
    except Exception as e:
        print(f"シャッター音生成エラー: {e}")
        return None


def generate_notification_sound():
    """通知音を生成"""
    try:
        sample_rate = 48000
        duration1 = 0.15
        duration2 = 0.1

        t1 = np.linspace(0, duration1, int(sample_rate * duration1), False)
        tone1 = (np.sin(2 * np.pi * 880 * t1) * 0.3 * 32767).astype(np.int16)

        gap = np.zeros(int(sample_rate * 0.1), dtype=np.int16)

        t2 = np.linspace(0, duration2, int(sample_rate * duration2), False)
        tone2 = (np.sin(2 * np.pi * 1320 * t2) * 0.2 * 32767).astype(np.int16)

        sound = np.concatenate([tone1, gap, tone2])

        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(sound.tobytes())

        return wav_buffer.getvalue()
    except Exception as e:
        print(f"通知音生成エラー: {e}")
        return None


def generate_startup_sound():
    """起動完了音を生成（3音の上昇メロディ）"""
    try:
        sample_rate = 48000

        # 3音の上昇メロディ（ド・ミ・ソ）
        frequencies = [523, 659, 784]  # C5, E5, G5
        duration = 0.12
        gap_duration = 0.05

        sounds = []
        for i, freq in enumerate(frequencies):
            t = np.linspace(0, duration, int(sample_rate * duration), False)
            # フェードイン・フェードアウト
            envelope = np.minimum(t / 0.02, 1) * np.minimum((duration - t) / 0.02, 1)
            tone = (np.sin(2 * np.pi * freq * t) * envelope * 0.35 * 32767).astype(np.int16)
            sounds.append(tone)
            if i < len(frequencies) - 1:
                gap = np.zeros(int(sample_rate * gap_duration), dtype=np.int16)
                sounds.append(gap)

        sound = np.concatenate(sounds)

        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(sound.tobytes())

        return wav_buffer.getvalue()
    except Exception as e:
        print(f"起動音生成エラー: {e}")
        return None


def convert_webm_to_wav(audio_data, filename="audio.webm"):
    """WebM音声をWAV形式に変換"""
    try:
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as webm_file:
            webm_file.write(audio_data)
            webm_path = webm_file.name

        wav_path = webm_path.replace(".webm", ".wav")

        result = subprocess.run([
            "ffmpeg", "-y", "-i", webm_path,
            "-ar", str(CONFIG["output_sample_rate"]), "-ac", "1", "-f", "wav", wav_path
        ], capture_output=True, timeout=30)

        if result.returncode != 0:
            print(f"ffmpeg変換エラー: {result.stderr.decode()}")
            return None

        with open(wav_path, "rb") as f:
            wav_data = f.read()

        os.unlink(webm_path)
        os.unlink(wav_path)

        return wav_data

    except Exception as e:
        print(f"音声変換エラー: {e}")
        return None


def play_audio_direct(audio_data):
    """音声を直接再生（PyAudio使用）"""
    if audio_data is None:
        print("音声データがありません")
        return

    audio = pyaudio.PyAudio()
    output_device = find_audio_device(audio, "output")

    print("再生中...")

    try:
        wav_buffer = io.BytesIO(audio_data)
        with wave.open(wav_buffer, 'rb') as wf:
            original_rate = wf.getframerate()
            channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()

            # 48kHzにリサンプリングが必要な場合
            if original_rate != CONFIG["output_sample_rate"]:
                frames = wf.readframes(wf.getnframes())
                audio_np = np.frombuffer(frames, dtype=np.int16)
                # 簡易リサンプリング
                ratio = CONFIG["output_sample_rate"] / original_rate
                new_length = int(len(audio_np) * ratio)
                indices = np.linspace(0, len(audio_np) - 1, new_length).astype(int)
                resampled = audio_np[indices]
                frames = resampled.astype(np.int16).tobytes()
                rate = CONFIG["output_sample_rate"]
            else:
                frames = wf.readframes(wf.getnframes())
                rate = original_rate

            stream = audio.open(
                format=audio.get_format_from_width(sampwidth),
                channels=1,
                rate=rate,
                output=True,
                output_device_index=output_device
            )

            # チャンクで再生
            chunk_size = 4096
            for i in range(0, len(frames), chunk_size):
                stream.write(frames[i:i+chunk_size])

            stream.stop_stream()
            stream.close()

    except Exception as e:
        print(f"再生エラー: {e}")
    finally:
        audio.terminate()


def on_voice_message_received(message):
    """スマホからの音声メッセージを受信したときの処理"""
    global firebase_messenger, global_audio_handler

    print(f"\nスマホから音声メッセージ受信!")

    # グローバルオーディオハンドラが利用可能か確認
    if not global_audio_handler:
        print("オーディオハンドラが初期化されていません")
        return

    # 通知音を再生
    notification = generate_notification_sound()
    if notification:
        global_audio_handler.play_audio_buffer(notification)

    try:
        audio_url = message.get("audio_url")
        if not audio_url:
            print("音声URLがありません")
            return

        # 音声データをダウンロード
        audio_data = firebase_messenger.download_audio(audio_url)
        if not audio_data:
            print("音声ダウンロードに失敗")
            return

        # WebMをWAVに変換して再生
        filename = message.get("filename", "audio.webm")
        wav_data = convert_webm_to_wav(audio_data, filename)
        if wav_data:
            global_audio_handler.play_audio_buffer(wav_data)
        else:
            print("音声変換に失敗")

        # 再生済みにマーク
        firebase_messenger.mark_as_played(message.get("id"))

    except Exception as e:
        print(f"メッセージ受信処理エラー: {e}")


def voice_send_func(message_text=None):
    """音声メッセージ録音モードを開始"""
    global firebase_messenger, voice_message_mode, voice_message_mode_timestamp

    if not firebase_messenger:
        return "Firebase Voice Messengerが初期化されていません。"

    # 録音モードを有効化（タイムスタンプ付き）
    voice_message_mode = True
    voice_message_mode_timestamp = time.time()
    print(f"音声メッセージモード開始 (タイムアウト: {VOICE_MESSAGE_MODE_TIMEOUT}秒)")

    # シンプルな応答（AIがそのまま読み上げる）
    return "ボタンを押して録音してください"


def voice_send_photo_func():
    """写真を撮影してスマホに送信"""
    global firebase_messenger, camera_lock

    if not firebase_messenger:
        return "Firebase Voice Messengerが初期化されていません。"

    print("写真を撮影してスマホに送信中...")

    try:
        # カメラロックを取得して撮影
        with camera_lock:
            image_path = "/tmp/ai_necklace_photo_send.jpg"
            result = subprocess.run(
                ["rpicam-still", "-o", image_path, "-t", "500", "--width", "1280", "--height", "960"],
                capture_output=True, timeout=10
            )

            if result.returncode != 0:
                return f"写真の撮影に失敗しました: {result.stderr.decode()}"

            # 写真データを読み込み
            with open(image_path, "rb") as f:
                photo_data = f.read()

        # ロック解放後にFirebaseに送信
        if firebase_messenger.send_photo_message(photo_data):
            print("写真をスマホに送信しました")
            return "写真をスマホに送信しました。"
        else:
            return "写真の送信に失敗しました。"

    except subprocess.TimeoutExpired:
        return "カメラの撮影がタイムアウトしました"
    except FileNotFoundError:
        return "カメラが見つかりません"
    except Exception as e:
        return f"写真送信エラー: {str(e)}"


def record_voice_message_sync():
    """
    音声メッセージ用の同期録音
    グローバルオーディオハンドラのPyAudioインスタンスを再利用
    """
    global running, button, global_audio_handler

    if not global_audio_handler:
        print("オーディオハンドラが初期化されていません")
        return None

    # グローバルハンドラのPyAudioインスタンスを使用
    audio = global_audio_handler.audio
    input_device = find_audio_device(audio, "input")

    if input_device is None:
        print("入力デバイスが見つかりません")
        return None

    print("音声メッセージ録音中... (ボタンを離すと停止)")

    stream = None
    try:
        stream = audio.open(
            format=pyaudio.paInt16,
            channels=CONFIG["channels"],
            rate=CONFIG["input_sample_rate"],  # 44100Hz
            input=True,
            input_device_index=input_device,
            frames_per_buffer=CONFIG["chunk_size"]
        )
    except Exception as e:
        print(f"ストリーム開始エラー: {e}")
        return None

    frames = []
    max_chunks = int(CONFIG["input_sample_rate"] / CONFIG["chunk_size"] * 60)  # 最大60秒
    start_time = time.time()

    try:
        while True:
            if not running:
                break

            # タイムアウト (60秒)
            if time.time() - start_time > 60:
                print("録音タイムアウト")
                break

            # ボタンが離されたら終了
            if button and not button.is_pressed:
                print("ボタンが離されました、録音終了")
                break

            if len(frames) >= max_chunks:
                print("最大録音時間に達しました")
                break

            try:
                available = stream.get_read_available()
                if available >= CONFIG["chunk_size"]:
                    data = stream.read(CONFIG["chunk_size"], exception_on_overflow=False)
                    frames.append(data)
                else:
                    time.sleep(0.001)
            except Exception as e:
                print(f"録音中にエラー: {e}")
                break
    finally:
        # 必ずストリームを閉じる
        if stream:
            try:
                stream.stop_stream()
                stream.close()
                print("音声メッセージ録音ストリーム終了")
            except Exception as e:
                print(f"ストリーム終了エラー: {e}")

    if len(frames) < 5:
        print("録音が短すぎます")
        return None

    # WAV形式に変換
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, 'wb') as wf:
        wf.setnchannels(CONFIG["channels"])
        wf.setsampwidth(2)  # 16bit
        wf.setframerate(CONFIG["input_sample_rate"])  # 44100Hz
        wf.writeframes(b''.join(frames))

    wav_buffer.seek(0)
    print(f"録音完了: {len(frames)}チャンク, 約{len(frames) * CONFIG['chunk_size'] / CONFIG['input_sample_rate']:.1f}秒")
    return wav_buffer


def transcribe_audio_with_gemini(wav_data):
    """Gemini APIで音声を文字起こし"""
    global gemini_client

    if not gemini_client:
        print("Geminiクライアントが初期化されていません")
        return None

    try:
        response = gemini_client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[
                types.Part.from_text(text="この音声の内容を正確に文字起こししてください。話された言葉をそのまま書き出してください。余計な説明は不要です。"),
                types.Part.from_bytes(data=wav_data, mime_type="audio/wav")
            ]
        )

        if response and response.text:
            transcribed = response.text.strip()
            print(f"文字起こし結果: {transcribed}")
            return transcribed
        return None

    except Exception as e:
        print(f"文字起こしエラー: {e}")
        return None


def send_recorded_voice_message():
    """録音した音声をスマホに送信"""
    global firebase_messenger, gemini_client, voice_message_mode, voice_message_mode_timestamp

    # 使用開始時点で即座にリセット（どんな結果でも1回限り）
    voice_message_mode = False
    voice_message_mode_timestamp = None
    print("voice_message_mode をリセットしました")

    try:
        # 同期録音を実行
        wav_buffer = record_voice_message_sync()

        if wav_buffer is None:
            print("録音データがありません")
            return False

        # Geminiで文字起こし
        print("音声をテキストに変換中...")
        wav_buffer.seek(0)
        wav_data = wav_buffer.read()
        transcribed_text = transcribe_audio_with_gemini(wav_data)

        # Firebaseに送信
        print("スマホに送信中...")
        if firebase_messenger.send_message(wav_data, text=transcribed_text):
            print("メッセージをスマホに送信しました")
            return True
        else:
            print("送信に失敗しました")
            return False

    except Exception as e:
        print(f"音声メッセージ送信エラー: {e}")
        return False


# ==================== アラーム機能 ====================

def load_alarms():
    """保存されたアラームを読み込み"""
    global alarms, alarm_next_id
    try:
        if os.path.exists(CONFIG["alarm_file_path"]):
            with open(CONFIG["alarm_file_path"], 'r') as f:
                data = json.load(f)
                alarms = data.get('alarms', [])
                alarm_next_id = data.get('next_id', 1)
                print(f"アラーム: {len(alarms)}件読み込み")
    except Exception as e:
        print(f"アラーム読み込みエラー: {e}")
        alarms = []
        alarm_next_id = 1


def save_alarms():
    """アラームを保存"""
    global alarms, alarm_next_id
    try:
        os.makedirs(os.path.dirname(CONFIG["alarm_file_path"]), exist_ok=True)
        with open(CONFIG["alarm_file_path"], 'w') as f:
            json.dump({'alarms': alarms, 'next_id': alarm_next_id}, f, ensure_ascii=False)
    except Exception as e:
        print(f"アラーム保存エラー: {e}")


def alarm_set_func(time_str, label="アラーム", message=""):
    """アラームを設定"""
    global alarms, alarm_next_id

    try:
        hour, minute = map(int, time_str.split(':'))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return "時刻が不正です。00:00〜23:59の形式で指定してください。"
    except:
        return "時刻の形式が不正です。HH:MM形式（例: 07:00）で指定してください。"

    alarm = {
        "id": alarm_next_id,
        "time": time_str,
        "label": label,
        "message": message or f"{label}の時間です",
        "enabled": True,
        "created_at": datetime.now().isoformat()
    }

    alarms.append(alarm)
    alarm_next_id += 1
    save_alarms()

    return f"{time_str}に「{label}」のアラームを設定しました。"


def alarm_list_func():
    """アラーム一覧を取得"""
    global alarms

    if not alarms:
        return "設定されているアラームはありません。"

    result = "アラーム一覧:\n"
    for alarm in alarms:
        status = "有効" if alarm.get("enabled", True) else "無効"
        result += f"{alarm['id']}. {alarm['time']} - {alarm['label']} ({status})\n"

    return result.strip()


def alarm_delete_func(alarm_id):
    """アラームを削除"""
    global alarms

    try:
        alarm_id = int(alarm_id)
    except:
        return "アラームIDは数字で指定してください。"

    for i, alarm in enumerate(alarms):
        if alarm['id'] == alarm_id:
            deleted = alarms.pop(i)
            save_alarms()
            return f"「{deleted['label']}」({deleted['time']})のアラームを削除しました。"

    return f"ID {alarm_id} のアラームが見つかりません。"


# アラーム監視用のグローバル変数
alarm_thread = None
alarm_client = None  # GeminiLiveClientへの参照


def check_alarms_and_notify():
    """アラームをチェックして通知（バックグラウンドスレッド用）"""
    global running, alarms, alarm_client

    last_triggered = {}  # 同じアラームが連続で鳴らないように

    while running:
        try:
            now = datetime.now()
            current_time = now.strftime("%H:%M")

            alarms_to_delete = []  # 削除するアラームのIDリスト

            for alarm in alarms:
                if not alarm.get("enabled", True):
                    continue

                alarm_id = alarm['id']
                alarm_time = alarm['time']

                # 同じ分に複数回鳴らないようにチェック
                trigger_key = f"{alarm_id}_{current_time}"
                if trigger_key in last_triggered:
                    continue

                if alarm_time == current_time:
                    print(f"アラーム発動: {alarm['label']} ({alarm_time})")
                    last_triggered[trigger_key] = True

                    # Gemini Live APIを通じて音声通知
                    if alarm_client and alarm_client.is_connected:
                        try:
                            message = alarm.get('message', f"{alarm['label']}の時間です")
                            notification = f"アラームです。{message}"
                            # 非同期で送信するためにスレッドセーフな方法で
                            asyncio.run_coroutine_threadsafe(
                                alarm_client.send_text_message(notification),
                                alarm_client.loop
                            )
                        except Exception as e:
                            print(f"アラーム通知エラー: {e}")

                    # 発動したアラームを削除リストに追加
                    alarms_to_delete.append(alarm_id)

            # 発動したアラームを削除
            if alarms_to_delete:
                for alarm_id in alarms_to_delete:
                    alarms[:] = [a for a in alarms if a['id'] != alarm_id]
                    print(f"アラーム削除: ID {alarm_id}")
                save_alarms()

            # 古いトリガー記録をクリア（1分以上前のもの）
            keys_to_remove = [k for k in last_triggered if not k.endswith(current_time)]
            for k in keys_to_remove:
                del last_triggered[k]

        except Exception as e:
            print(f"アラームチェックエラー: {e}")

        time.sleep(10)  # 10秒ごとにチェック


def start_alarm_thread():
    """アラーム監視スレッドを開始"""
    global alarm_thread
    alarm_thread = threading.Thread(target=check_alarms_and_notify, daemon=True)
    alarm_thread.start()
    print("アラーム監視スレッド開始")


# ==================== カメラ機能 ====================

def camera_capture_func(prompt="この画像に何が写っていますか？簡潔に説明してください。"):
    """カメラで撮影してGemini Visionで画像を解析"""
    global gemini_client, camera_lock

    # カメラロックを取得
    with camera_lock:
        print("カメラで撮影中...")

        try:
            image_path = "/tmp/ai_necklace_capture.jpg"
            result = subprocess.run(
                ["rpicam-still", "-o", image_path, "-t", "500", "--width", "1280", "--height", "960"],
                capture_output=True, text=True, timeout=10
            )

            if result.returncode != 0:
                return f"カメラでの撮影に失敗しました: {result.stderr}"

            with open(image_path, "rb") as f:
                image_data = f.read()

        except subprocess.TimeoutExpired:
            return "カメラの撮影がタイムアウトしました"
        except FileNotFoundError:
            return "カメラが見つかりません"
        except Exception as e:
            return f"カメラエラー: {str(e)}"

    # ロック解放後に画像解析（時間がかかるのでロック外で実行）
    print("画像を解析中...")

    try:
        # Gemini Vision API を使用
        response = gemini_client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[
                types.Part.from_text(text=prompt + "\n\n日本語で回答してください。音声で読み上げるため、1-2文程度の簡潔な説明をお願いします。"),
                types.Part.from_bytes(data=image_data, mime_type="image/jpeg")
            ]
        )

        return response.text

    except Exception as e:
        return f"画像解析エラー: {str(e)}"


def gmail_send_photo_func(to=None, subject="写真を送ります", body=""):
    """写真を撮影してメール送信"""
    global gmail_service, last_email_list, camera_lock

    if not gmail_service:
        return "Gmail機能が初期化されていません"

    if not to:
        if not last_email_list:
            return "送信先が指定されていません。"
        to_raw = last_email_list[0].get('from_email', '')
        match = re.search(r'<([^>]+)>', to_raw)
        to = match.group(1) if match else to_raw.strip()

    try:
        # カメラロックを取得して撮影
        with camera_lock:
            print("写真を撮影中...")
            image_path = "/tmp/ai_necklace_capture.jpg"
            result = subprocess.run(
                ["rpicam-still", "-o", image_path, "-t", "500", "--width", "1280", "--height", "960"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                return f"写真の撮影に失敗しました"

            with open(image_path, 'rb') as f:
                img_data = f.read()

        # ロック解放後にメール送信
        message = MIMEMultipart()
        message['to'] = to
        message['subject'] = subject
        message.attach(MIMEText(body or "写真を送ります。", 'plain'))

        img_part = MIMEBase('image', 'jpeg')
        img_part.set_payload(img_data)
        encoders.encode_base64(img_part)
        filename = f"photo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        img_part.add_header('Content-Disposition', 'attachment', filename=filename)
        message.attach(img_part)

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        gmail_service.users().messages().send(userId='me', body={'raw': raw}).execute()

        to_name = to.split('@')[0]
        return f"{to_name}さんに写真付きメールを送信しました"

    except Exception as e:
        return f"写真付きメール送信エラー: {str(e)}"


# ==================== ライフログ機能 ====================

def capture_lifelog_photo():
    """ライフログ用の写真を撮影して保存（ローカル + Firebase）"""
    global lifelog_photo_count, camera_lock, firebase_messenger

    # カメラロックを即座に試行（ユーザー操作を優先するため待機しない）
    if not camera_lock.acquire(blocking=False):
        print("ライフログ撮影スキップ: カメラ使用中（ユーザー操作優先）")
        return False

    try:
        # 今日の日付でディレクトリを作成
        today = datetime.now().strftime("%Y-%m-%d")
        lifelog_dir = os.path.join(CONFIG["lifelog_dir"], today)
        os.makedirs(lifelog_dir, exist_ok=True)

        # タイムスタンプ付きのファイル名
        timestamp = datetime.now().strftime("%H%M%S")
        filename = f"{timestamp}.jpg"
        image_path = os.path.join(lifelog_dir, filename)

        # カメラで撮影
        result = subprocess.run(
            ["rpicam-still", "-o", image_path, "-t", "500", "--width", "1280", "--height", "960"],
            capture_output=True, timeout=10
        )

        if result.returncode == 0:
            lifelog_photo_count += 1
            print(f"ライフログ撮影: {image_path} (今日{lifelog_photo_count}枚目)")

            # シャッター音を再生
            shutter_sound = generate_shutter_sound()
            if shutter_sound:
                play_audio_direct(shutter_sound)

            # Firebaseにアップロード（非同期的に実行、失敗してもローカル保存は成功とする）
            if firebase_messenger:
                try:
                    with open(image_path, "rb") as f:
                        photo_data = f.read()
                    if firebase_messenger.upload_lifelog_photo(photo_data, today, timestamp):
                        print(f"Firebaseアップロード成功")
                    else:
                        print(f"Firebaseアップロード失敗（ローカルは保存済み）")
                except Exception as e:
                    print(f"Firebaseアップロードエラー: {e}（ローカルは保存済み）")

            return True
        else:
            print(f"ライフログ撮影失敗: {result.stderr.decode()}")
            return False

    except subprocess.TimeoutExpired:
        print("ライフログ撮影タイムアウト")
        return False
    except Exception as e:
        print(f"ライフログ撮影エラー: {e}")
        return False
    finally:
        camera_lock.release()


def lifelog_thread_func():
    """ライフログ撮影のバックグラウンドスレッド"""
    global running, lifelog_enabled, lifelog_photo_count

    last_date = datetime.now().strftime("%Y-%m-%d")
    retry_interval = 30  # リトライ間隔（秒）

    while running:
        if lifelog_enabled:
            # 日付が変わったらカウントをリセット
            current_date = datetime.now().strftime("%Y-%m-%d")
            if current_date != last_date:
                lifelog_photo_count = 0
                last_date = current_date
                print(f"日付変更: ライフログカウントをリセット")

            # 撮影
            success = capture_lifelog_photo()

            # 撮影成功なら通常間隔、スキップなら30秒後にリトライ
            if success:
                wait_time = CONFIG["lifelog_interval"]
            else:
                wait_time = retry_interval
                print(f"{retry_interval}秒後にリトライします")
        else:
            wait_time = CONFIG["lifelog_interval"]

        # 次の撮影まで待機（1秒ごとにチェックして停止に素早く対応）
        for _ in range(wait_time):
            if not running:
                break
            if lifelog_enabled:
                time.sleep(1)
            else:
                # ライフログ無効時は長めにスリープ
                time.sleep(5)
                break


def start_lifelog_thread():
    """ライフログスレッドを開始"""
    global lifelog_thread
    if lifelog_thread is None or not lifelog_thread.is_alive():
        lifelog_thread = threading.Thread(target=lifelog_thread_func, daemon=True)
        lifelog_thread.start()
        print("ライフログスレッド開始")


def lifelog_start_func():
    """ライフログ撮影を開始"""
    global lifelog_enabled

    if lifelog_enabled:
        return "ライフログは既に動作中です。"

    lifelog_enabled = True
    start_lifelog_thread()

    interval_min = CONFIG["lifelog_interval"] // 60
    return f"ライフログを開始しました。{interval_min}分ごとに自動撮影します。"


def lifelog_stop_func():
    """ライフログ撮影を停止"""
    global lifelog_enabled

    if not lifelog_enabled:
        return "ライフログは動作していません。"

    lifelog_enabled = False
    return "ライフログを停止しました。"


def lifelog_status_func():
    """ライフログのステータスを取得"""
    global lifelog_enabled, lifelog_photo_count

    status = "動作中" if lifelog_enabled else "停止中"
    today = datetime.now().strftime("%Y-%m-%d")
    lifelog_dir = os.path.join(CONFIG["lifelog_dir"], today)

    # 実際のファイル数をカウント
    actual_count = 0
    if os.path.exists(lifelog_dir):
        actual_count = len([f for f in os.listdir(lifelog_dir) if f.endswith('.jpg')])

    interval_min = CONFIG["lifelog_interval"] // 60
    return f"ライフログは{status}です。今日は{actual_count}枚撮影しました。撮影間隔は{interval_min}分です。"


# ==================== ツール実行 ====================

def execute_tool(tool_name, arguments):
    """ツールを実行"""
    print(f"ツール実行: {tool_name} - {arguments}")

    if tool_name == "gmail_list":
        return gmail_list_func(
            query=arguments.get("query", "is:unread"),
            max_results=arguments.get("max_results", 5)
        )
    elif tool_name == "gmail_read":
        return gmail_read_func(arguments.get("message_id"))
    elif tool_name == "gmail_send":
        return gmail_send_func(
            to=arguments.get("to"),
            subject=arguments.get("subject"),
            body=arguments.get("body")
        )
    elif tool_name == "gmail_reply":
        return gmail_reply_func(
            message_id=arguments.get("message_id"),
            body=arguments.get("body"),
            attach_photo=arguments.get("attach_photo", False)
        )
    elif tool_name == "alarm_set":
        return alarm_set_func(
            time_str=arguments.get("time"),
            label=arguments.get("label", "アラーム"),
            message=arguments.get("message", "")
        )
    elif tool_name == "alarm_list":
        return alarm_list_func()
    elif tool_name == "alarm_delete":
        return alarm_delete_func(arguments.get("alarm_id"))
    elif tool_name == "camera_capture":
        return camera_capture_func(arguments.get("prompt", "この画像に何が写っていますか？"))
    elif tool_name == "gmail_send_photo":
        return gmail_send_photo_func(
            to=arguments.get("to"),
            subject=arguments.get("subject", "写真を送ります"),
            body=arguments.get("body", "")
        )
    elif tool_name == "voice_send":
        return voice_send_func()
    elif tool_name == "voice_send_photo":
        return voice_send_photo_func()
    elif tool_name == "lifelog_start":
        return lifelog_start_func()
    elif tool_name == "lifelog_stop":
        return lifelog_stop_func()
    elif tool_name == "lifelog_status":
        return lifelog_status_func()
    else:
        return f"不明なツール: {tool_name}"


# ==================== Gemini Live API用ツール定義 ====================

def get_gemini_tools():
    """Gemini Live API用のツール定義を取得"""
    gmail_list_tool = {
        "name": "gmail_list",
        "description": "メール一覧を取得します。「メールを確認して」「未読メールを読んで」などと言われたら使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "検索クエリ（例: is:unread, from:xxx@gmail.com）"},
                "max_results": {"type": "integer", "description": "取得件数"}
            }
        }
    }

    gmail_read_tool = {
        "name": "gmail_read",
        "description": "メール本文を読み取ります。「1番目のメールを読んで」などと言われたら使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "メールID（番号: 1, 2, 3など）"}
            },
            "required": ["message_id"]
        }
    }

    gmail_send_tool = {
        "name": "gmail_send",
        "description": "新規メールを送信します。",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "宛先メールアドレス"},
                "subject": {"type": "string", "description": "件名"},
                "body": {"type": "string", "description": "本文"}
            },
            "required": ["to", "subject", "body"]
        }
    }

    gmail_reply_tool = {
        "name": "gmail_reply",
        "description": "メールに返信します。「さっきのメールに返信して」などと言われたら使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "返信するメールの番号（1, 2, 3など）"},
                "body": {"type": "string", "description": "返信本文"}
            },
            "required": ["message_id", "body"]
        }
    }

    alarm_set_tool = {
        "name": "alarm_set",
        "description": "アラームを設定します。「7時にアラームをセットして」などと言われたら使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "time": {"type": "string", "description": "時刻（HH:MM形式、例: 07:00, 14:30）"},
                "label": {"type": "string", "description": "ラベル（例: 起床）"},
                "message": {"type": "string", "description": "読み上げメッセージ"}
            },
            "required": ["time"]
        }
    }

    alarm_list_tool = {
        "name": "alarm_list",
        "description": "アラーム一覧を取得します。「アラームを確認して」などと言われたら使用。",
        "parameters": {"type": "object", "properties": {}}
    }

    alarm_delete_tool = {
        "name": "alarm_delete",
        "description": "アラームを削除します。",
        "parameters": {
            "type": "object",
            "properties": {
                "alarm_id": {"type": "integer", "description": "アラームID（番号）"}
            },
            "required": ["alarm_id"]
        }
    }

    camera_capture_tool = {
        "name": "camera_capture",
        "description": "カメラで撮影して画像を説明します。「写真を撮って」「何が見える？」「これは何？」「目の前にあるものを教えて」などと言われたら使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "画像に対する質問"}
            }
        }
    }

    gmail_send_photo_tool = {
        "name": "gmail_send_photo",
        "description": "写真を撮影してメールで送信します。「写真を撮って送って」などと言われたら使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "宛先メールアドレス（省略時は直前のメール相手）"},
                "subject": {"type": "string", "description": "件名"},
                "body": {"type": "string", "description": "本文"}
            }
        }
    }

    voice_send_tool = {
        "name": "voice_send",
        "description": "スマホに音声メッセージを送信します。「スマホにメッセージを送って」「ボイスメッセージを送りたい」などと言われたら使用。ユーザーの録音した声がそのまま送信されます。",
        "parameters": {"type": "object", "properties": {}}
    }

    voice_send_photo_tool = {
        "name": "voice_send_photo",
        "description": "写真を撮影してスマホに送信します。「スマホに写真を送って」「写真を撮ってスマホに送って」などと言われたら使用。",
        "parameters": {"type": "object", "properties": {}}
    }

    lifelog_start_tool = {
        "name": "lifelog_start",
        "description": "ライフログ撮影を開始します。「ライフログ開始」「ライフログを始めて」「定期撮影を開始」などと言われたら使用。1分ごとに自動で写真を撮影して保存します。",
        "parameters": {"type": "object", "properties": {}}
    }

    lifelog_stop_tool = {
        "name": "lifelog_stop",
        "description": "ライフログ撮影を停止します。「ライフログ停止」「ライフログを止めて」「定期撮影を停止」などと言われたら使用。",
        "parameters": {"type": "object", "properties": {}}
    }

    lifelog_status_tool = {
        "name": "lifelog_status",
        "description": "ライフログのステータスを確認します。「今日何枚撮った？」「ライフログの状態」「撮影枚数を教えて」などと言われたら使用。",
        "parameters": {"type": "object", "properties": {}}
    }

    # 辞書形式からtypes.FunctionDeclarationに変換
    def to_function_declaration(tool_dict):
        params = tool_dict.get("parameters", {})
        properties = params.get("properties", {})
        required = params.get("required", [])

        schema_props = {}
        for name, prop in properties.items():
            prop_type = prop.get("type", "string").upper()
            schema_props[name] = types.Schema(
                type=prop_type,
                description=prop.get("description", "")
            )

        return types.FunctionDeclaration(
            name=tool_dict["name"],
            description=tool_dict["description"],
            parameters=types.Schema(
                type="OBJECT",
                properties=schema_props,
                required=required if required else None
            )
        )

    function_declarations = [
        to_function_declaration(gmail_list_tool),
        to_function_declaration(gmail_read_tool),
        to_function_declaration(gmail_send_tool),
        to_function_declaration(gmail_reply_tool),
        to_function_declaration(alarm_set_tool),
        to_function_declaration(alarm_list_tool),
        to_function_declaration(alarm_delete_tool),
        to_function_declaration(camera_capture_tool),
        to_function_declaration(gmail_send_photo_tool),
        to_function_declaration(voice_send_tool),
        to_function_declaration(voice_send_photo_tool),
        to_function_declaration(lifelog_start_tool),
        to_function_declaration(lifelog_stop_tool),
        to_function_declaration(lifelog_status_tool),
    ]

    return [types.Tool(function_declarations=function_declarations)]


# ==================== オーディオハンドラ ====================

class GeminiAudioHandler:
    """Gemini Live API用音声処理ハンドラ (PyAudio使用 - raspi-voice3と同じ方式)"""

    def __init__(self):
        self.audio = pyaudio.PyAudio()
        self.input_stream = None
        self.output_stream = None
        self.is_recording = False
        self.is_playing = False

    def start_input_stream(self):
        input_device = CONFIG["input_device_index"]
        if input_device is None:
            input_device = find_audio_device(self.audio, "input")

        if input_device is None:
            print("入力デバイスが見つかりません")
            return False

        try:
            self.input_stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=CONFIG["channels"],
                rate=CONFIG["input_sample_rate"],
                input=True,
                input_device_index=input_device,
                frames_per_buffer=CONFIG["chunk_size"]
            )
            self.is_recording = True
            print("マイク入力開始")
            return True
        except Exception as e:
            print(f"マイク入力エラー: {e}")
            return False

    def stop_input_stream(self):
        if self.input_stream:
            self.is_recording = False
            self.input_stream.stop_stream()
            self.input_stream.close()
            self.input_stream = None
            print("マイク入力停止")

    def read_audio_chunk(self):
        """音声チャンクを読み取り、Gemini Live API用に16kHzにリサンプリング"""
        if self.input_stream and self.is_recording:
            try:
                data = self.input_stream.read(CONFIG["chunk_size"], exception_on_overflow=False)
                # 44.1kHz -> 16kHzにリサンプリング
                resampled = resample_audio(data, CONFIG["input_sample_rate"], CONFIG["send_sample_rate"])
                return resampled
            except Exception as e:
                print(f"音声読み取りエラー: {e}")
        return None

    def start_output_stream(self):
        """PyAudioを使用してスピーカー出力を開始（raspi-voice3と同じ）"""
        output_device = CONFIG["output_device_index"]
        if output_device is None:
            output_device = find_audio_device(self.audio, "output")

        try:
            self.output_stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=CONFIG["channels"],
                rate=CONFIG["output_sample_rate"],
                output=True,
                output_device_index=output_device,
                frames_per_buffer=CONFIG["chunk_size"] * 2
            )
            self.is_playing = True
            print("スピーカー出力開始")
        except Exception as e:
            print(f"スピーカー出力エラー: {e}")
            self.output_stream = None
            self.is_playing = False

    def stop_output_stream(self):
        if self.output_stream:
            self.is_playing = False
            self.output_stream.stop_stream()
            self.output_stream.close()
            self.output_stream = None
            print("スピーカー出力停止")

    def play_audio_chunk(self, audio_data):
        """Gemini出力（24kHz）を48kHzにリサンプリングして再生"""
        if self.output_stream and self.is_playing:
            try:
                resampled = resample_audio(audio_data, CONFIG["receive_sample_rate"], CONFIG["output_sample_rate"])
                self.output_stream.write(resampled)
            except Exception as e:
                print(f"音声再生エラー: {e}")

    def play_audio_buffer(self, audio_data):
        """完全な音声バッファを再生（WAVデータ）- raspi-voice3と同じ方式"""
        if audio_data is None:
            print("音声データがありません")
            return

        print("音声バッファ再生中...")

        try:
            wav_buffer = io.BytesIO(audio_data)
            with wave.open(wav_buffer, 'rb') as wf:
                original_rate = wf.getframerate()
                frames = wf.readframes(wf.getnframes())

                # 必要に応じてリサンプリング
                if original_rate != CONFIG["output_sample_rate"]:
                    audio_np = np.frombuffer(frames, dtype=np.int16)
                    ratio = CONFIG["output_sample_rate"] / original_rate
                    new_length = int(len(audio_np) * ratio)
                    indices = np.linspace(0, len(audio_np) - 1, new_length).astype(int)
                    resampled = audio_np[indices]
                    frames = resampled.astype(np.int16).tobytes()

                # 既存の出力ストリームに書き込み
                if self.output_stream and self.is_playing:
                    chunk_size = 4096
                    for i in range(0, len(frames), chunk_size):
                        self.output_stream.write(frames[i:i+chunk_size])
                else:
                    print("出力ストリームが利用不可")

        except Exception as e:
            print(f"音声バッファ再生エラー: {e}")

    def cleanup(self):
        self.stop_input_stream()
        self.stop_output_stream()
        if self.audio:
            self.audio.terminate()


# ==================== Gemini Live APIクライアント ====================

class GeminiLiveClient:
    """Google Gemini Live APIクライアント"""

    # 再接続設定
    MAX_RECONNECT_ATTEMPTS = 5
    RECONNECT_DELAY_BASE = 2  # 秒（指数バックオフの基底）

    def __init__(self, audio_handler: GeminiAudioHandler):
        # APIキーを取得（GOOGLE_API_KEY を優先）
        self.api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY または GEMINI_API_KEY が設定されていません")

        self.audio_handler = audio_handler
        self.session = None
        self.session_context = None  # コンテキストマネージャーを保持
        self.is_connected = False
        self.is_responding = False
        self.pending_tool_calls = {}
        self.loop = None  # イベントループ参照（スレッド間通信用）
        self.needs_reconnect = False  # 再接続が必要かどうか
        self.reconnect_count = 0  # 連続再接続回数

        # Geminiクライアント初期化（環境変数から自動で読み込むが、明示的にも渡す）
        self.client = genai.Client(api_key=self.api_key)

    def get_config(self):
        """Gemini Live APIセッション設定を取得"""
        return {
            "response_modalities": ["AUDIO"],
            "system_instruction": CONFIG["instructions"],
            "speech_config": {
                "voice_config": {
                    "prebuilt_voice_config": {
                        "voice_name": CONFIG["voice"]
                    }
                }
            },
            # プッシュトゥトークモード: 自動VADを無効化して手動制御
            "realtime_input_config": {
                "automatic_activity_detection": {
                    "disabled": True
                }
            },
            # 入力音声の文字起こしを有効化（デバッグ用）
            "input_audio_transcription": {},
            "tools": get_gemini_tools(),
        }

    async def connect(self):
        print(f"Gemini Live APIに接続中... ({CONFIG['model']})")

        try:
            # live.connect()はコンテキストマネージャーを返すので、__aenter__()で入る
            self.session_context = self.client.aio.live.connect(
                model=CONFIG["model"],
                config=self.get_config()
            )
            self.session = await self.session_context.__aenter__()
            self.is_connected = True
            self.loop = asyncio.get_event_loop()
            print("Gemini Live API接続完了")
        except Exception as e:
            print(f"接続エラー: {e}")
            raise

    async def send_activity_start(self):
        """音声活動開始を通知（プッシュトゥトーク開始）"""
        if not self.is_connected or not self.session:
            return

        try:
            await self.session.send_realtime_input(
                activity_start=types.ActivityStart()
            )
            print("activity_start送信")
        except Exception as e:
            print(f"activity_start送信エラー: {e}")

    async def send_activity_end(self):
        """音声活動終了を通知（プッシュトゥトーク終了）"""
        if not self.is_connected or not self.session:
            return

        try:
            await self.session.send_realtime_input(
                activity_end=types.ActivityEnd()
            )
            print("activity_end送信")
        except Exception as e:
            print(f"activity_end送信エラー: {e}")

    async def send_audio_chunk(self, audio_data):
        """音声チャンクを送信"""
        if not self.is_connected or not self.session:
            print(f"送信スキップ: connected={self.is_connected}, session={self.session is not None}")
            return

        try:
            # デバッグ: 最初のチャンクだけサイズを表示
            if not hasattr(self, '_audio_debug_shown'):
                self._audio_debug_shown = True
                print(f"\n[DEBUG] Audio chunk size: {len(audio_data)} bytes")

            # Gemini Live APIは {"data": bytes, "mime_type": str} 形式を期待
            await self.session.send_realtime_input(
                audio={"data": audio_data, "mime_type": "audio/pcm;rate=16000"}
            )
            print(".", end="", flush=True)  # 送信確認用ドット
        except Exception as e:
            print(f"音声送信エラー: {e}")

    async def send_text_message(self, text):
        """テキストメッセージを送信（アラーム通知用）"""
        if not self.is_connected or not self.session:
            return

        try:
            await self.session.send_client_content(
                turns={"role": "user", "parts": [{"text": text}]},
                turn_complete=True
            )
            print(f"システム通知: {text}")
        except Exception as e:
            print(f"テキスト送信エラー: {e}")

    async def send_tool_response(self, function_responses):
        """ツール実行結果を送信"""
        if not self.is_connected or not self.session:
            return

        try:
            await self.session.send_tool_response(function_responses=function_responses)
            print(f"ツール結果送信完了")
        except Exception as e:
            print(f"ツール結果送信エラー: {e}")

    async def receive_messages(self):
        """サーバーからのメッセージを受信"""
        global running

        print("受信ループ開始")
        try:
            while running and self.is_connected:
                try:
                    # receive()はイテレータを返す（待機）
                    print("receive()呼び出し待機中...")
                    async for response in self.session.receive():
                        if not running:
                            break

                        await self.handle_response(response)
                        # 正常にメッセージを受信できたら再接続カウントをリセット
                        self.reconnect_count = 0
                except StopAsyncIteration:
                    # ターンが終了した場合、次のターンを待つ
                    continue

        except Exception as e:
            print(f"受信エラー: {e}")
            self.is_connected = False
            self.needs_reconnect = True

    async def handle_response(self, response):
        """レスポンスを処理"""
        print(f"レスポンス受信: {type(response).__name__}")

        # サーバーコンテンツ
        if hasattr(response, 'server_content') and response.server_content:
            server_content = response.server_content

            # 割り込み検出
            if hasattr(server_content, 'interrupted') and server_content.interrupted:
                print("割り込み検出")
                self.is_responding = False

            # モデルのターン（音声データを含む）
            if hasattr(server_content, 'model_turn') and server_content.model_turn:
                self.is_responding = True
                for part in server_content.model_turn.parts:
                    # 音声データ
                    if hasattr(part, 'inline_data') and part.inline_data:
                        if hasattr(part.inline_data, 'data') and isinstance(part.inline_data.data, bytes):
                            self.audio_handler.play_audio_chunk(part.inline_data.data)
                    # テキスト
                    if hasattr(part, 'text') and part.text:
                        print(f"[AI] {part.text}")

            # ターン完了
            if hasattr(server_content, 'turn_complete') and server_content.turn_complete:
                self.is_responding = False
                print("応答完了")

            # 出力トランスクリプト
            if hasattr(server_content, 'output_transcription') and server_content.output_transcription:
                text = server_content.output_transcription.text
                if text:
                    print(f"[AI transcript] {text}")

            # 入力トランスクリプト（ユーザーの音声認識結果）
            if hasattr(server_content, 'input_transcription') and server_content.input_transcription:
                text = server_content.input_transcription.text
                if text:
                    print(f"[USER] {text}")

        # デバッグ: tool_callの有無を毎回確認
        if hasattr(response, 'tool_call'):
            tc = response.tool_call
            if tc:
                print(f"[DEBUG] tool_call found: {tc}")

        # ツール呼び出し
        if hasattr(response, 'tool_call') and response.tool_call:
            function_responses = []

            for fc in response.tool_call.function_calls:
                tool_name = fc.name
                arguments = dict(fc.args) if fc.args else {}

                print(f"ツール呼び出し: {tool_name}")

                # 長時間かかるツールは別スレッドで実行
                if tool_name in ["voice_send_photo", "camera_capture", "gmail_send_photo"]:
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, lambda: execute_tool(tool_name, arguments))
                else:
                    result = execute_tool(tool_name, arguments)

                function_responses.append(
                    types.FunctionResponse(
                        id=fc.id,
                        name=tool_name,
                        response={"result": result}
                    )
                )

            # ツール結果を送信
            if function_responses:
                await self.send_tool_response(function_responses)

    async def disconnect(self):
        if self.session_context:
            try:
                await self.session_context.__aexit__(None, None, None)
            except Exception:
                pass
            self.session_context = None
            self.session = None
            self.is_connected = False
            print("Gemini Live API切断")

    async def reset_session(self):
        """セッションをリセットして新しい会話を開始"""
        print("セッションリセット中...")

        # 古い接続をクリーンアップ
        await self.disconnect()
        self.pending_tool_calls = {}

        # 状態をリセット
        reset_voice_message_mode()

        try:
            await self.connect()
            print("セッションリセット完了 - 新しい会話を開始")
            return True
        except Exception as e:
            print(f"セッションリセット失敗: {e}")
            self.needs_reconnect = True
            return False

    async def reconnect(self):
        """接続を再確立する（指数バックオフ付き）"""
        global running

        self.reconnect_count += 1
        if self.reconnect_count > self.MAX_RECONNECT_ATTEMPTS:
            print(f"再接続回数が上限({self.MAX_RECONNECT_ATTEMPTS}回)に達しました。プログラムを終了します。")
            running = False
            return False

        # 指数バックオフで待機
        delay = self.RECONNECT_DELAY_BASE ** self.reconnect_count
        delay = min(delay, 60)  # 最大60秒
        print(f"{delay}秒後に再接続を試みます... (試行 {self.reconnect_count}/{self.MAX_RECONNECT_ATTEMPTS})")
        await asyncio.sleep(delay)

        # 古い接続をクリーンアップ
        await self.disconnect()
        self.needs_reconnect = False
        self.pending_tool_calls = {}

        # 状態をリセット
        reset_voice_message_mode()

        try:
            await self.connect()
            print("再接続成功!")
            return True
        except Exception as e:
            print(f"再接続失敗: {e}")
            self.needs_reconnect = True
            return False


async def audio_input_loop(client: GeminiLiveClient, audio_handler: GeminiAudioHandler):
    """音声入力ループ"""
    global running, button, is_recording, voice_message_mode

    while running:
        if CONFIG["use_button"] and button:
            if button.is_pressed:
                if not is_recording:
                    # タイムアウトチェック付きで voice_message_mode を確認
                    current_voice_mode = check_and_reset_voice_message_mode()

                    if current_voice_mode:
                        # 音声メッセージモード: 別スレッドで同期録音を実行
                        print("音声メッセージ録音開始（スレッドモード）")
                        is_recording = True
                        # スレッドで実行してイベントループをブロックしない
                        loop = asyncio.get_event_loop()
                        success = await loop.run_in_executor(None, send_recorded_voice_message)
                        is_recording = False
                        # 結果をログに出力（Geminiに送ると再度ツール呼び出しされるため）
                        if success:
                            print("メッセージ送信完了")
                        else:
                            print("メッセージ送信失敗")
                        continue
                    else:
                        print("ボタン押下検出 - 録音開始")

                        # 毎回セッションをリセットして新しい会話を開始
                        await client.reset_session()

                        if audio_handler.start_input_stream():
                            is_recording = True
                            # 音声活動開始を通知
                            await client.send_activity_start()
                        else:
                            print("録音開始失敗")
                            continue

                # Gemini Live APIに音声を送信
                chunk = audio_handler.read_audio_chunk()
                if chunk and len(chunk) > 0:
                    await client.send_audio_chunk(chunk)
            else:
                if is_recording:
                    is_recording = False
                    audio_handler.stop_input_stream()
                    print("ボタン離す - 録音停止")
                    # 音声活動終了を通知（これがGeminiに応答を促す）
                    await client.send_activity_end()

        await asyncio.sleep(0.01)


async def main_async():
    """非同期メインループ（自動再接続対応）"""
    global running, button, alarm_client, global_audio_handler

    audio_handler = GeminiAudioHandler()
    audio_handler.start_output_stream()
    global_audio_handler = audio_handler  # グローバルに設定（スマホ音声再生用）

    client = GeminiLiveClient(audio_handler)
    receive_task = None
    input_task = None
    first_start = True

    try:
        # アラーム監視スレッドを開始（接続状態に関係なく動作）
        alarm_client = client
        start_alarm_thread()

        # ライフログスレッドを開始（ただし撮影は「ライフログ開始」コマンドまで待機）
        start_lifelog_thread()

        while running:
            # 接続されていない場合は接続を試みる
            if not client.is_connected:
                if client.needs_reconnect:
                    # 再接続
                    success = await client.reconnect()
                    if not success:
                        continue
                else:
                    # 初回接続
                    try:
                        await client.connect()
                    except Exception as e:
                        print(f"接続エラー: {e}")
                        print("5秒後に再試行します...")
                        await asyncio.sleep(5)
                        continue

                # タスクを開始/再開
                if receive_task is None or receive_task.done():
                    receive_task = asyncio.create_task(client.receive_messages())
                if input_task is None or input_task.done():
                    input_task = asyncio.create_task(audio_input_loop(client, audio_handler))

                if first_start:
                    print("\n" + "=" * 50)
                    print("AI Necklace Gemini Live 起動（全機能版）")
                    print("=" * 50)
                    print(f"Gmail: {'有効' if gmail_service else '無効'}")
                    print(f"Firebase: {'有効' if firebase_messenger else '無効'}")
                    print(f"アラーム: {len(alarms)}件")
                    print(f"カメラ: 有効")
                    print(f"ライフログ: 待機中（{CONFIG['lifelog_interval'] // 60}分間隔）")
                    if CONFIG["use_button"]:
                        print(f"操作: GPIO{CONFIG['button_pin']}のボタンを押している間話す")
                    print("=" * 50)
                    print("\nコマンド例:")
                    print("  - 「メールを確認して」")
                    print("  - 「写真を撮って」「何が見える？」")
                    print("  - 「7時にアラームをセット」")
                    print("  - 「スマホにメッセージを送って」")
                    print("  - 「ライフログ開始」「ライフログ停止」")
                    print("=" * 50)
                    print("\n--- ボタンを押して話しかけてください ---\n")

                    # 起動完了音を再生
                    startup_sound = generate_startup_sound()
                    if startup_sound:
                        audio_handler.play_audio_buffer(startup_sound)
                        print("起動完了")
                    first_start = False
                else:
                    # 再接続時は短い通知音
                    print("再接続完了 - 会話を再開できます")

            await asyncio.sleep(0.1)

        # タスクをキャンセル
        if receive_task:
            receive_task.cancel()
            try:
                await receive_task
            except asyncio.CancelledError:
                pass
        if input_task:
            input_task.cancel()
            try:
                await input_task
            except asyncio.CancelledError:
                pass

    except Exception as e:
        print(f"エラー: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.disconnect()
        audio_handler.cleanup()


def main():
    """メインエントリーポイント"""
    global running, button, gemini_client

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("エラー: GOOGLE_API_KEY または GEMINI_API_KEY が設定されていません")
        sys.exit(1)

    # Geminiクライアント（カメラ用Vision API）
    gemini_client = genai.Client(api_key=api_key)

    # Gmail初期化
    init_gmail()

    # Firebase初期化
    init_firebase()

    # アラーム読み込み
    load_alarms()

    # ボタン初期化
    if CONFIG["use_button"] and GPIO_AVAILABLE:
        try:
            button = Button(CONFIG["button_pin"], pull_up=True, bounce_time=0.1)
            print(f"ボタン: GPIO{CONFIG['button_pin']}")
        except Exception as e:
            print(f"ボタン初期化エラー: {e}")
            button = None
            CONFIG["use_button"] = False
    else:
        button = None
        if CONFIG["use_button"]:
            CONFIG["use_button"] = False

    asyncio.run(main_async())
    print("終了しました")


if __name__ == "__main__":
    main()
