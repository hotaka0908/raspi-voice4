#!/usr/bin/env python3
"""
Firebase Voice Messaging Module
ラズパイとスマホ間で音声メッセージをやり取りするためのモジュール

Firebase Realtime Database + Cloud Storage を使用
REST API経由でアクセス（サービスアカウント不要）
"""

import os
import json
import time
import requests
import threading
import base64
from datetime import datetime
from pathlib import Path

# Firebase設定を外部ファイルから読み込み
try:
    from firebase_voice_config import FIREBASE_CONFIG
except ImportError:
    # 設定ファイルがない場合のフォールバック
    FIREBASE_CONFIG = {
        "apiKey": os.getenv("FIREBASE_API_KEY", ""),
        "authDomain": os.getenv("FIREBASE_AUTH_DOMAIN", ""),
        "databaseURL": os.getenv("FIREBASE_DATABASE_URL", ""),
        "projectId": os.getenv("FIREBASE_PROJECT_ID", ""),
        "storageBucket": os.getenv("FIREBASE_STORAGE_BUCKET", ""),
    }

# デバイス識別子
DEVICE_ID = "raspi"


class FirebaseVoiceMessenger:
    """Firebase を使った音声メッセージング"""

    def __init__(self, device_id=DEVICE_ID, on_message_received=None):
        """
        初期化

        Args:
            device_id: このデバイスのID（"raspi" または "phone"）
            on_message_received: メッセージ受信時のコールバック関数
        """
        self.device_id = device_id
        self.on_message_received = on_message_received
        self.db_url = FIREBASE_CONFIG["databaseURL"]
        self.storage_bucket = FIREBASE_CONFIG["storageBucket"]
        self.api_key = FIREBASE_CONFIG["apiKey"]
        self.running = False
        self.listener_thread = None
        self.last_processed_key = None

    def upload_audio(self, audio_data: bytes, filename: str = None) -> str:
        """
        音声データをFirebase Storageにアップロード

        Args:
            audio_data: 音声バイナリデータ
            filename: ファイル名（省略時は自動生成）

        Returns:
            ダウンロードURL
        """
        if filename is None:
            timestamp = int(time.time() * 1000)
            filename = f"{self.device_id}_{timestamp}.wav"

        # Firebase Storage REST API エンドポイント
        storage_url = f"https://firebasestorage.googleapis.com/v0/b/{self.storage_bucket}/o"

        # ファイルパスをURLエンコード
        encoded_path = requests.utils.quote(f"audio/{filename}", safe='')
        upload_url = f"{storage_url}/{encoded_path}"

        headers = {
            "Content-Type": "audio/wav",
        }

        response = requests.post(upload_url, headers=headers, data=audio_data)

        if response.status_code == 200:
            # ダウンロードURLを生成
            download_url = f"{storage_url}/{encoded_path}?alt=media"
            print(f"音声アップロード成功: {filename}")
            return download_url
        else:
            print(f"アップロードエラー: {response.status_code} - {response.text}")
            return None

    def upload_photo(self, photo_data: bytes, filename: str = None) -> str:
        """
        写真データをFirebase Storageにアップロード

        Args:
            photo_data: 写真バイナリデータ
            filename: ファイル名（省略時は自動生成）

        Returns:
            ダウンロードURL
        """
        if filename is None:
            timestamp = int(time.time() * 1000)
            filename = f"{self.device_id}_{timestamp}.jpg"

        # Firebase Storage REST API エンドポイント
        storage_url = f"https://firebasestorage.googleapis.com/v0/b/{self.storage_bucket}/o"

        # ファイルパスをURLエンコード（audioフォルダを使用）
        encoded_path = requests.utils.quote(f"audio/{filename}", safe='')
        upload_url = f"{storage_url}/{encoded_path}"

        headers = {
            "Content-Type": "image/jpeg",
        }

        response = requests.post(upload_url, headers=headers, data=photo_data)

        if response.status_code == 200:
            # ダウンロードURLを生成
            download_url = f"{storage_url}/{encoded_path}?alt=media"
            print(f"写真アップロード成功: {filename}")
            return download_url
        else:
            print(f"写真アップロードエラー: {response.status_code} - {response.text}")
            return None

    def send_message(self, audio_data: bytes, text: str = None) -> bool:
        """
        音声メッセージを送信

        Args:
            audio_data: 音声バイナリデータ
            text: テキスト（音声の文字起こしなど、オプション）

        Returns:
            成功したかどうか
        """
        # 音声をアップロード
        timestamp = int(time.time() * 1000)
        filename = f"{self.device_id}_{timestamp}.wav"
        audio_url = self.upload_audio(audio_data, filename)

        if not audio_url:
            return False

        # メタデータをRealtime Databaseに登録
        message_data = {
            "from": self.device_id,
            "audio_url": audio_url,
            "filename": filename,
            "timestamp": timestamp,
            "played": False,
        }

        if text:
            message_data["text"] = text

        db_url = f"{self.db_url}/messages.json"
        response = requests.post(db_url, json=message_data)

        if response.status_code == 200:
            print(f"メッセージ送信成功: {filename}")
            return True
        else:
            print(f"DB登録エラー: {response.status_code} - {response.text}")
            return False

    def send_photo_message(self, photo_data: bytes, text: str = None) -> bool:
        """
        写真メッセージを送信

        Args:
            photo_data: 写真バイナリデータ
            text: テキスト（オプション）

        Returns:
            成功したかどうか
        """
        # 写真をアップロード
        timestamp = int(time.time() * 1000)
        filename = f"{self.device_id}_{timestamp}.jpg"
        photo_url = self.upload_photo(photo_data, filename)

        if not photo_url:
            return False

        # メタデータをRealtime Databaseに登録
        message_data = {
            "from": self.device_id,
            "photo_url": photo_url,
            "filename": filename,
            "timestamp": timestamp,
            "played": False,
            "type": "photo",
        }

        if text:
            message_data["text"] = text

        db_url = f"{self.db_url}/messages.json"
        response = requests.post(db_url, json=message_data)

        if response.status_code == 200:
            print(f"写真メッセージ送信成功: {filename}")
            return True
        else:
            print(f"DB登録エラー: {response.status_code} - {response.text}")
            return False

    def upload_lifelog_photo(self, photo_data: bytes, date: str, time_str: str) -> bool:
        """
        ライフログ写真をFirebaseにアップロード

        Args:
            photo_data: 写真バイナリデータ
            date: 日付（YYYY-MM-DD形式）
            time_str: 時刻（HHMMSS形式）

        Returns:
            成功したかどうか
        """
        # Firebase Storage にアップロード
        # パス: lifelogs/{date}/{time}.jpg
        filename = f"{time_str}.jpg"
        storage_url = f"https://firebasestorage.googleapis.com/v0/b/{self.storage_bucket}/o"
        encoded_path = requests.utils.quote(f"lifelogs/{date}/{filename}", safe='')
        upload_url = f"{storage_url}/{encoded_path}"

        headers = {
            "Content-Type": "image/jpeg",
        }

        response = requests.post(upload_url, headers=headers, data=photo_data)

        if response.status_code != 200:
            print(f"ライフログ写真アップロードエラー: {response.status_code} - {response.text}")
            return False

        # ダウンロードURLを生成
        photo_url = f"{storage_url}/{encoded_path}?alt=media"
        print(f"ライフログ写真アップロード成功: lifelogs/{date}/{filename}")

        # Realtime Database にメタデータを保存
        # パス: lifelogs/{date}/{time_str}
        timestamp = int(time.time() * 1000)
        # HH:MM形式の時刻
        time_formatted = f"{time_str[:2]}:{time_str[2:4]}"

        # Realtime Database形式
        doc_data = {
            "deviceId": self.device_id,
            "timestamp": timestamp,
            "time": time_formatted,
            "photoUrl": photo_url,
            "analyzed": False,
            "analysis": ""
        }

        # Realtime Database REST API
        db_url = f"{self.db_url}/lifelogs/{date}/{time_str}.json"
        response = requests.put(db_url, json=doc_data)

        if response.status_code == 200:
            print(f"ライフログメタデータ保存成功: {date} {time_formatted}")
            return True
        else:
            print(f"Realtime Databaseエラー: {response.status_code} - {response.text}")
            # Storageへのアップロードは成功しているので、部分的な成功とする
            return True

    def get_messages(self, limit: int = 10, unplayed_only: bool = False) -> list:
        """
        メッセージ一覧を取得

        Args:
            limit: 取得件数
            unplayed_only: 未再生のみ取得

        Returns:
            メッセージリスト
        """
        # シンプルなクエリ（orderByはインデックス設定が必要なため使わない）
        db_url = f"{self.db_url}/messages.json"
        response = requests.get(db_url)

        if response.status_code != 200:
            print(f"メッセージ取得エラー: {response.status_code}")
            return []

        data = response.json()
        if not data:
            return []

        messages = []
        for key, value in data.items():
            if not isinstance(value, dict):
                continue
            value["id"] = key
            # 自分以外からのメッセージのみ
            if value.get("from") != self.device_id:
                if not unplayed_only or not value.get("played", False):
                    messages.append(value)

        # タイムスタンプでソート（新しい順）
        messages.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

        # 件数制限
        return messages[:limit]

    def download_audio(self, audio_url: str) -> bytes:
        """
        音声データをダウンロード

        Args:
            audio_url: 音声ファイルのURL

        Returns:
            音声バイナリデータ
        """
        response = requests.get(audio_url)
        if response.status_code == 200:
            return response.content
        else:
            print(f"ダウンロードエラー: {response.status_code}")
            return None

    def mark_as_played(self, message_id: str):
        """
        メッセージを再生済みにマーク

        Args:
            message_id: メッセージID
        """
        db_url = f"{self.db_url}/messages/{message_id}/played.json"
        response = requests.put(db_url, json=True)
        if response.status_code == 200:
            print(f"メッセージ {message_id} を再生済みにしました")

    def start_listening(self, poll_interval: float = 3.0):
        """
        新着メッセージの監視を開始（ポーリング方式）

        Args:
            poll_interval: ポーリング間隔（秒）
        """
        self.running = True
        self.processed_ids = set()  # 処理済みメッセージIDを追跡

        def poll_loop():
            # 既存のメッセージIDを記録（起動時に全て処理済みとする）
            messages = self.get_messages(limit=20)
            for msg in messages:
                self.processed_ids.add(msg.get("id"))
            print(f"既存メッセージ {len(self.processed_ids)} 件をスキップ")

            while self.running:
                try:
                    # 新着メッセージをチェック（全て取得して自分で判定）
                    messages = self.get_messages(limit=15, unplayed_only=False)

                    for msg in reversed(messages):  # 古い順に処理
                        msg_id = msg.get("id")

                        # 既に処理済みならスキップ
                        if msg_id in self.processed_ids:
                            continue

                        # 新着メッセージ
                        print(f"\n新着メッセージ: {msg.get('from')} - {msg.get('filename')}")

                        if self.on_message_received:
                            self.on_message_received(msg)

                        # 処理済みに追加
                        self.processed_ids.add(msg_id)

                        # 再生済みにマーク
                        self.mark_as_played(msg_id)

                except Exception as e:
                    print(f"ポーリングエラー: {e}")

                time.sleep(poll_interval)

        self.listener_thread = threading.Thread(target=poll_loop, daemon=True)
        self.listener_thread.start()
        print("メッセージ監視を開始しました")

    def stop_listening(self):
        """監視を停止"""
        self.running = False
        if self.listener_thread:
            self.listener_thread.join(timeout=5)
        print("メッセージ監視を停止しました")


# テスト用コード
if __name__ == "__main__":
    import sys

    def on_message(msg):
        print(f"\n=== 新着メッセージ ===")
        print(f"From: {msg.get('from')}")
        print(f"Time: {datetime.fromtimestamp(msg.get('timestamp', 0) / 1000)}")
        print(f"Text: {msg.get('text', '(なし)')}")
        print(f"Audio: {msg.get('audio_url')}")
        print("=" * 30)

    messenger = FirebaseVoiceMessenger(device_id="raspi", on_message_received=on_message)

    if len(sys.argv) > 1:
        if sys.argv[1] == "send":
            # テスト送信
            test_audio = b"RIFF" + b"\x00" * 100  # ダミー音声データ
            messenger.send_message(test_audio, text="テストメッセージ")
        elif sys.argv[1] == "list":
            # メッセージ一覧
            messages = messenger.get_messages()
            for msg in messages:
                print(f"{msg.get('from')}: {msg.get('filename')} - {msg.get('text', '')}")
        elif sys.argv[1] == "listen":
            # 監視モード
            messenger.start_listening()
            print("Ctrl+C で終了")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                messenger.stop_listening()
    else:
        print("Usage:")
        print("  python firebase_voice.py send   - テストメッセージ送信")
        print("  python firebase_voice.py list   - メッセージ一覧")
        print("  python firebase_voice.py listen - 監視モード")
