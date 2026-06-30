// アップロードされたファイルから本文テキストを抽出する。
// PDFは unpdf(pdfjsベース) で抽出。txt/md はそのまま読み込む。
import { extractText, getDocumentProxy } from "unpdf";

export async function extractTextFromFile(file: File): Promise<string> {
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";

  if (ext === "pdf") {
    const buffer = new Uint8Array(await file.arrayBuffer());
    const pdf = await getDocumentProxy(buffer);
    // ページ単位で取得し、ページ境界を段落区切り(\n\n)として保持する。
    // mergePages:true は全ページを連結してしまい、構造が失われるため使わない。
    const { text } = await extractText(pdf, { mergePages: false });
    const pages = Array.isArray(text) ? text : [text];
    return pages
      .map((page) => (page ?? "").trim())
      .filter(Boolean)
      .join("\n\n");
  }

  // txt / md などのプレーンテキスト
  return (await file.text()).trim();
}
