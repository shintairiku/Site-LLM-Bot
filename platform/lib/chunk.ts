// 取り込みテキストをRAG用のチャンクへ分割する。
// 「収まる最大の意味単位」で切るため、区切り候補を粗い順に再帰的に適用する：
//   段落(\n\n) → 改行(\n) → 文末(。！？．) → 読点(、) → 空白 → 文字
// これにより、文の途中での無理なぶつ切りを最小化し、最後の手段としてのみ文字単位で割る。

const CHUNK_SIZE = 1000; // 1チャンクの目標文字数
const CHUNK_OVERLAP = 150; // チャンク間で重複させる文字数

// 粗い区切りから細かい区切りへ。末尾の "" は文字単位分割（必ず収束させるため）。
const SEPARATORS = ["\n\n", "\n", "。", "！", "？", "．", "、", " ", ""];

export function chunkText(text: string): string[] {
  const normalized = text.replace(/\r\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
  if (!normalized) return [];

  const atoms = splitToAtoms(normalized, SEPARATORS);
  return mergeAtoms(atoms);
}

/**
 * テキストを CHUNK_SIZE 以下の「アトム」へ再帰分割する。
 * まず粗い区切りで割り、それでも大きい断片は次に細かい区切りで割る。
 */
function splitToAtoms(text: string, separators: string[]): string[] {
  if (text.length <= CHUNK_SIZE) {
    return text.trim() ? [text] : [];
  }

  const [sep, ...rest] = separators;

  // 区切りを使い切った／文字単位指定なら、文字数で強制分割（最終手段）
  if (sep === undefined || sep === "") {
    const out: string[] = [];
    for (let i = 0; i < text.length; i += CHUNK_SIZE) {
      out.push(text.slice(i, i + CHUNK_SIZE));
    }
    return out;
  }

  const pieces = splitKeepingSeparator(text, sep);
  // この区切りで全く割れなかった場合は次の区切りへ
  if (pieces.length <= 1) {
    return splitToAtoms(text, rest);
  }

  const atoms: string[] = [];
  for (const piece of pieces) {
    if (!piece) continue;
    if (piece.length <= CHUNK_SIZE) {
      if (piece.trim()) atoms.push(piece);
    } else {
      atoms.push(...splitToAtoms(piece, rest));
    }
  }
  return atoms;
}

/** 区切り文字を左側の断片に残したまま分割する（句点や改行を保持して文脈を維持）。 */
function splitKeepingSeparator(text: string, sep: string): string[] {
  const result: string[] = [];
  let start = 0;
  let idx = text.indexOf(sep, start);
  while (idx !== -1) {
    result.push(text.slice(start, idx + sep.length));
    start = idx + sep.length;
    idx = text.indexOf(sep, start);
  }
  if (start < text.length) result.push(text.slice(start));
  return result;
}

/** アトムを CHUNK_SIZE まで貪欲に結合し、チャンク間に CHUNK_OVERLAP の重複を持たせる。 */
function mergeAtoms(atoms: string[]): string[] {
  const chunks: string[] = [];
  let current = "";

  for (const atom of atoms) {
    if (current && current.length + atom.length > CHUNK_SIZE) {
      chunks.push(current.trim());
      // 直前チャンクの末尾を重複として引き継ぎ、境界での文脈断絶を緩和する
      current = current.slice(Math.max(0, current.length - CHUNK_OVERLAP));
    }
    current += atom;
  }
  if (current.trim()) chunks.push(current.trim());

  return chunks;
}
