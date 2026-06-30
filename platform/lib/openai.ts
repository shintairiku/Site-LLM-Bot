// このモジュールはAPIルート（サーバーサイド）からのみimportすること。
// OPENAI_API_KEYを扱うためクライアントコンポーネントから参照してはならない。
import OpenAI from "openai";

let client: OpenAI | null = null;

/** サーバーサイド専用のOpenAIクライアント。OPENAI_API_KEYはクライアントに露出しない。 */
export function getOpenAI(): OpenAI {
  if (!client) {
    const apiKey = process.env.OPENAI_API_KEY;
    if (!apiKey) throw new Error("OPENAI_API_KEY is not configured");
    client = new OpenAI({ apiKey });
  }
  return client;
}

// 推論側（Python）と同じモデルを使うこと。次元(1536)はDBのvector(1536)と一致させる必要がある。
export const EMBEDDING_MODEL = process.env.OPENAI_EMBEDDING_MODEL ?? "text-embedding-3-small";

const EMBED_BATCH_SIZE = 96;

/** テキスト配列をembeddingに変換する。OpenAIの入力上限に合わせてバッチ分割する。 */
export async function embedTexts(texts: string[]): Promise<number[][]> {
  const openai = getOpenAI();
  const vectors: number[][] = [];
  for (let i = 0; i < texts.length; i += EMBED_BATCH_SIZE) {
    const batch = texts.slice(i, i + EMBED_BATCH_SIZE);
    const res = await openai.embeddings.create({ model: EMBEDDING_MODEL, input: batch });
    for (const item of res.data) vectors.push(item.embedding);
  }
  return vectors;
}

/** number[] を pgvector のテキストリテラル '[0.1,0.2,...]' へ変換する。 */
export function toVectorLiteral(embedding: number[]): string {
  return `[${embedding.join(",")}]`;
}
