(function () {
  const script = document.currentScript;
  if (!script) {
    return;
  }

  // 埋め込み script タグの data 属性を起点に、ウィジェット表示に必要な設定値を初期化する。
  // この値は下の render 相当の処理と、テーマ反映、モック応答表示で参照される。
  const baseUrl = new URL("./", script.src || window.location.href);
  const cssUrl = new URL("mock-widget.css", baseUrl).toString();
  const apiBase = script.dataset.apiBase || "http://127.0.0.1:8000";
  const tenantId = script.dataset.tenantId || "sample-shintairiku";
  const tenantName = script.dataset.tenantName || "サンプル工務店";
  const accent = script.dataset.color || "#155e75";
  let sessionId = null;
  const suggestions = [
    "施工エリアを教えてください",
    "相談の流れを知りたいです",
    "リフォームも対応していますか？",
  ];

  ensureCss(cssUrl);
  document.documentElement.style.setProperty("--widget-primary", accent);

  // ランチャーボタンと本体パネルを先に構築し、以降の各関数は
  // messagesEl / suggestionsEl / statusEl / textarea を共有してUI更新を行う。
  const launcher = document.createElement("button");
  launcher.className = "mock-chatbot-launcher";
  launcher.type = "button";
  launcher.textContent = "AI相談窓口";

  const panel = document.createElement("section");
  panel.className = "mock-chatbot-panel";
  panel.innerHTML = `
    <div class="mock-chatbot-header">
      <h2>${escapeHtml(tenantName)} AI相談窓口</h2>
      <p>住まいに関するご質問を受け付けています。API未接続時は自動でモック応答に切り替わります。</p>
      <button class="mock-chatbot-close" type="button" aria-label="閉じる">×</button>
    </div>
    <div class="mock-chatbot-messages"></div>
    <div class="mock-chatbot-suggestions"></div>
    <div class="mock-chatbot-status">待機中</div>
    <form class="mock-chatbot-form">
      <textarea placeholder="住まいに関するご質問を入力してください"></textarea>
      <button type="submit">送信</button>
    </form>
  `;

  document.body.appendChild(launcher);
  document.body.appendChild(panel);

  const messagesEl = panel.querySelector(".mock-chatbot-messages");
  const suggestionsEl = panel.querySelector(".mock-chatbot-suggestions");
  const statusEl = panel.querySelector(".mock-chatbot-status");
  const closeButton = panel.querySelector(".mock-chatbot-close");
  const form = panel.querySelector(".mock-chatbot-form");
  const textarea = form.querySelector("textarea");
  const submitButton = form.querySelector("button");

  // 初期メッセージは addMessage に集約しておき、
  // 送信時のユーザー発話追加・モック応答追加も同じ導線で処理する。
  addMessage(
    messagesEl,
    "bot",
    "こんにちは。住まいに関するご質問をお受けします。\nまずは施工エリアや相談の流れなど、簡単な内容からお試しください。"
  );

  // 候補質問ボタンは textarea への入力補助のみを担当する。
  // 実送信は form submit に一本化しているため、入力経路が増えても送信処理が分散しない。
  suggestions.forEach(function (question) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = question;
    button.addEventListener("click", function () {
      textarea.value = question;
      textarea.focus();
    });
    suggestionsEl.appendChild(button);
  });

  // 開閉処理はこのクリックイベントだけに閉じ込め、見た目状態は CSS の is-open で管理する。
  launcher.addEventListener("click", function () {
    panel.classList.toggle("is-open");
    statusEl.textContent = panel.classList.contains("is-open")
      ? "チャットを表示中"
      : "待機中";
    if (panel.classList.contains("is-open")) {
      textarea.focus();
    }
  });

  closeButton.addEventListener("click", function () {
    panel.classList.remove("is-open");
    setStatus(statusEl, "待機中", false);
  });

  // 送信処理の中心。入力値検証、ユーザー発話の描画、状態表示更新のあと、
  // まず API へ問い合わせ、失敗時のみ createMockReply にフォールバックする。
  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    const text = textarea.value.trim();
    if (!text) {
      return;
    }

    textarea.value = "";
    addMessage(messagesEl, "user", text);
    setBusyState(textarea, submitButton, suggestionsEl, true);
    setStatus(statusEl, "APIへ問い合わせ中...", true);

    try {
      const reply = await requestChatAnswer(text);
      sessionId = reply.session_id || sessionId;
      addMessage(messagesEl, "bot", reply.answer);
      setStatus(
        statusEl,
        reply.source === "openai" ? "OpenAI応答を受信しました" : "デモ応答を受信しました",
        false
      );
    } catch (error) {
      addMessage(messagesEl, "bot", createMockReply(text));
      setStatus(statusEl, "API接続に失敗したためモック応答を表示しました", false);
    } finally {
      setBusyState(textarea, submitButton, suggestionsEl, false);
      textarea.focus();
    }
  });

  // Enter だけで送信できるようにし、Shift+Enter は改行に残す。
  textarea.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  // 入力文の簡易ルールに応じてモック応答文を返す。
  // 送信イベントからのみ呼ばれる純粋関数にしているため、
  // 将来は API 応答がない場合のフォールバック文言生成にも流用しやすい。
  function createMockReply(text) {
    if (text.includes("施工") || text.includes("エリア")) {
      return "施工エリアに関するご質問ですね。\n現在の仮ウィジェットでは、対象地域の案内文をここに表示する想定です。";
    }
    if (text.includes("リフォーム")) {
      return "リフォーム相談にも対応する想定です。\n詳細は次工程でAPI接続後にサイト情報を参照して返答します。";
    }
    if (text.includes("相談") || text.includes("流れ")) {
      return "ご相談の流れをご案内する想定です。\n仮実装では、初回相談 -> ヒアリング -> ご提案という導線を表示しています。";
    }
    return "ありがとうございます。\nこの仮ウィジェットでは、次工程でAI回答に置き換わる位置にモック文章を表示しています。";
  }

  // FastAPI 側の最小ハンドラを呼び出す関数。
  // UI 側はこの関数から answer/source を受け取り、描画ロジックとは分離している。
  async function requestChatAnswer(text) {
    const response = await window.fetch(`${apiBase}/api/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        tenant_id: tenantId,
        message: text,
        page_url: window.location.href,
        session_id: sessionId,
      }),
    });
    if (!response.ok) {
      throw new Error("chat api request failed");
    }
    return response.json();
  }

  // 送信中の多重送信を防ぎ、入力部品の状態をまとめて切り替える。
  function setBusyState(textareaEl, submitButtonEl, suggestionsContainer, isBusy) {
    textareaEl.disabled = isBusy;
    submitButtonEl.disabled = isBusy;
    suggestionsContainer.querySelectorAll("button").forEach(function (button) {
      button.disabled = isBusy;
    });
  }

  // ステータス文言と装飾を共通化し、待機中/通信中/完了の表現を揃える。
  function setStatus(statusElement, text, isBusy) {
    statusElement.textContent = text;
    statusElement.classList.toggle("is-busy", isBusy);
  }

  // メッセージ描画の共通関数。
  // 初期メッセージ、ユーザー発話、bot 応答のすべてがここを通ることで、
  // DOM 構造とスクロール制御を一か所で保守できる。
  function addMessage(container, role, text) {
    const node = document.createElement("div");
    node.className = `mock-chatbot-message ${role}`;
    node.textContent = text;
    container.appendChild(node);
    container.scrollTop = container.scrollHeight;
    return node;
  }

  // CSS の重複読み込みを避けつつ、script 設置だけでウィジェットを自己完結させるための関数。
  // ウィジェット本体は見た目をこの関数経由で前提化しているため、初期化のかなり早い段階で実行する。
  function ensureCss(href) {
    if (document.querySelector(`link[href="${href}"]`)) {
      return;
    }
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = href;
    document.head.appendChild(link);
  }

  // パネルのタイトルに tenantName を埋め込むための最低限のエスケープ関数。
  // innerHTML に外部値を入れる箇所はここを通す前提にして、XSS の混入点を限定する。
  function escapeHtml(text) {
    return String(text)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }
})();
