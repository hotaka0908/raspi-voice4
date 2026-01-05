/**
 * Cloud Functions for AI Necklace Gemini Live
 *
 * ライフログ写真がFirebase Storageにアップロードされた時に
 * Gemini Vision APIで自動分析し、結果をRealtime Databaseに保存
 */

const { onObjectFinalized } = require("firebase-functions/v2/storage");
const { onRequest } = require("firebase-functions/v2/https");
const { defineSecret } = require("firebase-functions/params");
const { initializeApp } = require("firebase-admin/app");
const { getDatabase } = require("firebase-admin/database");
const { getStorage } = require("firebase-admin/storage");
const { GoogleGenerativeAI } = require("@google/generative-ai");

// Firebase Admin初期化
initializeApp();

// シークレット定義
const googleApiKey = defineSecret("GOOGLE_API_KEY");

/**
 * ライフログ写真分析関数
 *
 * トリガー: Firebase Storage に lifelogs/ パス配下にファイルがアップロードされた時
 * 処理: Gemini Vision APIで画像を分析し、結果をRealtime Databaseに保存
 */
exports.analyzeLifelogPhoto = onObjectFinalized(
  {
    region: "asia-northeast1",
    memory: "512MiB",
    timeoutSeconds: 120,
    secrets: [googleApiKey],
  },
  async (event) => {
    const filePath = event.data.name;
    const contentType = event.data.contentType;

    // lifelogs/ 配下の画像ファイルのみ処理
    if (!filePath.startsWith("lifelogs/")) {
      console.log("Not a lifelog file, skipping:", filePath);
      return null;
    }

    if (!contentType || !contentType.startsWith("image/")) {
      console.log("Not an image file, skipping:", filePath);
      return null;
    }

    console.log("Analyzing lifelog photo:", filePath);

    try {
      // Gemini API初期化（シークレットから取得）
      const genAI = new GoogleGenerativeAI(googleApiKey.value());

      // Storage から画像をダウンロード
      const bucket = getStorage().bucket(event.data.bucket);
      const file = bucket.file(filePath);
      const [imageBuffer] = await file.download();
      const base64Image = imageBuffer.toString("base64");

      // Gemini Vision APIで分析
      const model = genAI.getGenerativeModel({ model: "gemini-2.0-flash" });

      const prompt = `この画像はライフログとして自動撮影されたものです。
以下の情報を日本語で簡潔に抽出してください：

1. 場所の種類（屋内/屋外、オフィス/自宅/店舗など）
2. 主な活動や状況
3. 写っている人数（0人、1人、複数人）
4. 時間帯の推測（朝/昼/夕方/夜）
5. 特筆すべき物や出来事

回答は以下のJSON形式で返してください：
{
  "location": "場所の説明",
  "activity": "活動の説明",
  "people_count": "人数",
  "time_of_day": "時間帯",
  "notable": "特筆事項",
  "summary": "1文での要約"
}`;

      const result = await model.generateContent([
        prompt,
        {
          inlineData: {
            mimeType: contentType,
            data: base64Image,
          },
        },
      ]);

      const responseText = result.response.text();
      console.log("Gemini response:", responseText);

      // JSONを抽出
      let analysis;
      try {
        // JSONブロックを抽出（```json ... ``` 形式に対応）
        const jsonMatch = responseText.match(/\{[\s\S]*\}/);
        if (jsonMatch) {
          analysis = JSON.parse(jsonMatch[0]);
        } else {
          analysis = { summary: responseText, raw: true };
        }
      } catch (parseError) {
        console.error("JSON parse error:", parseError);
        analysis = { summary: responseText, raw: true };
      }

      // パスから日付と時刻を抽出 (lifelogs/2024-01-05/123456.jpg)
      const pathParts = filePath.split("/");
      const date = pathParts[1]; // 2024-01-05
      const timeFile = pathParts[2]; // 123456.jpg
      const time = timeFile.replace(".jpg", "");

      // Realtime Database に分析結果を保存
      const db = getDatabase();
      await db.ref(`lifelogs/${date}/${time}`).update({
        analyzed: true,
        analysis: analysis,
        analyzedAt: Date.now(),
      });

      console.log(`Analysis saved for ${date}/${time}`);
      return { success: true, path: filePath };

    } catch (error) {
      console.error("Error analyzing photo:", error);

      // エラー情報も保存
      const pathParts = filePath.split("/");
      if (pathParts.length >= 3) {
        const date = pathParts[1];
        const time = pathParts[2].replace(".jpg", "");
        const db = getDatabase();
        await db.ref(`lifelogs/${date}/${time}`).update({
          analyzed: false,
          analysisError: error.message,
          analyzedAt: Date.now(),
        });
      }

      return { success: false, error: error.message };
    }
  }
);

/**
 * ヘルスチェック用エンドポイント
 */
exports.healthCheck = onRequest(
  { region: "asia-northeast1" },
  (req, res) => {
    res.json({
      status: "ok",
      service: "ai-necklace-gemini-functions",
      timestamp: new Date().toISOString(),
      features: ["lifelog-analysis"],
    });
  }
);

/**
 * 手動で写真を分析するエンドポイント（デバッグ用）
 * POST /analyzePhoto
 * Body: { "path": "lifelogs/2024-01-05/123456.jpg" }
 */
exports.analyzePhotoManual = onRequest(
  {
    region: "asia-northeast1",
    memory: "512MiB",
    timeoutSeconds: 120,
    secrets: [googleApiKey],
  },
  async (req, res) => {
    if (req.method !== "POST") {
      res.status(405).json({ error: "Method not allowed" });
      return;
    }

    const { path } = req.body;
    if (!path) {
      res.status(400).json({ error: "path is required" });
      return;
    }

    try {
      // Gemini API初期化（シークレットから取得）
      const genAI = new GoogleGenerativeAI(googleApiKey.value());

      const bucket = getStorage().bucket();
      const file = bucket.file(path);

      const [exists] = await file.exists();
      if (!exists) {
        res.status(404).json({ error: "File not found" });
        return;
      }

      const [imageBuffer] = await file.download();
      const base64Image = imageBuffer.toString("base64");

      const [metadata] = await file.getMetadata();
      const contentType = metadata.contentType || "image/jpeg";

      const model = genAI.getGenerativeModel({ model: "gemini-2.0-flash" });

      const result = await model.generateContent([
        "この画像を日本語で簡潔に説明してください。",
        {
          inlineData: {
            mimeType: contentType,
            data: base64Image,
          },
        },
      ]);

      const responseText = result.response.text();

      res.json({
        success: true,
        path: path,
        analysis: responseText,
      });

    } catch (error) {
      console.error("Error:", error);
      res.status(500).json({ error: error.message });
    }
  }
);
